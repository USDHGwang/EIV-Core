"""Regenerate the GATE live-demo paste set (see gate-live-demo.md).

Builds a signed treasury-mandate intent + a compliant approval and an attacker
drain, runs each through EIV GATE, and prints the JSON to paste into the
Dashboard GATE tab. Run from anywhere: `python docs/demo-run/gen_gate_demo.py`.
"""

import json
import os
import sys

# repo root = .../docs/demo-run/gen_gate_demo.py -> up three levels
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)

from eiv.eip712 import sign_intent
from eiv.schema import build_intent_spec
from eiv.service import ValidatorService

KEY = 0xAC0974BEC39A17E36BA4A6B4D238FF944BACB478CBED5EFCAE784D7BF4F2FF80
USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
WETH = "0x4200000000000000000000000000000000000006"
ROUTER = "0x2626664c2603336e57b271c5c0b26f421741e481"
USER = "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266"
ATTACKER = "0x1111111111111111111111111111111111111111"

spec = {
    "allowed_targets": [ROUTER, USDC], "allowed_spenders": [ROUTER],
    "token_in": USDC, "token_out": WETH, "max_amount_in": "100000000",
    "min_amount_out": "20000000000000000", "recipient": USER,
    "deadline": 4102444800, "require_zero_residual": True,
    "bounded_approval": True, "max_slippage_bps": 50,
}
env = sign_intent(build_intent_spec(spec), KEY)
intent = {"spec": spec, **env}


def approve(spender, amt):
    return "0x095ea7b3" + spender[2:].rjust(64, "0") + hex(amt)[2:].rjust(64, "0")


def transfer(to, amt):
    return "0xa9059cbb" + to[2:].rjust(64, "0") + hex(amt)[2:].rjust(64, "0")


good = {"to": USDC, "data": approve(ROUTER, 50_000_000), "value": "0x0"}
drain = {"to": WETH, "data": transfer(ATTACKER, 20_000_000_000_000_000), "value": "0x0"}

svc = ValidatorService()
g = svc.gate(intent, good)
d = svc.gate(intent, drain)
print("=== INTENT (paste into GATE intent box) ===")
print(json.dumps(intent))
print("\n=== GOOD proposed_tx -> " + g["decision"] + " ===")
print(json.dumps(good))
cats = ",".join(v["category"] for v in d["result"]["violations"] if v["severity"] == "FAIL")
print("\n=== DRAIN proposed_tx -> " + d["decision"] + "  [" + cats + "] ===")
print(json.dumps(drain))
