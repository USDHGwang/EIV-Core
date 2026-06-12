"""
EIV — AttestationSink (attesting the verdict)

After validation, the result is attested to an ERC-8004 ValidationRegistry. How
it is sent is encapsulated behind an interface:

    attest(intent_hash, result) -> attestation_ref

The current StubAttestationSink prints the corresponding ERC-8004
validationResponse (request_hash / response code / tag) and returns a simulated
tx ref (nothing is written on-chain).

ERC-8004 ValidationRegistry field mapping:
  - request_hash: hash of the validated content (here, intent_hash).
  - response    : a uint8 score 0-100. This layer uses 100 = full compliance
                  (PASS), 0 = violation (FAIL).
  - tag         : a bytes32 label identifying the validation type and verdict.
(The exact ABI depends on the contract version, so it is centralized in
build_validation_response.)
"""

from __future__ import annotations

import hashlib
import json
import sys
from typing import Protocol, TextIO

from eiv.schema import VERDICT_PASS

RESPONSE_PASS = 100  # ERC-8004 response score: full compliance
RESPONSE_FAIL = 0  # ERC-8004 response score: violation
TAG_PREFIX = "EIV.L2"  # L2 = Intent-Spec Compliance (authorization compliance)


def build_validation_response(intent_hash: str, result: dict) -> dict:
    """Build the ERC-8004 validationResponse payload from the result schema.

    Single source of truth: both the sink and the service produce the payload
    through this function.
    TODO: when writing on-chain, ABI-encode these fields as the
    ValidationRegistry.validationResponse parameters.
    """
    verdict = result.get("verdict")
    code = RESPONSE_PASS if verdict == VERDICT_PASS else RESPONSE_FAIL
    return {
        "request_hash": intent_hash,
        "response": code,
        "tag": f"{TAG_PREFIX}.{verdict}",
        "verdict": verdict,
        "n_violations": len(result.get("violations", [])),
    }


def _mock_tx_ref(payload: dict) -> str:
    """Derive a deterministic simulated tx hash (0x + 64 hex) from the payload."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "0x" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


class AttestationSink(Protocol):
    """Interface for sending the verdict; returns an attestation reference
    (a tx hash in a production implementation)."""

    def attest(self, intent_hash: str, result: dict) -> str: ...


class StubAttestationSink:
    """Prints the corresponding ERC-8004 validationResponse and returns a
    simulated tx ref (nothing is written on-chain).

    TODO: replace with OnChainAttestationSink (writes to the on-chain ValidationRegistry).
    """

    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream: TextIO = stream or sys.stdout
        self.last_payload: dict | None = None

    def attest(self, intent_hash: str, result: dict) -> str:
        payload = build_validation_response(intent_hash, result)
        self.last_payload = payload
        ref = _mock_tx_ref(payload)
        print(
            "[EIV attest -> ERC-8004 ValidationRegistry (reference impl, not written on-chain)]\n"
            f"    request_hash : {payload['request_hash']}\n"
            f"    response     : {payload['response']}  ({payload['verdict']})\n"
            f"    tag          : {payload['tag']}\n"
            f"    n_violations : {payload['n_violations']}\n"
            f"    -> tx ref    : {ref}",
            file=self.stream,
        )
        return ref


class OnChainAttestationSink:
    """Writes the verdict to an ERC-8004 ValidationRegistry on-chain.

    Builds the calldata for
        validationResponse(bytes32 requestHash, bytes response,
                           string responseURI, bytes32 responseHash, string tag)
    signs an EIP-1559 transaction with the attester key, and broadcasts it over
    JSON-RPC — all standard library (see eiv.eth).

    Field mapping:
      requestHash  = the intent's EIP-712 digest (what the authorizer signed)
      response     = single byte score: 100 (PASS) / 0 (FAIL)
      responseURI  = where the full validation record can be fetched
                     (response_uri_base + requestHash; empty when unset)
      responseHash = keccak256 of the canonical result JSON, so the on-chain
                     record commits to the exact violation set
      tag          = "EIV.L2.PASS" / "EIV.L2.FAIL"

    dry_run=True builds and signs the transaction but does not broadcast it
    (the attestation_ref is "dryrun:<tx_hash>" and the raw tx is kept in
    last_raw_tx) — useful for rehearsing without spending gas.
    transport is injectable for tests: (method, params) -> result.
    """

    _SIGNATURE = "validationResponse(bytes32,bytes,string,bytes32,string)"
    _TYPES = ["bytes32", "bytes", "string", "bytes32", "string"]
    _FALLBACK_GAS = 300_000

    def __init__(
        self,
        rpc_url: str,
        registry_address: str,
        private_key: str,
        chain_id: int | None = None,
        response_uri_base: str = "",
        dry_run: bool = False,
        transport=None,
        timeout: float = 30.0,
    ) -> None:
        from eiv.eth import http_rpc_transport, privkey_to_address

        self.rpc_url = rpc_url
        self.registry_address = registry_address
        self._private_key = int(private_key, 16) if isinstance(private_key, str) else private_key
        self.chain_id = chain_id
        self.response_uri_base = response_uri_base
        self.dry_run = dry_run
        self._rpc = transport or http_rpc_transport(rpc_url, timeout=timeout)
        self.attester_address = privkey_to_address(self._private_key)
        self.last_payload: dict | None = None
        self.last_raw_tx: str | None = None

    def _build_calldata(self, intent_hash: str, result: dict, payload: dict) -> bytes:
        from eiv.eth import abi_call_data, keccak256

        result_blob = json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")
        response_uri = (
            f"{self.response_uri_base.rstrip('/')}/{payload['request_hash']}"
            if self.response_uri_base
            else ""
        )
        return abi_call_data(
            self._SIGNATURE,
            self._TYPES,
            [
                payload["request_hash"],
                bytes([payload["response"]]),
                response_uri,
                keccak256(result_blob),
                payload["tag"],
            ],
        )

    def attest(self, intent_hash: str, result: dict) -> str:
        from eiv.eth import from_hex_quantity, sign_eip1559_tx

        payload = build_validation_response(intent_hash, result)
        self.last_payload = payload
        data = self._build_calldata(intent_hash, result, payload)

        chain_id = self.chain_id or from_hex_quantity(self._rpc("eth_chainId", []))
        nonce = from_hex_quantity(
            self._rpc("eth_getTransactionCount", [self.attester_address, "pending"])
        )
        gas_price = from_hex_quantity(self._rpc("eth_gasPrice", []))
        max_priority = min(gas_price, 2 * 10**9)  # <= 2 gwei tip
        # eth_gasPrice already includes the base fee; 1.25x covers ~2 blocks
        # of maximum base-fee growth without overshooting small balances.
        max_fee = gas_price * 5 // 4 + max_priority

        try:
            gas_limit = from_hex_quantity(
                self._rpc(
                    "eth_estimateGas",
                    [{
                        "from": self.attester_address,
                        "to": self.registry_address,
                        "data": "0x" + data.hex(),
                    }],
                )
            ) * 5 // 4  # headroom; unused gas is refunded
        except Exception:  # noqa: BLE001 — estimation is best-effort
            gas_limit = self._FALLBACK_GAS

        raw, tx_hash = sign_eip1559_tx(
            self._private_key,
            chain_id=chain_id,
            nonce=nonce,
            max_priority_fee=max_priority,
            max_fee=max_fee,
            gas_limit=gas_limit,
            to=self.registry_address,
            value=0,
            data=data,
        )
        self.last_raw_tx = "0x" + raw.hex()

        if self.dry_run:
            return f"dryrun:{tx_hash}"
        sent = self._rpc("eth_sendRawTransaction", [self.last_raw_tx])
        return sent or tx_hash
