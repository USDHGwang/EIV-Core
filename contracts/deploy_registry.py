"""
Deploy EIVValidationRegistry to Sepolia using eiv-core's stdlib crypto stack.

No Hardhat / web3.py needed — signing and RPC come from eiv.eth (the same
code paths the validator's selftest covers with published vectors).

Usage (from the repo root):
    python contracts/deploy_registry.py --check   # preflight only (no broadcast)
    python contracts/deploy_registry.py           # deploy

Compile first (once):
    cd contracts && npm install --no-save solc@0.8.19 && node compile_standalone.js

Reads from the repo-root .env (or environment):
    RPC_URL               Sepolia RPC endpoint
    ATTESTER_PRIVATE_KEY  funded deployer key (NEVER printed, NEVER committed)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from eiv.eth import (  # noqa: E402
    from_hex_quantity,
    http_rpc_transport,
    privkey_to_address,
    sign_eip1559_tx,
)

ARTIFACT = os.path.join(_HERE, "artifacts", "EIVValidationRegistry.json")
CHAIN_ID = 11155111  # Sepolia
DEFAULT_RPC = "https://ethereum-sepolia-rpc.publicnode.com"


def load_env() -> None:
    """Minimal .env loader (repo-root .env), values never echoed."""
    path = os.path.join(_ROOT, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="preflight only, no broadcast")
    args = parser.parse_args()

    load_env()
    rpc_url = os.environ.get("RPC_URL", "").strip() or DEFAULT_RPC
    key_hex = os.environ.get("ATTESTER_PRIVATE_KEY", "").strip()

    rpc = http_rpc_transport(rpc_url)
    chain_id = from_hex_quantity(rpc("eth_chainId", []))
    if chain_id != CHAIN_ID:
        print(f"ERROR: RPC chain id {chain_id} != Sepolia ({CHAIN_ID})")
        return 1
    print(f"rpc        : {rpc_url} (chain {chain_id})")

    if not key_hex:
        print("ERROR: ATTESTER_PRIVATE_KEY not set (put it in .env; it is gitignored)")
        return 1
    priv = int(key_hex, 16)
    addr = privkey_to_address(priv)
    balance = from_hex_quantity(rpc("eth_getBalance", [addr, "latest"]))
    print(f"deployer   : {addr}")
    print(f"balance    : {balance / 1e18:.6f} ETH")

    with open(ARTIFACT, encoding="utf-8") as f:
        bytecode = bytes.fromhex(json.load(f)["bytecode"][2:])
    print(f"bytecode   : {len(bytecode)} bytes")

    gas = from_hex_quantity(rpc("eth_estimateGas", [{"from": addr, "data": "0x" + bytecode.hex()}]))
    block = rpc("eth_getBlockByNumber", ["latest", False])
    base_fee = from_hex_quantity(block["baseFeePerGas"])
    tip = 1_500_000_000  # 1.5 gwei
    # base fee moves at most 12.5% per block; 1.25x covers ~2 full blocks
    max_fee = base_fee * 5 // 4 + tip
    cost = gas * max_fee
    print(f"gas        : {gas} (max cost {cost / 1e18:.6f} ETH)")

    if balance < cost:
        print("ERROR: insufficient balance — fund the deployer at a Sepolia faucet, e.g.")
        print("       https://www.alchemy.com/faucets/ethereum-sepolia")
        return 1
    if args.check:
        print("preflight OK — rerun without --check to deploy")
        return 0

    nonce = from_hex_quantity(rpc("eth_getTransactionCount", [addr, "pending"]))
    raw, tx_hash = sign_eip1559_tx(
        priv,
        chain_id=CHAIN_ID,
        nonce=nonce,
        max_priority_fee=tip,
        max_fee=max_fee,
        gas_limit=gas + 20_000,
        to="",  # contract creation
        data=bytecode,
    )
    sent = rpc("eth_sendRawTransaction", ["0x" + raw.hex()])
    print(f"tx         : {sent}")

    for _ in range(60):
        receipt = rpc("eth_getTransactionReceipt", [sent])
        if receipt:
            status = from_hex_quantity(receipt.get("status", "0x0"))
            contract = receipt.get("contractAddress")
            if status != 1:
                print("ERROR: deployment tx reverted")
                return 1
            print(f"deployed   : {contract}")
            print(f"           https://sepolia.etherscan.io/address/{contract}")
            print("\nSet in .env:")
            print(f"  EIV_VALIDATION_REGISTRY_ADDRESS={contract}")
            return 0
        time.sleep(5)
    print(f"tx broadcast but no receipt yet — check https://sepolia.etherscan.io/tx/{sent}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
