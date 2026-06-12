"""
EIV — IntentSource and the EIP-712 signature-verification interface

Loads a signature-authorized intent (IntentSpec) from JSON and verifies its
signature.

Verification is encapsulated behind the EIP712Verifier protocol. The default
implementation is eiv.eip712.Eip712Verifier — real EIP-712 verification
(rebuild the typed-data digest from the spec, ecrecover, compare the recovered
address to the declared signer) implemented entirely with the standard
library. StubEIP712Verifier (accept-everything) is kept for tests that need to
isolate other layers.

Policy for unsigned intents: by default they are accepted but marked
auth.verified = false in the validation record, so consumers can distinguish
a cryptographically attested authorization from an asserted one. Set
EIV_REQUIRE_SIGNATURE=1 (or require_signature=True) to reject them outright.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional, Protocol

from eiv import eip712
from eiv.predicates import IntentSpec
from eiv.schema import (
    build_intent_spec,
    compute_intent_hash,
    spec_to_canonical,
    split_envelope,
)


class IntentAuthError(ValueError):
    """Signature verification failed (authorization invalid)."""


@dataclass
class LoadedIntent:
    """An intent after loading and signature verification."""

    spec: IntentSpec
    intent_hash: str
    signer: Optional[str]
    signature: Optional[str]
    canonical: dict  # canonical spec dict, returned in the record
    auth: dict = field(default_factory=dict)  # {scheme, verified, signer, digest, ...}


class EIP712Verifier(Protocol):
    """Signature-verification interface. verify() returns True when the intent is
    signed by signer and untampered."""

    def verify(
        self, spec: IntentSpec, signature: Optional[str], signer: Optional[str]
    ) -> bool: ...


class StubEIP712Verifier:
    """Accept-everything verifier, kept for tests that isolate other layers."""

    scheme = "stub"

    def verify(
        self, spec: IntentSpec, signature: Optional[str], signer: Optional[str]
    ) -> bool:
        return True


def _env_require_signature() -> bool:
    return os.environ.get("EIV_REQUIRE_SIGNATURE", "").strip() in ("1", "true", "yes")


class IntentSource:
    """Loads and verifies an intent from JSON, producing a LoadedIntent.

    intent_hash is the EIP-712 typed-data digest of the spec (the same value an
    authorizer signs), so the attestation's request_hash is bound to the signed
    authorization itself. The sha256 content hash remains available in
    auth.content_sha256 for plain content addressing.
    """

    def __init__(self, verifier: Optional[EIP712Verifier] = None) -> None:
        if verifier is None:
            verifier = eip712.Eip712Verifier(require_signature=_env_require_signature())
        self.verifier: EIP712Verifier = verifier

    def load(self, intent: dict | str) -> LoadedIntent:
        obj = intent if isinstance(intent, dict) else json.loads(intent)
        spec_dict, env = split_envelope(obj)
        spec = build_intent_spec(spec_dict)
        signature = env.get("signature")
        signer = env.get("signer")
        if not self.verifier.verify(spec, signature, signer):
            raise IntentAuthError("EIP-712 signature verification failed (intent not authorized)")

        chain_id = getattr(self.verifier, "chain_id", None)
        digest = eip712.intent_digest_hex(spec, chain_id)
        signed = bool(signature and signer)
        scheme = getattr(self.verifier, "scheme", "unknown")
        auth = {
            "scheme": scheme,
            # Only a cryptographic verifier can attest a signature; the stub
            # accepting input does not make the intent "verified".
            "verified": signed and scheme == "eip712",
            "signer": signer,
            "chain_id": chain_id if chain_id is not None else eip712.env_chain_id(),
            "digest": digest,
            "content_sha256": compute_intent_hash(spec),
        }
        return LoadedIntent(
            spec=spec,
            intent_hash=digest,
            signer=signer,
            signature=signature,
            canonical=spec_to_canonical(spec),
            auth=auth,
        )

    def load_file(self, path: str) -> LoadedIntent:
        with open(path, encoding="utf-8") as f:
            return self.load(json.load(f))
