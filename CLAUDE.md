# EIV-Core

Off-chain 驗證 agent 鏈上行為是否符合使用者簽章授權。定位是 authorization compliance，**不是 AI security**（寫文案/文件時注意）。

## 硬約束（違反前先停下問 user）

- **不改 `eiv/predicates.py` 的規則**（凍結契約）
- **不破壞凍結 schema**：validate result、HTTP API response
- **零第三方依賴**是設計約束。加 import 前確認是 stdlib（`mcp` 是唯一 optional 例外）
- 密碼學是自實作的，動 attestation / 簽章相關檔案要跑全 selftest 且需要獨立 review

## Check（宣稱「改好了」之前必跑）

```
python -m eiv.selftest    # 基準 184/184，任何改動後必須全綠
```

Demo 驗證：三 fixture 端到端應為 PASS/FAIL/FAIL。

## 已知安全缺口（2026-07-07 審計，詳見 docs/audit-2026-07-07.md）

- ~~HIGH-1: signature malleability~~ **已修 2026-07-09**：parse_signature_hex 拒 high-s（EIP-2），regression 在 selftest part C
- HIGH-2: max_slippage_bps 簽進授權但從不 enforce — 修法動到 predicates.py 凍結契約，**要 user 拍板**
- 補測試優先序見審計報告 Top 5

## 已知 TODO 方向（不要順手做，要 user 排程）

- attestation.py：ABI-encode fields、OnChainAttestationSink
- schema.py：EIP-712 typed-data digest
