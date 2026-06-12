"""
EIV — ValidatorService (orchestration layer)

run(intent, tx_ref) chains the pipeline:

    IntentSource (verify signature) -> ChainAdapter (fetch execution trace)
        -> validate (validation engine) -> AttestationSink (ERC-8004)
        -> ValidationStore (persist)

Returns a validation record (which embeds the result schema).
All external dependencies are injected via the constructor and default to the
reference implementations; swapping in production implementations requires no
change to this layer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from eiv.attestation import (
    AttestationSink,
    StubAttestationSink,
    build_validation_response,
)
from eiv.chain_adapter import ChainAdapter, MockChainAdapter, decode_proposed_trace
from eiv.intent_source import IntentSource
from eiv.predicates import validate
from eiv.store import ValidationStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def summarize(record: dict) -> dict:
    """Compact view for listings (GET /validations)."""
    return {
        "validation_id": record["validation_id"],
        "tx_ref": record["tx_ref"],
        "verdict": record["result"]["verdict"],
        "n_violations": len(record["result"]["violations"]),
        "verified": record.get("auth", {}).get("verified", False),
        "created_at": record["created_at"],
    }


class ValidatorService:
    def __init__(
        self,
        source: Optional[IntentSource] = None,
        adapter: Optional[ChainAdapter] = None,
        sink: Optional[AttestationSink] = None,
        store: Optional[ValidationStore] = None,
    ) -> None:
        self.source = source or IntentSource()
        self.adapter = adapter or MockChainAdapter()
        self.sink = sink or StubAttestationSink()
        self.store = store if store is not None else ValidationStore()

    def run(self, intent: dict | str, tx_ref: str) -> dict:
        """Run one validation end to end and return the full record."""
        loaded = self.source.load(intent)
        # The spec gives the adapter token-pair context (amount_in / amount_out
        # are defined relative to the authorized tokens); fixture adapters ignore it.
        trace = self.adapter.get_execution_trace(tx_ref, loaded.spec)

        # Deterministic validation engine (rules live in predicates.py)
        result = validate(loaded.spec, trace)  # result schema

        attestation_ref = self.sink.attest(loaded.intent_hash, result)
        attestation = {
            "attestation_ref": attestation_ref,
            **build_validation_response(loaded.intent_hash, result),
        }

        record = {
            "validation_id": "val_" + uuid4().hex[:12],
            "tx_ref": tx_ref,
            "intent_hash": loaded.intent_hash,
            "signer": loaded.signer,
            "auth": loaded.auth,  # signature-verification outcome (scheme/verified/digest)
            "intent": loaded.canonical,  # authorized intent
            "result": result,  # result schema (kept verbatim)
            "attestation": attestation,
            "created_at": _now_iso(),
        }
        self.store.put(record)
        return record

    def gate(self, intent: dict | str, proposed_tx: dict) -> dict:
        """GATE mode: pre-execution validation via calldata decoding.

        Returns a decision record with approve/reject + the result schema.
        D:Amount output and F:Residual are optimistic (partial check).
        """
        loaded = self.source.load(intent)
        trace = decode_proposed_trace(proposed_tx, loaded.spec)
        result = validate(loaded.spec, trace)

        unchecked = [
            "D:Amount (output amount unknown pre-execution)",
            "F:Residual (allowance state unknown pre-execution)",
        ]

        decision = "REJECT" if result["verdict"] == "FAIL" else "APPROVE"
        return {
            "decision": decision,
            "mode": "GATE",
            "partial": True,
            "unchecked": unchecked,
            "result": result,
            "signer": loaded.signer,
            "auth": loaded.auth,
        }

    def get(self, validation_id: str) -> Optional[dict]:
        return self.store.get(validation_id)

    def list(self) -> list[dict]:
        return [summarize(r) for r in self.store.list()]
