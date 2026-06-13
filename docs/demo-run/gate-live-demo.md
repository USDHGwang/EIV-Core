# GATE live demo — copy-paste cheat sheet

For an interactive Demo Day moment on the **Dashboard → GATE** tab
(`http://127.0.0.1:8742/dashboard`, requires `python -m eiv.api` running).

One signed authorization (a treasury mandate: approve the router + swap up to
100 USDC → WETH, output only to the owner, bounded approval). Paste it once,
then try the two proposals to show **APPROVE** vs **REJECT** live.

The intent is signed with the public Anvil dev key (test only) and uses real
Base addresses, so EIV decodes the calldata for real.

---

### 1. Paste into the **intent** box

```json
{"spec": {"allowed_targets": ["0x2626664c2603336e57b271c5c0b26f421741e481", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"], "allowed_spenders": ["0x2626664c2603336e57b271c5c0b26f421741e481"], "token_in": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "token_out": "0x4200000000000000000000000000000000000006", "max_amount_in": "100000000", "min_amount_out": "20000000000000000", "recipient": "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266", "deadline": 4102444800, "require_zero_residual": true, "bounded_approval": true, "max_slippage_bps": 50}, "signature": "0xb04dab3f635b3a89a0075800c737468737fd6802dbfbc46570a36cbd575dd20f42f49bf04ca0bb2915b6f3920c3c79ab16f643fd07dfdd850ec7f809e854c12b1c", "signer": "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266", "domain": {"name": "EIV", "version": "1", "chainId": 11155111}}
```

### 2a. GOOD proposed_tx → **APPROVE**

A bounded approval of exactly 50 USDC to the authorized router.

```json
{"to": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "data": "0x095ea7b30000000000000000000000002626664c2603336e57b271c5c0b26f421741e4810000000000000000000000000000000000000000000000000000000002faf080", "value": "0x0"}
```

### 2b. DRAIN proposed_tx → **REJECT** (`A:Target` + `D:Amount` + `B:Recipient`)

A compromised agent redirecting the WETH output to an attacker wallet
(`0x1111…1111`). EIV decodes it and rejects on three independent grounds.

```json
{"to": "0x4200000000000000000000000000000000000006", "data": "0xa9059cbb000000000000000000000000111111111111111111111111111111111111111100000000000000000000000000000000000000000000000000470de4df820000", "value": "0x0"}
```

---

**Talking point:** same signed mandate, two proposals. The compliant one clears;
the drain is rejected deterministically — the verdict comes from
`eiv.predicates`, not from any model, so it holds even if the agent is fully
compromised. (To regenerate this set: `python docs/demo-run/gen_gate_demo.py`.)
