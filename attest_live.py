"""One-shot: validate the bundled signed intent and attest to the live
Sepolia ValidationRegistry. MockChainAdapter supplies the execution trace;
the attestation sink is the real OnChainAttestationSink.

Usage:  python attest_live.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from eiv.attestation import OnChainAttestationSink
from eiv.chain_adapter import MockChainAdapter
from eiv.intent_source import IntentSource
from eiv.service import ValidatorService


def load_env() -> None:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_env()
    sink = OnChainAttestationSink(
        rpc_url=os.environ["RPC_URL"],
        registry_address=os.environ["EIV_VALIDATION_REGISTRY_ADDRESS"],
        private_key=os.environ["ATTESTER_PRIVATE_KEY"],
        chain_id=int(os.environ.get("CHAIN_ID", "11155111")),
        dry_run=args.dry_run,
    )
    service = ValidatorService(
        source=IntentSource(), adapter=MockChainAdapter(), sink=sink,
    )

    intent_path = os.path.join("eiv", "fixtures", "intents", "intent_clean.json")
    with open(intent_path, encoding="utf-8") as f:
        intent = json.load(f)

    record = service.run(intent, "tx_clean")
    print("verdict      :", record["result"]["verdict"])
    print("intent_hash  :", record["intent_hash"])
    print("auth.verified:", record["auth"]["verified"])
    print("attestation  :", record["attestation"]["attestation_ref"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
