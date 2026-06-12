"""
EIV — schema / serialization layer

predicates.py's validation engine uses dataclasses (IntentSpec / ExecutionTrace),
while the external interfaces (HTTP body, JSON fixtures, attestation payload) are
all JSON. This module bridges the two:

    JSON dict  <->  dataclass

It also provides related helpers: amount parsing (uint256-safe), intent hashing,
and validate_json() for validating directly from dicts.

Design notes:
- Amounts are always represented as strings in JSON (uint256 exceeds the
  JavaScript Number safe range) and parsed to int; accepts int / decimal string /
  0x hex string / the "UNLIMITED" sentinel.
- This module contains no validation rules — rules live only in
  predicates.validate(); here we only convert types.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from eiv.predicates import (
    SPEC_VERSION,
    UNLIMITED,
    Approval,
    ExecutionTrace,
    IntentSpec,
    Transfer,
    validate,
)

# result schema enum values (consistent with predicates.Severity)
VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
SEVERITY_FAIL = "FAIL"
SEVERITY_WARN_SAFETY = "WARN-SAFETY"
SEVERITY_WARN_SPEC = "WARN-SPEC"

# Reserved envelope keys (signature wrapper) that are not part of IntentSpec itself
_ENVELOPE_KEYS = ("spec", "signature", "signer", "domain")


class IntentParseError(ValueError):
    """Malformed intent JSON or missing fields."""


class TraceParseError(ValueError):
    """Malformed execution trace JSON or missing fields."""


class AddressPinningError(ValueError):
    """Address-type fields contain non-address values (symbols, names, etc.)."""


_ETH_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def is_eth_address(s: str) -> bool:
    return isinstance(s, str) and bool(_ETH_ADDRESS_RE.match(s))


def require_eth_addresses(spec: "IntentSpec") -> None:
    """Validate that all address-type fields are valid Ethereum addresses.

    Raises AddressPinningError listing every non-address field. This guards
    against symbol-based specs (e.g. "USDC" instead of 0x...) hitting an RPC
    adapter, where B:Recipient comparison would silently fail.
    """
    bad: list[str] = []
    for label, value in [("token_in", spec.token_in), ("token_out", spec.token_out),
                         ("recipient", spec.recipient)]:
        if not is_eth_address(value):
            bad.append(f"{label}={value!r}")
    for addr in spec.allowed_targets:
        if not is_eth_address(addr):
            bad.append(f"allowed_targets: {addr!r}")
    for addr in spec.allowed_spenders:
        if not is_eth_address(addr):
            bad.append(f"allowed_spenders: {addr!r}")
    if bad:
        raise AddressPinningError(
            f"spec contains non-address values (use contract addresses, not symbols): {', '.join(bad)}"
        )


def parse_amount(x: Any) -> int:
    """Parse a JSON amount into an int. Accepts int / decimal string / 0x hex / "UNLIMITED".

    uint256 exceeds the safe range of a JSON number (JavaScript Number), so
    amounts are transmitted as strings.
    """
    if isinstance(x, bool):  # bool is a subclass of int; reject explicitly
        raise IntentParseError(f"amount must not be a bool: {x!r}")
    if isinstance(x, int):
        return x
    if isinstance(x, str):
        s = x.strip()
        if s.upper() == "UNLIMITED":
            return UNLIMITED
        try:
            if s.lower().startswith("0x"):
                return int(s, 16)
            return int(s)
        except ValueError as e:
            raise IntentParseError(f"cannot parse amount {x!r}: {e}") from e
    raise IntentParseError(f"unsupported amount type: {type(x).__name__}")


def split_envelope(obj: dict) -> tuple[dict, dict]:
    """Split an intent object into (spec_dict, envelope_dict).

    Supports two input formats:
      1. Enveloped: {"spec": {...}, "signature": ..., "signer": ...}
      2. Flat:      {...spec fields..., "signature": ..., "signer": ...}
    """
    if not isinstance(obj, dict):
        raise IntentParseError(f"intent must be an object, got {type(obj).__name__}")
    if isinstance(obj.get("spec"), dict):
        spec_dict = obj["spec"]
    else:
        spec_dict = {k: v for k, v in obj.items() if k not in _ENVELOPE_KEYS}
    envelope = {
        "signature": obj.get("signature"),
        "signer": obj.get("signer"),
        "domain": obj.get("domain"),
    }
    return spec_dict, envelope


def _ensure_seq(value: Any, field: str, exc: type) -> list:
    """Require a JSON array; reject strings/bytes (set()/list() would split them
    into characters and silently produce wrong results)."""
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple, set)):
        raise exc(f"{field} must be an array, got {type(value).__name__}")
    return list(value)


def _ensure_map(value: Any, field: str, exc: type) -> dict:
    """Require a JSON object (dict); otherwise a later .items() would raise AttributeError."""
    if not isinstance(value, dict):
        raise exc(f"{field} must be an object, got {type(value).__name__}")
    return value


def build_intent_spec(spec_dict: dict) -> IntentSpec:
    """dict -> IntentSpec. Raises IntentParseError on missing required fields."""
    required = (
        "allowed_targets",
        "allowed_spenders",
        "token_in",
        "token_out",
        "max_amount_in",
        "min_amount_out",
        "recipient",
        "deadline",
    )
    missing = [k for k in required if k not in spec_dict]
    if missing:
        raise IntentParseError(f"intent spec missing fields: {', '.join(missing)}")
    # Type-check outside the try so the error is clear (avoid strings being split
    # into a set of characters by set()).
    allowed_targets = _ensure_seq(spec_dict["allowed_targets"], "allowed_targets", IntentParseError)
    allowed_spenders = _ensure_seq(spec_dict["allowed_spenders"], "allowed_spenders", IntentParseError)
    try:
        return IntentSpec(
            allowed_targets=set(allowed_targets),
            allowed_spenders=set(allowed_spenders),
            token_in=spec_dict["token_in"],
            token_out=spec_dict["token_out"],
            max_amount_in=parse_amount(spec_dict["max_amount_in"]),
            min_amount_out=parse_amount(spec_dict["min_amount_out"]),
            recipient=spec_dict["recipient"],
            deadline=parse_amount(spec_dict["deadline"]),
            require_zero_residual=bool(spec_dict.get("require_zero_residual", True)),
            bounded_approval=bool(spec_dict.get("bounded_approval", True)),
            max_slippage_bps=(
                None
                if spec_dict.get("max_slippage_bps") is None
                else int(spec_dict["max_slippage_bps"])
            ),
            spec_version=str(spec_dict.get("spec_version", SPEC_VERSION)),
        )
    except (TypeError, ValueError) as e:
        raise IntentParseError(f"failed to parse intent spec: {e}") from e


def build_trace(trace_dict: dict) -> ExecutionTrace:
    """dict -> ExecutionTrace. Raises TraceParseError on missing required fields."""
    if not isinstance(trace_dict, dict):
        raise TraceParseError(f"trace must be an object, got {type(trace_dict).__name__}")
    required = ("amount_in", "amount_out", "block_ts")
    missing = [k for k in required if k not in trace_dict]
    if missing:
        raise TraceParseError(f"execution trace missing fields: {', '.join(missing)}")
    # Type-check outside the try (residual must be an object, otherwise .items()
    # would raise an uncaught AttributeError).
    calls_to = _ensure_seq(trace_dict.get("calls_to", []), "calls_to", TraceParseError)
    approvals = _ensure_seq(trace_dict.get("approvals", []), "approvals", TraceParseError)
    transfers = _ensure_seq(trace_dict.get("transfers_out", []), "transfers_out", TraceParseError)
    residual = _ensure_map(
        trace_dict.get("residual_allowances", {}), "residual_allowances", TraceParseError
    )
    try:
        return ExecutionTrace(
            calls_to=calls_to,
            approvals=[Approval(a["spender"], parse_amount(a["amount"])) for a in approvals],
            transfers_out=[
                Transfer(t["token"], t["to"], parse_amount(t["amount"])) for t in transfers
            ],
            amount_in=parse_amount(trace_dict["amount_in"]),
            amount_out=parse_amount(trace_dict["amount_out"]),
            block_ts=parse_amount(trace_dict["block_ts"]),
            residual_allowances={k: parse_amount(v) for k, v in residual.items()},
        )
    except (TypeError, KeyError, ValueError) as e:
        raise TraceParseError(f"failed to parse execution trace: {e}") from e


def spec_to_canonical(spec: IntentSpec) -> dict:
    """IntentSpec -> a reproducible canonical dict (sets sorted, amounts as strings).

    Used for intent hashing and as the spec content returned in a record.
    """
    return {
        "spec_version": spec.spec_version,
        "allowed_targets": sorted(spec.allowed_targets),
        "allowed_spenders": sorted(spec.allowed_spenders),
        "token_in": spec.token_in,
        "token_out": spec.token_out,
        "max_amount_in": str(spec.max_amount_in),
        "min_amount_out": str(spec.min_amount_out),
        "recipient": spec.recipient,
        "deadline": spec.deadline,
        "require_zero_residual": spec.require_zero_residual,
        "bounded_approval": spec.bounded_approval,
        "max_slippage_bps": spec.max_slippage_bps,
    }


def compute_intent_hash(spec: IntentSpec) -> str:
    """Stable hash of an intent (used as the attestation request_hash).

    Currently the sha256 of the canonical JSON.
    TODO: switch to an EIP-712 typed-data digest (same hash as the on-chain authorization).
    """
    payload = json.dumps(spec_to_canonical(spec), sort_keys=True, separators=(",", ":"))
    return "0x" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_json(intent: dict | str, trace: dict | str) -> dict:
    """Convenience function: validate directly from JSON (dict or string), returning the result schema.

    Rules come from predicates.validate().
    """
    intent_obj = intent if isinstance(intent, dict) else json.loads(intent)
    trace_obj = trace if isinstance(trace, dict) else json.loads(trace)
    spec_dict, _ = split_envelope(intent_obj)
    spec = build_intent_spec(spec_dict)
    tr = build_trace(trace_obj)
    return validate(spec, tr)
