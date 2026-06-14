"""
EIV — ChainAdapter (source of execution traces)

The validator needs what actually happened on-chain (ExecutionTrace). How it is
obtained is encapsulated behind an interface:

    get_execution_trace(tx_ref, spec=None) -> ExecutionTrace

Implementations:
  - MockChainAdapter : loads traces from JSON fixtures (tests, demos, and
                       clients that supply the trace themselves).
  - RpcChainAdapter  : reconstructs the trace from a live node over JSON-RPC —
                       receipt + logs + block timestamp + post-execution
                       allowance reads. Standard library only.

`spec` is optional context: the trace amounts (amount_in / amount_out) are
defined relative to the authorized token pair, so the RPC adapter uses the
spec's token_in / token_out to compute them. MockChainAdapter ignores it
(fixture traces carry precomputed amounts).

RPC reconstruction model (documented honestly):
  - calls_to            : the tx `to` plus every contract that emitted a log.
                          Without a debug_trace endpoint this is the observable
                          call set; contracts touched silently (no logs, no
                          events) are not visible. The A:Target check therefore
                          covers every state-changing token interaction, which
                          is where funds move.
  - approvals           : ERC-20 Approval events where owner == tx sender.
  - transfers_out       : terminal ERC-20 Transfer events — transfers whose
                          recipient is not itself a touched contract (i.e. what
                          actually left the execution towards end recipients).
                          Restricted to the spec's token_out when spec is given.
                          Native ETH (tx.value) is injected as a synthetic entry
                          using the NATIVE_ETH sentinel (0xeeee...eeee, EIP-7528)
                          when the tx succeeds and value > 0.
  - amount_in           : total token_in transferred out of the tx sender.
                          Includes native ETH value when token_in is NATIVE_ETH.
  - amount_out          : total token_out delivered to terminal recipients
                          (regardless of who received it — sending output to an
                          attacker must still count as output, so B:Recipient
                          can flag the destination). Includes native ETH value
                          when token_out is NATIVE_ETH.
  - residual_allowances : allowance(sender, spender) read via eth_call at the
                          tx's block for every spender that received an
                          approval; falls back to the latest block on
                          non-archive nodes, then to the final Approval event
                          value.
  - block_ts            : the block timestamp.

Addresses are normalized to the spec's own spelling when they match
case-insensitively, so checksummed intents and lowercase logs compare equal in
the (string-based) predicate engine.
"""

from __future__ import annotations

import json
import os
from typing import Callable, Optional, Protocol

from eiv.eth import (
    EthRpcError,
    from_hex_quantity,
    function_selector,
    http_rpc_transport,
    keccak256_text,
)
from eiv.predicates import Approval, ExecutionTrace, IntentSpec, Transfer
from eiv.schema import build_trace, require_eth_addresses

_DEFAULT_TRACES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "traces")

# Event topics, computed (not hardcoded) from the canonical signatures.
TRANSFER_TOPIC = "0x" + keccak256_text("Transfer(address,address,uint256)").hex()
APPROVAL_TOPIC = "0x" + keccak256_text("Approval(address,address,uint256)").hex()
_ALLOWANCE_SELECTOR = function_selector("allowance(address,address)")

# EIP-7528 sentinel for native ETH in token-position fields.
NATIVE_ETH = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"


class TraceNotFound(KeyError):
    """No execution trace found for the given tx_ref."""

    def __str__(self) -> str:
        # KeyError.__str__ wraps the message in quotes (repr); override to the raw
        # message so API error responses are clean.
        return self.args[0] if self.args else self.__class__.__name__


class ChainAdapter(Protocol):
    """Interface for obtaining an execution trace.

    Implementations that connect to real chain data (RPC, indexer) must call
    require_eth_addresses(spec) before processing to prevent symbol-based
    specs from silently bypassing predicate checks.
    """

    def get_execution_trace(self, tx_ref: str, spec=None) -> ExecutionTrace: ...


class MockChainAdapter:
    """Loads ExecutionTrace from JSON fixtures.

    Resolution order:
      1. Check the in-memory registry first (register() for dynamic entries,
         convenient for HTTP / tests).
      2. Otherwise read {traces_dir}/{tx_ref}.json.

    tx_ref is basename-sanitized to prevent path traversal; it is essentially the
    fixture filename (without .json).
    """

    def __init__(
        self,
        traces_dir: Optional[str] = None,
        registry: Optional[dict] = None,
    ) -> None:
        self.traces_dir = traces_dir or _DEFAULT_TRACES_DIR
        self.registry: dict[str, dict] = dict(registry or {})

    def register(self, tx_ref: str, trace_dict: dict) -> None:
        """Register a trace dynamically (e.g. for tests, or when a client supplies the trace)."""
        self.registry[tx_ref] = trace_dict

    def get_execution_trace(self, tx_ref: str, spec=None) -> ExecutionTrace:
        if tx_ref in self.registry:
            return build_trace(self.registry[tx_ref])

        safe = os.path.basename(str(tx_ref))
        if safe in ("", ".", ".."):
            raise TraceNotFound(f"invalid tx_ref: {tx_ref!r}")
        if not safe.endswith(".json"):
            safe += ".json"
        path = os.path.join(self.traces_dir, safe)
        if not os.path.isfile(path):
            raise TraceNotFound(f"no trace found for tx_ref {tx_ref!r} ({path})")
        with open(path, encoding="utf-8") as f:
            return build_trace(json.load(f))


def _topic_to_address(topic: str) -> str:
    return ("0x" + topic[-40:]).lower()


class FallbackChainAdapter:
    """Try MockChainAdapter (fixtures) first, fall back to RpcChainAdapter.

    This lets fixture-based demo scenarios and live-chain tx_refs coexist
    when RPC_URL is set.
    """

    def __init__(self, mock: MockChainAdapter, rpc: "RpcChainAdapter") -> None:
        self.mock = mock
        self.rpc = rpc
        self.rpc_url = rpc.rpc_url

    def get_execution_trace(self, tx_ref: str, spec=None) -> ExecutionTrace:
        try:
            return self.mock.get_execution_trace(tx_ref, spec)
        except TraceNotFound:
            return self.rpc.get_execution_trace(tx_ref, spec)


class RpcChainAdapter:
    """Reconstructs an ExecutionTrace from a live EVM node over JSON-RPC.

    transport is injectable for tests: a callable (method, params) -> result.
    The default is a urllib JSON-RPC client against rpc_url.
    """

    def __init__(
        self,
        rpc_url: str,
        transport: Optional[Callable] = None,
        timeout: float = 20.0,
        max_retries: int = 3,
        fallback_url: Optional[str] = None,
    ) -> None:
        self.rpc_url = rpc_url
        self._rpc = transport or http_rpc_transport(
            rpc_url, timeout=timeout, max_retries=max_retries,
            fallback_url=fallback_url,
        )

    # -- helpers ------------------------------------------------------------

    def _vocabulary(self, spec) -> dict:
        """Map lowercase address -> the spec's own spelling, so trace strings
        compare equal in the string-based predicate engine."""
        vocab: dict[str, str] = {}
        if spec is None:
            return vocab
        names = set(spec.allowed_targets) | set(spec.allowed_spenders)
        names |= {spec.token_in, spec.token_out, spec.recipient}
        for name in names:
            if isinstance(name, str):
                vocab[name.lower()] = name
        return vocab

    def _call_allowance(self, token: str, owner: str, spender: str, block_tag: str) -> Optional[int]:
        data = (
            _ALLOWANCE_SELECTOR
            + bytes.fromhex(owner[2:]).rjust(32, b"\x00")
            + bytes.fromhex(spender[2:]).rjust(32, b"\x00")
        )
        try:
            out = self._rpc(
                "eth_call", [{"to": token, "data": "0x" + data.hex()}, block_tag]
            )
            return from_hex_quantity(out) if out and out != "0x" else 0
        except EthRpcError:
            return None

    # -- main ---------------------------------------------------------------

    def get_execution_trace(self, tx_ref: str, spec=None) -> ExecutionTrace:
        if spec is not None:
            require_eth_addresses(spec)
        receipt = self._rpc("eth_getTransactionReceipt", [tx_ref])
        if not receipt:
            raise TraceNotFound(f"no transaction receipt for tx_ref {tx_ref!r} on {self.rpc_url}")
        tx = self._rpc("eth_getTransactionByHash", [tx_ref]) or {}
        block = self._rpc("eth_getBlockByNumber", [receipt.get("blockNumber"), False]) or {}

        vocab = self._vocabulary(spec)

        def canon(addr: str) -> str:
            a = (addr or "").lower()
            return vocab.get(a, a)

        sender = (tx.get("from") or receipt.get("from") or "").lower()
        logs = receipt.get("logs") or []

        # Observable call set: tx target + every log-emitting contract.
        touched_lower: set = set()
        if receipt.get("to") or tx.get("to"):
            touched_lower.add((receipt.get("to") or tx.get("to")).lower())
        for log in logs:
            touched_lower.add((log.get("address") or "").lower())
        touched_lower.discard("")

        # Decode ERC-20 Transfer / Approval events.
        transfers = []  # (token_lower, from_lower, to_lower, amount)
        approvals = []  # (token_lower, owner_lower, spender_lower, amount)
        for log in logs:
            topics = log.get("topics") or []
            if len(topics) < 3:
                continue
            token = (log.get("address") or "").lower()
            amount = from_hex_quantity(log.get("data") or "0x0") if log.get("data") not in (None, "0x") else 0
            if topics[0].lower() == TRANSFER_TOPIC:
                transfers.append(
                    (token, _topic_to_address(topics[1]), _topic_to_address(topics[2]), amount)
                )
            elif topics[0].lower() == APPROVAL_TOPIC:
                approvals.append(
                    (token, _topic_to_address(topics[1]), _topic_to_address(topics[2]), amount)
                )

        token_in = spec.token_in.lower() if spec is not None else None
        token_out = spec.token_out.lower() if spec is not None else None

        # Terminal transfers: recipient is not itself a touched contract.
        terminal = [t for t in transfers if t[2] not in touched_lower]
        transfers_out = [
            {"token": canon(t[0]), "to": canon(t[2]), "amount": str(t[3])}
            for t in terminal
            if token_out is None or t[0] == token_out
        ]

        amount_in = sum(t[3] for t in transfers if t[1] == sender and (token_in is None or t[0] == token_in))
        amount_out = sum(t[3] for t in terminal if token_out is None or t[0] == token_out)

        # Native ETH value transfer (tx.value): handled separately from ERC-20
        # logs because tx.to is always in touched_lower (the terminal filter
        # would exclude it). Direct injection into transfers_out and amounts.
        tx_status = from_hex_quantity(receipt.get("status") or "0x1")
        eth_value = from_hex_quantity(tx.get("value") or "0x0")
        if tx_status == 1 and eth_value > 0:
            tx_to = (receipt.get("to") or tx.get("to") or "").lower()
            if tx_to:
                if token_in is None or NATIVE_ETH == token_in:
                    amount_in += eth_value
                if token_out is None or NATIVE_ETH == token_out:
                    transfers_out.append(
                        {"token": canon(NATIVE_ETH), "to": canon(tx_to), "amount": str(eth_value)}
                    )
                    amount_out += eth_value

        # Approvals granted by the sender during this execution.
        sender_approvals = [a for a in approvals if a[1] == sender]
        approvals_out = [
            {"spender": canon(a[2]), "amount": str(a[3])} for a in sender_approvals
        ]

        # Residual allowances after execution: eth_call at the tx block, falling
        # back to latest (non-archive nodes), then to the final Approval value.
        block_tag = receipt.get("blockNumber") or "latest"
        residual: dict[str, str] = {}
        last_seen: dict[tuple, int] = {}
        for token, _owner, spender, amount in sender_approvals:
            last_seen[(token, spender)] = amount
        for (token, spender), fallback_amount in last_seen.items():
            value = self._call_allowance(token, sender, spender, block_tag)
            if value is None and block_tag != "latest":
                value = self._call_allowance(token, sender, spender, "latest")
            if value is None:
                value = fallback_amount
            key = canon(spender)
            residual[key] = str(max(int(residual.get(key, "0")), value))

        trace_dict = {
            "calls_to": sorted(canon(a) for a in touched_lower),
            "approvals": approvals_out,
            "transfers_out": transfers_out,
            "amount_in": str(amount_in),
            "amount_out": str(amount_out),
            "block_ts": str(from_hex_quantity(block.get("timestamp") or "0x0")),
            "residual_allowances": residual,
        }
        return build_trace(trace_dict)


# ---------------------------------------------------------------------------
# GATE mode — calldata-level pre-execution trace decoding
# ---------------------------------------------------------------------------

# ERC-20 function selectors (4 bytes)
_TRANSFER_SEL = function_selector("transfer(address,uint256)")
_APPROVE_SEL = function_selector("approve(address,uint256)")
_TRANSFER_FROM_SEL = function_selector("transferFrom(address,address,uint256)")


def _decode_address(data: bytes, offset: int) -> str:
    return "0x" + data[offset + 12 : offset + 32].hex()


def _decode_uint256(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 32], "big")


def decode_proposed_trace(proposed_tx: dict, spec: IntentSpec) -> ExecutionTrace:
    """Build a pre-execution trace from a proposed transaction's calldata.

    Decodes ERC-20 transfer/approve/transferFrom signatures and maps them to
    ExecutionTrace fields so predicates can catch authorization violations
    (A:Target, B:Recipient, C:AuthExpansion, E:Deadline) before execution.

    Limitations (transparent): D:Amount output and F:Residual cannot be
    determined pre-execution; they are set to optimistic values that won't
    trigger false positives. The caller should mark the result as partial.
    """
    # Build vocabulary for address canonicalization (same as RpcChainAdapter)
    vocab: dict[str, str] = {}
    names = set(spec.allowed_targets) | set(spec.allowed_spenders)
    names |= {spec.token_in, spec.token_out, spec.recipient}
    for name in names:
        if isinstance(name, str):
            vocab[name.lower()] = name

    def canon(addr: str) -> str:
        a = (addr or "").lower()
        return vocab.get(a, a)

    to_addr = canon((proposed_tx.get("to") or ""))
    data_hex = proposed_tx.get("data") or "0x"
    try:
        data = bytes.fromhex(data_hex[2:]) if len(data_hex) > 2 else b""
    except ValueError:
        data = b""
    value = from_hex_quantity(proposed_tx.get("value") or "0x0")
    sender = (proposed_tx.get("from") or "").lower()

    calls_to = [to_addr] if to_addr else []
    approvals_list: list[Approval] = []
    transfers_list: list[Transfer] = []
    amount_in = 0

    if len(data) >= 4:
        sel = data[:4]

        if sel == _APPROVE_SEL and len(data) >= 68:
            spender = canon(_decode_address(data, 4))
            amount = _decode_uint256(data, 36)
            approvals_list.append(Approval(spender, amount))

        elif sel == _TRANSFER_SEL and len(data) >= 68:
            recipient = canon(_decode_address(data, 4))
            amount = _decode_uint256(data, 36)
            transfers_list.append(Transfer(to_addr, recipient, amount))
            amount_in = amount

        elif sel == _TRANSFER_FROM_SEL and len(data) >= 100:
            _from = _decode_address(data, 4)
            to = canon(_decode_address(data, 36))
            amount = _decode_uint256(data, 68)
            transfers_list.append(Transfer(to_addr, to, amount))
            if _from == sender:
                amount_in = amount

    if value > 0:
        transfers_list.append(Transfer(canon(NATIVE_ETH), to_addr, value))
        amount_in += value

    return ExecutionTrace(
        calls_to=calls_to,
        approvals=approvals_list,
        transfers_out=transfers_list,
        amount_in=amount_in,
        amount_out=spec.min_amount_out,
        block_ts=int(__import__("time").time()),
        residual_allowances={},
    )
