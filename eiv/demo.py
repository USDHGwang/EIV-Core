"""
EIV — end-to-end demo

Runs one signature-authorized intent (intent_clean.json) against three execution
traces through ValidatorService:

    tx_clean     -> PASS
    tx_residual  -> FAIL (unbounded approve, leaves residual allowance)
    tx_unauth    -> FAIL (calls an unauthorized target, sends output to an attacker)

Returns exit code 1 if any verdict does not match the expectation.

Run: python -m eiv.demo
"""

from __future__ import annotations

import os
import sys

_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

# Windows consoles may default to a non-UTF-8 codepage; force UTF-8 output.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

import json

from eiv.service import ValidatorService
from eiv.store import ValidationStore

_HERE = os.path.dirname(os.path.abspath(__file__))
_INTENT = os.path.join(_HERE, "fixtures", "intents", "intent_clean.json")
_RUNS = os.path.join(_HERE, "runs")

# (display name, tx_ref, expected verdict)
SCENARIOS = [
    ("1) Clean execution", "tx_clean", "PASS"),
    ("2) Residual / unbounded allowance", "tx_residual", "FAIL"),
    ("3) Unauthorized target", "tx_unauth", "FAIL"),
]


def main() -> int:
    with open(_INTENT, encoding="utf-8") as f:
        intent = json.load(f)

    # Default to the reference implementations (IntentSource / MockChainAdapter / StubAttestationSink)
    service = ValidatorService(store=ValidationStore(_RUNS))

    print("=" * 68)
    print("EIV end-to-end demo - one authorization, three executions")
    print("=" * 68)

    all_ok = True
    for name, tx_ref, expected in SCENARIOS:
        print(f"\n### {name}  (tx_ref={tx_ref})")
        record = service.run(intent, tx_ref)
        verdict = record["result"]["verdict"]
        ok = verdict == expected
        all_ok = all_ok and ok

        mark = "OK" if ok else "MISMATCH"
        print(f"  verdict: {verdict}  (expected {expected}) [{mark}]")
        for v in record["result"]["violations"]:
            print(f"    [{v['severity']:11}] {v['category']}: {v['detail']}")
        print(f"  validation_id: {record['validation_id']}")
        print(f"  attestation  : {record['attestation']['attestation_ref']}")

    print("\n" + "=" * 68)
    print(f"Stored in: {_RUNS}")
    if all_ok:
        print("Result: all verdicts as expected (PASS / FAIL / FAIL)")
        return 0
    print("Result: some verdicts did not match")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
