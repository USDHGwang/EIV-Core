# Deployments

## Sepolia (chain id 11155111)

| | |
|---|---|
| Contract | `EIVValidationRegistry` (ERC-8004 ValidationRegistry, minimal) |
| Address | [`0x6719c69829740232f652b4b6bad8e6850922a2fb`](https://sepolia.etherscan.io/address/0x6719c69829740232f652b4b6bad8e6850922a2fb) |
| Deploy tx | [`0x1e65604af37eb880cc04e204fcd439bec92913781f898b83835c3bab89c61c6d`](https://sepolia.etherscan.io/tx/0x1e65604af37eb880cc04e204fcd439bec92913781f898b83835c3bab89c61c6d) |
| Deployed | 2026-06-12, 706,287 gas |
| Owner / attester | `0xa9ad686e8183e54ccb9684b24110a269fe03be61` |
| Compiler | solc 0.8.19, optimizer 200 runs (`compile_standalone.js`) |
| Deploy method | `deploy_registry.py` — signed by eiv-core's stdlib stack (`eiv/eth.py`), no Hardhat |

First attestation written through this registry:
[`0xbc50b963d8f9c9f5f34ba7764f510e0f6cddf4d67a4b927584170bdac40ec6f0`](https://sepolia.etherscan.io/tx/0xbc50b963d8f9c9f5f34ba7764f510e0f6cddf4d67a4b927584170bdac40ec6f0)
(block 11041392 — `requestHash` = the intent's EIP-712 digest, tag `EIV.L2.PASS`,
`hasValidation(requestHash)` returns true).
