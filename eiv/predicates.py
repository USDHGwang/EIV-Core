"""
EIV — predicate engine v0 (the deterministic validation core)

Validates whether an agent's on-chain execution (ExecutionTrace) complies with
its signature-authorized intent (IntentSpec).

Scope: L2 Intent-Spec Compliance — checks "did it follow the signed
authorization", not the L3 "did it understand the user's true intent".
Output severities:
  FAIL        — violates a field stated in the signed spec (objective, reproducible)
  WARN-SAFETY — risky but not prohibited by the spec
  WARN-SPEC   — the spec itself is underspecified (a spec-quality issue, not an
                execution anomaly)

This is the ground-truth layer. An LLM may investigate / orchestrate / explain on
the outer loop, but any FAIL must be reducible to the deterministic result here
(grounding guard). The model is replaceable; this layer is not.

MVP scope: A(Target) / C(AuthExpansion) / D(Amount) / F(Residual); B/E included.
v0 uses max_amount_in as a proxy threshold for C ("required allowance"); to be
refined with empirical AIP rules.
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

UNLIMITED = 2**256 - 1


class Severity(Enum):
    FAIL = "FAIL"
    WARN_SAFETY = "WARN-SAFETY"
    WARN_SPEC = "WARN-SPEC"


SPEC_VERSION = "1.0"


@dataclass
class IntentSpec:
    allowed_targets: set        # contracts that may be called (incl. router)
    allowed_spenders: set       # addresses that may be approved
    token_in: str
    token_out: str
    max_amount_in: int
    min_amount_out: int
    recipient: str              # where output must go
    deadline: int               # unix ts
    require_zero_residual: bool = True   # allowance must be zero after execution
    bounded_approval: bool = True        # approval must not exceed what the task needs
    max_slippage_bps: int | None = None  # unset -> WARN-SPEC
    spec_version: str = SPEC_VERSION


@dataclass
class Approval:
    spender: str
    amount: int


@dataclass
class Transfer:
    token: str
    to: str
    amount: int


@dataclass
class ExecutionTrace:
    calls_to: list           # every contract 'to' touched during execution
    approvals: list          # approvals emitted during execution
    transfers_out: list      # outgoing transfers
    amount_in: int
    amount_out: int
    block_ts: int
    residual_allowances: dict  # spender -> residual allowance after execution


@dataclass
class Violation:
    category: str
    severity: Severity
    detail: str


def validate(spec: IntentSpec, trace: ExecutionTrace) -> dict:
    v: list = []

    # A — Target: every contract touched must be in the authorized set
    for to in trace.calls_to:
        if to not in spec.allowed_targets:
            v.append(Violation("A:Target", Severity.FAIL, f"call to unauthorized target {to}"))

    # C — Authorization Expansion: approve spender and amount
    for ap in trace.approvals:
        if ap.spender not in spec.allowed_spenders:
            v.append(Violation("C:AuthExpansion", Severity.FAIL,
                               f"approve to unauthorized spender {ap.spender}"))
        elif ap.amount > spec.max_amount_in:
            if spec.bounded_approval:
                v.append(Violation("C:AuthExpansion", Severity.FAIL,
                                   f"approve amount {ap.amount} exceeds required {spec.max_amount_in} ({ap.spender})"))
            else:
                v.append(Violation("C:AuthExpansion", Severity.WARN_SAFETY,
                                   f"unbounded/excessive approve to authorized spender {ap.spender}"))

    # D — Amount (incl. slippage)
    if trace.amount_in > spec.max_amount_in:
        v.append(Violation("D:Amount", Severity.FAIL,
                           f"amountIn {trace.amount_in} > maxAmountIn {spec.max_amount_in}"))
    if trace.amount_out < spec.min_amount_out:
        v.append(Violation("D:Amount", Severity.FAIL,
                           f"amountOut {trace.amount_out} < minAmountOut {spec.min_amount_out}"))
    if spec.max_slippage_bps is None:
        v.append(Violation("G:SpecQuality", Severity.WARN_SPEC, "spec does not define maxSlippageBps"))

    # F — Residual: allowance left after execution
    for spender, remaining in trace.residual_allowances.items():
        if remaining > 0:
            if spec.require_zero_residual:
                v.append(Violation("F:Residual", Severity.FAIL,
                                   f"residual allowance {remaining} left to {spender} after execution"))
            else:
                v.append(Violation("F:Residual", Severity.WARN_SAFETY,
                                   f"residual allowance {remaining} to {spender} (spec does not require zeroing)"))

    # B — Recipient: where output goes
    for t in trace.transfers_out:
        if t.token == spec.token_out and t.to != spec.recipient:
            v.append(Violation("B:Recipient", Severity.FAIL,
                               f"output sent to {t.to}, not the authorized recipient {spec.recipient}"))

    # E — Deadline
    if trace.block_ts > spec.deadline:
        v.append(Violation("E:Deadline", Severity.FAIL,
                           f"executed at {trace.block_ts}, past deadline {spec.deadline}"))

    verdict = "FAIL" if any(x.severity == Severity.FAIL for x in v) else "PASS"
    return {
        "verdict": verdict,
        "violations": [
            {"category": x.category, "severity": x.severity.value, "detail": x.detail}
            for x in v
        ],
    }


# ---------------------------------------------------------------------------
# Demo: three mock scenarios showing the engine's verdicts
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json

    ROUTER = "0xRouter"
    USER = "0xUser"
    USDC, WETH = "USDC", "WETH"

    # A signed authorization: "swap at most 100 USDC -> WETH, only via ROUTER, output back to USER"
    spec = IntentSpec(
        allowed_targets={ROUTER},
        allowed_spenders={ROUTER},
        token_in=USDC, token_out=WETH,
        max_amount_in=100, min_amount_out=90,
        recipient=USER, deadline=1_000,
        require_zero_residual=True, bounded_approval=True,
        max_slippage_bps=50,
    )

    scenarios = {
        "1) clean execution": ExecutionTrace(
            calls_to=[ROUTER],
            approvals=[Approval(ROUTER, 100)],
            transfers_out=[Transfer(WETH, USER, 95)],
            amount_in=100, amount_out=95, block_ts=900,
            residual_allowances={ROUTER: 0},
        ),
        "2) leftover residual allowance (F)": ExecutionTrace(
            calls_to=[ROUTER],
            approvals=[Approval(ROUTER, UNLIMITED)],
            transfers_out=[Transfer(WETH, USER, 95)],
            amount_in=100, amount_out=95, block_ts=900,
            residual_allowances={ROUTER: UNLIMITED - 100},
        ),
        "3) unauthorized target + excessive approve (A+C)": ExecutionTrace(
            calls_to=["0xEvil"],
            approvals=[Approval("0xEvil", 100)],
            transfers_out=[Transfer(WETH, "0xAttacker", 95)],
            amount_in=100, amount_out=95, block_ts=900,
            residual_allowances={"0xEvil": 0},
        ),
    }

    for name, trace in scenarios.items():
        result = validate(spec, trace)
        print(f"\n=== {name} -> {result['verdict']} ===")
        for viol in result["violations"]:
            print(f"  [{viol['severity']}] {viol['category']}: {viol['detail']}")
