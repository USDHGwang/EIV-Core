# EIV Core — Execution-Integrity Validator

**English** | [繁體中文](README.zh-TW.md) | [简体中文](README.zh-CN.md)

AI agents now move real money on-chain, and they get drained. In May 2026 an AI
agent wallet lost ~$175K to a single prompt-injection tweet combined with an NFT
that silently escalated its permissions. The root cause is a category error:

> **a model generating an action is not the same as that action being authorized.**

EIV is an **independent source of truth** about whether an agent's on-chain
execution stayed within the authorization its user actually signed. Given the
signed intent (IntentSpec) and what the agent did on-chain, EIV produces a
deterministic verdict on whether the execution complied.

**EIV does not ask you to trust EIV.** The verdict is a deterministic function of
public inputs — the signed authorization and the on-chain execution — so anyone
can reproduce the same verdict independently. Trust comes from reproducibility,
the way it does for a credit rating or an audit, not from EIV's authority.

Scope: **L2 — authorization compliance** (did the execution obey the signed
authorization), not L3 (did it understand the user's true intent).

## What makes it different

EIV verifies the **outcome against your invariants** — did your funds or
permissions move outside what you signed — regardless of which contract was involved.

- **vs allowlist enforcement** (e.g. Cobo): an allowlist only protects you on
  contracts someone has already vetted, and no team keeps up with the long tail.
  EIV protects you on a contract deployed five minutes ago, because it checks what
  happened to *your* assets, not whether the counterparty is on a list.
- **vs in-wallet enforcement** (Coinbase / MetaMask): a wallet vouching for its
  own agents is not neutral. EIV is an independent verifier whose verdict is
  re-checkable by anyone.
- **vs LLM guardrails** (NeMo / LLM Guard): those screen the *prompt*
  probabilistically and can be bypassed — the May 2026 attack slipped past the
  agent's own safety layer. EIV checks the *on-chain outcome* deterministically,
  independent of the prompt or the agent's reasoning.

The same deterministic check can run **before** execution (simulate the proposed
transaction, then block it) or **after** (attest it, building the agent's
verifiable track record). Verdicts can be attested through **ERC-8004**, making
the track record portable across ecosystems.

## Zero dependencies — including the cryptography

EIV's trust model is "re-verify, don't trust", and that extends to the supply
chain: the whole validator — keccak-256, secp256k1 ECDSA (RFC 6979 signing and
ecrecover), EIP-712 typed-data hashing, RLP, EIP-1559 transaction signing,
JSON-RPC, HTTP server, and the web console — runs on a stock Python standard
library. Anyone with Python can re-run a verdict; there is no dependency tree to
audit. The primitives are checked against published test vectors on every
`python -m eiv.selftest` run.

## Where this is heading

Today EIV outputs a verdict per execution. As agents take on more on-chain
authority, those verdicts aggregate into a portable, independently-verifiable
reputation — an independent rating layer for agent execution, distinct from the
wallet or the agent itself. That is the long-term direction; the current release
is the deterministic verification core.

→ Full reasoning, the A–G check basis, the EIV-vs-AIP boundary, and honest limits:
**[docs/POSITIONING.md](docs/POSITIONING.md)**.

## Architecture

```
                      ┌─────────────────────────────────────────┐
                      │  eiv-core (this repo, stdlib only)      │
   signed intent ───▶ │  Eip712Verifier   (ecrecover == signer) │
                      │        │                                │
   tx hash ────────▶  │  RpcChainAdapter  (receipt + logs +     │
                      │        │           allowance reads)     │
                      │        ▼                                │
                      │  predicates.py    (deterministic A–G)   │
                      │        │                                │    ERC-8004
                      │        ▼                                │  validation
                      │  OnChainAttestationSink ────────────────┼──────────────▶ contracts/
                      │        │                                │   response     EIVValidationRegistry
                      │        ▼                                │                (live on Sepolia)
                      │  ValidationStore + HTTP API + console   │
                      └─────────────────────────────────────────┘
                                       │ HTTP / web
                                       ▼
                          dashboards, agents, anyone re-verifying
```

- **eiv-core** (this project): the off-chain validation service — deterministic
  engine, EIP-712 verification, live trace reconstruction, attestation signing,
  HTTP API, and the embedded console.
- **contracts/** (in this repo): a minimal ERC-8004 ValidationRegistry in
  Solidity 0.8.19, compiled with standalone solc-js (no Hardhat) and deployed
  by `contracts/deploy_registry.py` using eiv-core's own stdlib signing stack.
  Deployed on Sepolia; deployment record in `contracts/DEPLOYMENTS.md`. After
  deployment, set its address in `EIV_VALIDATION_REGISTRY_ADDRESS` (see
  `.env.example`).

## The console

`python -m eiv.api` serves a zero-dependency web console at `/`:
bundled scenarios (a clean swap, a dangling-allowance drain, an unauthorized
target, and a replay of the May 2026 Grok/Bankr incident), a live validation
feed, and a full drill-down per record — signature verification outcome,
violations by category, the canonical signed intent, and the ERC-8004
attestation payload. It runs offline; no CDN, fonts, or build step.

One scenario validates the **real drain transaction** ([0x6fc7…739a on Base
mainnet](https://basescan.org/tx/0x6fc7eb7da9379383efda4253e4f599bbc3a99afed0468eabfe18484ec525739a),
3,000,000,000 DRB ≈ $175K to the attacker). Start the service with
`RPC_URL=https://mainnet.base.org` and EIV fetches the execution from the chain
and flags `B:Recipient` on the actual transaction — not a mock of it.

## Result schema (API contract)

`validate()` and the HTTP API return a fixed result schema — the public contract
for downstream consumers (dashboard, attestation):

```jsonc
{
  "verdict": "PASS" | "FAIL",
  "violations": [
    { "category": "A:Target",
      "severity": "FAIL" | "WARN-SAFETY" | "WARN-SPEC",
      "detail":   "human-readable description" }
  ]
}
```

- `verdict` depends only on whether any `FAIL`-severity violation exists;
  `WARN-*` does not affect it.
- Severity: `FAIL` (violates a field stated in the signed spec),
  `WARN-SAFETY` (risky but not prohibited by the spec),
  `WARN-SPEC` (the spec itself is underspecified).
- Categories cover target, recipient, authorization expansion, amount/slippage,
  deadline, residual allowance, etc.
- Amounts are strings in JSON (uint256 exceeds the JavaScript Number safe range).

## HTTP API

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | The EIV console (embedded web UI) |
| `POST` | `/validate` | Submit `{intent, tx_ref}`; returns `{validation_id, verdict, violations}` |
| `POST` | `/gate` | **Pre-execution check**: submit `{intent, proposed_tx}`; decodes the calldata (ERC-20 transfer/approve/transferFrom + native ETH) and returns `{decision: APPROVE\|REJECT, partial, unchecked, result}` before anything touches the chain |
| `GET` | `/reputation/{addr}` | Trust profile for an agent address: pass-rate trust score (0–100), risk level, violations by category, recent verdicts |
| `GET` | `/validations` | List summaries of all validation records |
| `GET` | `/validations/{id}` | Full validation record (incl. the result schema) |
| `GET` | `/scenarios` | Bundled demo scenarios with their signed intents inlined |
| `GET` | `/status` | Active component implementations + verdict counters |
| `GET` | `/healthz` | Health check |

The same verdict serves three uses: **GATE** (block a proposed transaction
before execution), **RECORD** (validate and attest after execution), and
**reputation** (aggregate verdicts into a portable trust profile). GATE is
transparent about its limits: output amount and residual allowance are unknown
pre-execution, so the response lists them under `unchecked`.

Error codes: `400` malformed request · `401` signature verification failed ·
`404` unknown tx_ref / id · `500` internal error.

## Quick start

Requires Python 3.9+ (developed on 3.10); no third-party dependencies.

```bash
# End-to-end demo: one authorization, three executions -> PASS / FAIL / FAIL
python -m eiv.demo

# Automated tests: verdicts, HTTP behavior, crypto vectors, RPC decoding,
# attestation encoding, console endpoints
python -m eiv.selftest

# Start the HTTP API + console (default 127.0.0.1:8000)
python -m eiv.api

# Submit a validation request (while the API is running)
curl -X POST http://127.0.0.1:8000/validate \
  -H "Content-Type: application/json" \
  -d '{"intent": <contents of eiv/fixtures/intents/intent_clean.json>, "tx_ref": "tx_clean"}'

# Sign an intent with a local key (test keys only)
python -m eiv.eip712 sign --intent path/to/intent.json --key 0x...
```

Optional install: `pip install -e .` (MCP tool: `pip install -e ".[mcp]"`).

## Python SDK

For agent integration, `eiv.sdk` provides three clients with the same core
methods (`validate` / `gate` / `reputation`):

```python
from eiv.sdk import EivEmbed, EivClient, AsyncEivClient

# In-process — no server needed
eiv = EivEmbed()                          # MockChainAdapter (fixtures)
eiv = EivEmbed(rpc_url="https://...")     # live-chain validation

# Pre-execution gate: should this proposed tx be allowed?
decision = eiv.gate(intent, proposed_tx)  # {"decision": "APPROVE" | "REJECT", ...}

# Post-execution validation
result = eiv.validate(intent, tx_hash)    # {"validation_id", "verdict", "violations"}

# Agent trust profile
profile = eiv.reputation("0xagent...")    # {"trust_score", "risk_level", ...}

# HTTP client against a running `python -m eiv.api`
client = EivClient("http://127.0.0.1:8000")

# Async wrapper around either client
aclient = AsyncEivClient(client)
result = await aclient.validate(intent, tx_hash)

# Post-validation hooks (alerting, logging, circuit breakers)
eiv.on_validation(lambda r: alert(r) if r["verdict"] == "FAIL" else None)
```

## GLM-5.1 agent layer — long-horizon execution on deterministic rails

`eiv.glm` and `eiv.agent_loop` add an autonomous agent that runs **on top of**
the validator without ever entering the trust path. GLM-5.1 drives a
multi-step loop; EIV gates every action it proposes.

- **`eiv/glm.py`** — `GlmClient` (OpenAI-compatible, stdlib HTTP, retry/backoff
  on 429/5xx), `spec_from_prompt` (plain-language authorization → a validated
  `IntentSpec`, with repair rounds), `propose_transaction` (GLM acts as the
  agent).
- **`eiv/agent_loop.py`** — `AgentRun`: GLM-5.1 decomposes the task into a plan,
  then acts through a JSON action protocol (`plan` / `propose_tx` /
  `reputation` / `finish`). Every `propose_tx` passes through
  `ValidatorService.gate()`; a `REJECT` feeds the deterministic violations back
  so the model can self-correct. The full run — plan, tool calls, verdicts,
  corrections — is written to a JSONL audit log. `max_steps` bounds autonomy.
- **`glm_sandbox.py`** — the end-to-end demo (below).

**Where GLM-5.1 is called:** only in `GlmClient.chat()` (spec extraction and the
agent loop). Configure any OpenAI-compatible provider via `.env`
(`GLM_API_KEY` / `GLM_BASE_URL` / `GLM_MODEL`); the model id is `z-ai/glm-5.1`
(`glm-5.1` on the official Z.AI endpoint).

**Safety boundary — by construction the model cannot move funds:**

- The agent can only *propose* a transaction. The single path to execution is a
  deterministic GATE `APPROVE`. Verdicts come from `eiv.predicates` and depend
  on no model — core modules do not import `glm`/`agent_loop`.
- A swap is modeled as one router call (the router pulls the input token via
  Permit2), so the token contract is never an allowed target. A drain — a
  direct token transfer to an attacker — is therefore a call to an
  unauthorized target and is rejected (`A:Target`) **even if the model is fully
  compromised.**
- **Failure handling:** the loop survives malformed model output (recorded as a
  protocol error, retried), transient provider failures (retry with backoff;
  on exhaustion the run ends `status="error"` with the log still closed), and a
  step ceiling (`status="exhausted"`).
- **Human intervention:** GATE returns a decision, it does not broadcast.
  Execution and on-chain attestation remain explicit, human-gated steps
  (`EIV_ATTEST_DRY_RUN=1` rehearses without broadcasting).

Run the demo (`python glm_sandbox.py`) — three acts on one signed authorization:

| Act | What happens | Outcome |
|---|---|---|
| **GREEN** | a compliant task; GLM-5.1 plans and proposes a single router swap | GATE `APPROVE` → delivered |
| **RESIST** | the same task with a prompt injection ordering a transfer to an attacker | GLM-5.1 refuses the injection on its own (defense in depth) |
| **BACKSTOP** | a compromised agent submits the drain directly, bypassing the model | GATE `REJECT` (`A:Target`) — the guarantee that holds even when the model is owned |

## Implementation status

EIV isolates external dependencies behind replaceable interfaces. As of v0.3.0
all production implementations are real and covered by the selftest (174
checks); the reference implementations remain available for isolation testing
and offline demos.

v0.3.0 additions: token address pinning (symbol-based specs are rejected on
live adapters), native ETH transfer detection (EIP-7528 sentinel), RPC retry
with fallback URL, GATE pre-execution mode, a formal JSON Schema for
IntentSpec v1.0 ([docs/intent-spec-v1.schema.json](docs/intent-spec-v1.schema.json)),
an SQLite-backed store (`EIV_STORE_BACKEND=sqlite`), the reputation API, and
the Python SDK.

| Interface | Production implementation (default when configured) | Reference |
|---|---|---|
| `EIP712Verifier` | `Eip712Verifier` — rebuilds the EIP-712 typed-data digest from the spec, ecrecover, compares the recovered address to the declared signer. Tampered content or a wrong signer is rejected (HTTP 401). **Active by default.** | `StubEIP712Verifier` |
| `ChainAdapter` | `RpcChainAdapter` — reconstructs the trace from a live node over JSON-RPC: receipt, ERC-20 Transfer/Approval logs, block timestamp, and post-execution allowance reads via `eth_call`. Enabled with `RPC_URL`. | `MockChainAdapter` (fixtures) |
| `AttestationSink` | `OnChainAttestationSink` — ABI-encodes `validationResponse`, signs an EIP-1559 transaction, and broadcasts it to the ERC-8004 registry. Enabled with `EIV_VALIDATION_REGISTRY_ADDRESS` + `ATTESTER_PRIVATE_KEY`; `EIV_ATTEST_DRY_RUN=1` signs without broadcasting. | `StubAttestationSink` |

Swapping implementations requires no change to the orchestration service, API,
or validation engine; composition is environment-driven (see `.env.example`).

Unsigned intents are accepted by default but the record carries
`auth.verified = false`, so consumers can always distinguish a cryptographically
attested authorization from an asserted one. `EIV_REQUIRE_SIGNATURE=1` rejects
them outright.

### ABI alignment with the registry contract

Contract interface:
`validationResponse(bytes32 requestHash, bytes response, string responseURI, bytes32 responseHash, string tag)`

| Contract field | Implementation |
|---|---|
| `requestHash` | the intent's EIP-712 typed-data digest (what the authorizer signed) |
| `response` | single byte score: `100` (PASS) / `0` (FAIL) |
| `responseURI` | `EIV_RESPONSE_URI_BASE` + requestHash (empty when unset) |
| `responseHash` | keccak-256 of the canonical result JSON (commits to the exact violation set) |
| `tag` | `EIV.L2.{verdict}` (e.g. `EIV.L2.PASS`) — matches the contract |

### Live on Sepolia

This path is not theoretical — it has run end-to-end on Sepolia:

| | |
|---|---|
| `EIVValidationRegistry` (ERC-8004 ValidationRegistry) | [`0x6719c69829740232f652b4b6bad8e6850922a2fb`](https://sepolia.etherscan.io/address/0x6719c69829740232f652b4b6bad8e6850922a2fb) |
| First real attestation (`OnChainAttestationSink`) | [`0xbc50b963d8f9c9f5f34ba7764f510e0f6cddf4d67a4b927584170bdac40ec6f0`](https://sepolia.etherscan.io/tx/0xbc50b963d8f9c9f5f34ba7764f510e0f6cddf4d67a4b927584170bdac40ec6f0) (block 11041392, 145,626 gas, `ValidationResponse` event emitted) |

The attested `requestHash` is the intent's EIP-712 digest
`0xe218a34c8204b392b0455de31668d208aef8549a039af6076654fd033ac76748`; on-chain
`hasValidation(requestHash)` returns true, with tag `EIV.L2.PASS`. Both the
contract deployment and the attestation transaction were signed by eiv-core's
zero-dependency stdlib crypto stack (`eiv/eth.py`) — no Hardhat or web3.py in
the loop for the attestation path.

## Project structure

```
eiv-core/
├── eiv/
│   ├── predicates.py       # deterministic validation engine (rule source)
│   ├── schema.py           # JSON <-> dataclass, amount parsing, content hash
│   ├── eth.py              # stdlib crypto: keccak, secp256k1, RLP, ABI, EIP-1559, JSON-RPC
│   ├── eip712.py           # IntentSpec typed-data digest, signing, verification
│   ├── intent_source.py    # IntentSource and the EIP712Verifier interface
│   ├── chain_adapter.py    # MockChainAdapter + RpcChainAdapter (live JSON-RPC)
│   ├── attestation.py      # StubAttestationSink + OnChainAttestationSink (ERC-8004)
│   ├── service.py          # ValidatorService orchestration (run + gate)
│   ├── store.py            # ValidationStore (JSON) + SqliteValidationStore (WAL, indexed)
│   ├── reputation.py       # trust-profile aggregation over validation history
│   ├── sdk.py              # Python SDK: EivClient / EivEmbed / AsyncEivClient + hooks
│   ├── glm.py              # GLM-5.1 client + NL->IntentSpec + agent proposal (demo layer)
│   ├── agent_loop.py       # long-horizon GLM-5.1 loop, every action gated by EIV
│   ├── api.py              # HTTP API + console serving (standard library)
│   ├── static/index.html   # the EIV console (zero-dependency web UI)
│   ├── demo.py             # end-to-end demo
│   ├── selftest.py         # automated tests (incl. published crypto vectors)
│   ├── mcp_tool.py         # MCP tool (optional)
│   └── fixtures/           # signed sample intents, execution traces, scenarios
├── contracts/              # ERC-8004 ValidationRegistry (Solidity) + stdlib deploy tooling
├── docs/                   # design documents
├── pyproject.toml
├── .env.example
└── LICENSE
```

## License

MIT License — see [LICENSE](LICENSE).

## Team

AI × Web3 Agentic Builders Hackathon · Z.AI track.
