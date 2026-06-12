"""
EIV — EIP-712 typed-data hashing and signature verification for IntentSpec.

This replaces StubEIP712Verifier with real cryptographic verification: the
intent's EIP-712 digest is rebuilt from the spec content, the signature is
recovered (ecrecover), and the recovered address must equal the declared
signer. A tampered spec or a wrong signer fails verification — the
authorization is now actually checked, not assumed.

Typed-data layout
-----------------
struct IntentSpec {
    string[] allowedTargets;   // sorted, from spec_to_canonical
    string[] allowedSpenders;  // sorted
    string   tokenIn;
    string   tokenOut;
    uint256  maxAmountIn;
    uint256  minAmountOut;
    string   recipient;
    uint256  deadline;
    bool     requireZeroResidual;
    bool     boundedApproval;
    int256   maxSlippageBps;   // -1 when the spec leaves it unset
}
domain = EIP712Domain(string name, string version, uint256 chainId)
         name = "EIV", version = "1"

Targets / tokens / recipient are typed as `string` rather than `address` on
purpose: EIV validates executions on any chain (or against symbolic test
fixtures) and the spec recommends — but does not require — address-pinned
values. The digest is computed over the same canonical ordering that
spec_to_canonical produces, so Python and any future Solidity verifier hash
the same words (the array hashing follows EIP-712: keccak of the concatenated
keccak hashes of each member).

The signing helper (sign_intent / CLI below) exists so demos, fixtures, and
integration tests can produce genuinely signed intents with a local key.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from eiv.eth import (
    ecdsa_recover,
    ecdsa_sign,
    keccak256,
    keccak256_text,
    parse_signature_hex,
    privkey_to_address,
    pubkey_to_address,
    signature_to_hex,
)
from eiv.predicates import IntentSpec
from eiv.schema import spec_to_canonical

DEFAULT_CHAIN_ID = 11155111  # Sepolia — where the registry contract deploys

DOMAIN_NAME = "EIV"
DOMAIN_VERSION = "1"

_DOMAIN_TYPEHASH = keccak256_text("EIP712Domain(string name,string version,uint256 chainId)")
_INTENT_TYPE = (
    "IntentSpec(string[] allowedTargets,string[] allowedSpenders,string tokenIn,"
    "string tokenOut,uint256 maxAmountIn,uint256 minAmountOut,string recipient,"
    "uint256 deadline,bool requireZeroResidual,bool boundedApproval,int256 maxSlippageBps)"
)
_INTENT_TYPEHASH = keccak256_text(_INTENT_TYPE)
_NAME_HASH = keccak256_text(DOMAIN_NAME)
_VERSION_HASH = keccak256_text(DOMAIN_VERSION)


def env_chain_id() -> int:
    raw = os.environ.get("CHAIN_ID", "").strip()
    try:
        return int(raw, 0) if raw else DEFAULT_CHAIN_ID
    except ValueError:
        return DEFAULT_CHAIN_ID


def _word_uint(n: int) -> bytes:
    return int(n).to_bytes(32, "big")


def _word_int256(n: int) -> bytes:
    return int(n).to_bytes(32, "big", signed=True)


def _word_bool(b: bool) -> bytes:
    return _word_uint(1 if b else 0)


def _hash_string(s: str) -> bytes:
    return keccak256_text(s)


def _hash_string_array(items: list) -> bytes:
    return keccak256(b"".join(_hash_string(s) for s in items))


def domain_separator(chain_id: int) -> bytes:
    return keccak256(_DOMAIN_TYPEHASH + _NAME_HASH + _VERSION_HASH + _word_uint(chain_id))


def struct_hash(spec: IntentSpec) -> bytes:
    c = spec_to_canonical(spec)
    slippage = -1 if c["max_slippage_bps"] is None else int(c["max_slippage_bps"])
    return keccak256(
        _INTENT_TYPEHASH
        + _hash_string_array(c["allowed_targets"])
        + _hash_string_array(c["allowed_spenders"])
        + _hash_string(c["token_in"])
        + _hash_string(c["token_out"])
        + _word_uint(int(c["max_amount_in"]))
        + _word_uint(int(c["min_amount_out"]))
        + _hash_string(c["recipient"])
        + _word_uint(int(c["deadline"]))
        + _word_bool(c["require_zero_residual"])
        + _word_bool(c["bounded_approval"])
        + _word_int256(slippage)
    )


def intent_digest(spec: IntentSpec, chain_id: Optional[int] = None) -> bytes:
    """The EIP-712 digest an authorizer signs: keccak(0x1901 ‖ domain ‖ structHash)."""
    cid = chain_id if chain_id is not None else env_chain_id()
    return keccak256(b"\x19\x01" + domain_separator(cid) + struct_hash(spec))


def intent_digest_hex(spec: IntentSpec, chain_id: Optional[int] = None) -> str:
    return "0x" + intent_digest(spec, chain_id).hex()


def sign_intent(spec: IntentSpec, priv: int, chain_id: Optional[int] = None) -> dict:
    """Sign a spec with a local key. Returns the envelope fields for the intent JSON."""
    cid = chain_id if chain_id is not None else env_chain_id()
    digest = intent_digest(spec, cid)
    recid, r, s = ecdsa_sign(digest, priv)
    return {
        "signature": signature_to_hex(recid, r, s),
        "signer": privkey_to_address(priv),
        "domain": {"name": DOMAIN_NAME, "version": DOMAIN_VERSION, "chainId": cid},
    }


def recover_intent_signer(
    spec: IntentSpec, signature: str, chain_id: Optional[int] = None
) -> str:
    """Recover the address that signed this spec's EIP-712 digest."""
    recid, r, s = parse_signature_hex(signature)
    digest = intent_digest(spec, chain_id)
    return pubkey_to_address(ecdsa_recover(digest, recid, r, s))


class Eip712Verifier:
    """Real EIP-712 verification behind the EIP712Verifier protocol.

    - Signed intent: rebuild the digest from the spec, ecrecover, and require the
      recovered address to equal the declared signer (case-insensitive). Any
      tampering with the spec content changes the digest and fails recovery.
    - Unsigned intent: rejected when require_signature=True; otherwise accepted
      and reported as unverified (the validation record carries auth.verified =
      false, so downstream consumers can tell attested-authorization apart from
      asserted-authorization).
    """

    scheme = "eip712"

    def __init__(self, chain_id: Optional[int] = None, require_signature: bool = False) -> None:
        self.chain_id = chain_id if chain_id is not None else env_chain_id()
        self.require_signature = require_signature

    def verify(
        self, spec: IntentSpec, signature: Optional[str], signer: Optional[str]
    ) -> bool:
        if not signature or not signer:
            return not self.require_signature
        try:
            recovered = recover_intent_signer(spec, signature, self.chain_id)
        except (ValueError, TypeError):
            return False
        return recovered.lower() == signer.lower()


# ---------------------------------------------------------------------------
# CLI: sign an intent file with a local key (for fixtures / demos / tests)
#   python -m eiv.eip712 sign --intent path.json --key 0x... [--chain-id N]
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    from eiv.schema import build_intent_spec, split_envelope

    parser = argparse.ArgumentParser(description="EIV EIP-712 intent tools")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_sign = sub.add_parser("sign", help="sign an intent JSON file in place")
    p_sign.add_argument("--intent", required=True)
    p_sign.add_argument("--key", required=True, help="hex private key (test keys only)")
    p_sign.add_argument("--chain-id", type=int, default=None)
    args = parser.parse_args()

    with open(args.intent, encoding="utf-8") as f:
        obj = json.load(f)
    spec_dict, _ = split_envelope(obj)
    spec = build_intent_spec(spec_dict)
    priv = int(args.key, 16)
    envelope = sign_intent(spec, priv, args.chain_id)
    obj.update(envelope)
    with open(args.intent, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
        f.write("\n")
    print(f"signed {args.intent}")
    print(f"  signer : {envelope['signer']}")
    print(f"  digest : {intent_digest_hex(spec, args.chain_id)}")
