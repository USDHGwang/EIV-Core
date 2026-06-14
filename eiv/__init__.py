"""
EIV — Execution-Integrity Validator

Independent, after-the-fact integrity validation of an AI agent's on-chain
transaction: checks whether an execution complies with the agent's
signature-authorized intent (IntentSpec), and attests the verdict on-chain per
ERC-8004. Scoped at L2 (authorization compliance), not L3 (semantic intent).

Public API
----------
1. Deterministic validation engine:
       validate(spec: IntentSpec, trace: ExecutionTrace) -> dict
   Returns a fixed result schema (the downstream contract):
       {
         "verdict": "PASS" | "FAIL",
         "violations": [
           {"category": str, "severity": "FAIL"|"WARN-SAFETY"|"WARN-SPEC", "detail": str},
           ...
         ]
       }
   Validation rules live in predicates.py.

2. dict interface (same rules):
       validate_json(intent: dict, trace: dict) -> same schema

3. Service layer:
       ValidatorService().run(intent, tx_ref) -> validation record (embeds the result above)

External dependency interfaces and their implementations (all standard library,
zero third-party dependencies — including the cryptography, see eiv.eth):
   - EIP712Verifier   <- Eip712Verifier (real EIP-712 typed-data verification:
                         rebuild digest, ecrecover, compare signer; default)
                         StubEIP712Verifier (accept-everything, for isolation tests)
   - ChainAdapter     <- RpcChainAdapter (reconstructs the trace from a live node
                         over JSON-RPC; enabled via RPC_URL)
                         MockChainAdapter (fixture traces; default without RPC_URL)
   - AttestationSink  <- OnChainAttestationSink (signs + broadcasts the ERC-8004
                         validationResponse; enabled via registry/key env vars,
                         EIV_ATTEST_DRY_RUN=1 signs without broadcasting)
                         StubAttestationSink (prints the response; default)
"""

from __future__ import annotations

# Deterministic validation engine (source of validation rules)
from eiv.predicates import (
    Approval,
    ExecutionTrace,
    IntentSpec,
    Severity,
    Transfer,
    Violation,
    validate,
)

# Serialization and convenience helpers
from eiv.schema import (
    IntentParseError,
    TraceParseError,
    compute_intent_hash,
    validate_json,
)

# EIP-712 typed-data hashing / signing / verification (stdlib crypto in eiv.eth)
from eiv.eip712 import (
    Eip712Verifier,
    intent_digest,
    intent_digest_hex,
    recover_intent_signer,
    sign_intent,
)

# External dependency interfaces and implementations
from eiv.attestation import (
    AttestationSink,
    OnChainAttestationSink,
    StubAttestationSink,
    build_validation_response,
)
from eiv.chain_adapter import (
    ChainAdapter,
    FallbackChainAdapter,
    MockChainAdapter,
    RpcChainAdapter,
    TraceNotFound,
)
from eiv.intent_source import (
    EIP712Verifier,
    IntentAuthError,
    IntentSource,
    LoadedIntent,
    StubEIP712Verifier,
)

# Service layer
from eiv.service import ValidatorService, summarize
from eiv.store import ValidationStore

# SDK (agent integration)
from eiv.sdk import AsyncEivClient, EivClient, EivEmbed

__version__ = "0.3.0"

__all__ = [
    # validation engine
    "validate",
    "validate_json",
    "IntentSpec",
    "ExecutionTrace",
    "Approval",
    "Transfer",
    "Violation",
    "Severity",
    # service layer
    "ValidatorService",
    "ValidationStore",
    "summarize",
    # intent source / signature-verification interface
    "IntentSource",
    "LoadedIntent",
    "EIP712Verifier",
    "Eip712Verifier",
    "StubEIP712Verifier",
    "IntentAuthError",
    "sign_intent",
    "intent_digest",
    "intent_digest_hex",
    "recover_intent_signer",
    # chain data interface
    "ChainAdapter",
    "FallbackChainAdapter",
    "MockChainAdapter",
    "RpcChainAdapter",
    "TraceNotFound",
    # attestation interface
    "AttestationSink",
    "StubAttestationSink",
    "OnChainAttestationSink",
    "build_validation_response",
    # schema helpers
    "compute_intent_hash",
    "IntentParseError",
    "TraceParseError",
    # SDK
    "EivClient",
    "EivEmbed",
    "AsyncEivClient",
    "__version__",
]
