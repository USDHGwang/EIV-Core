# 交接契約 / Build Handoff — AEGIS

> draft-1 · 2026-06-04 · **這份是三人並行開發的命脈**
> 配合 `PROPOSAL.md`、`ARCHITECTURE.md`

---

## 0. 最重要的一條規則

**Day 1 凍結「驗證結果 schema + Validator API」這個介面契約，然後先接一條假資料的 end-to-end walking skeleton，再各自填肉。**
三人隊死法第一名 = 各做各的，第 8 天才發現接不起來。介面先行。

---

## 1. 介面契約（Validator ⇄ Web 之間，凍結後不隨意改）

### 1.1 驗證結果 Schema（JSON）

```json
{
  "validationId": "uuid",
  "agentId": "ERC-8004 agentId 或 address",
  "chain": "monad-testnet",
  "intent": {
    "action": "swap",
    "allowedTargets": ["0x..."],
    "allowedSpenders": ["0x..."],
    "maxOutflow": "1000000",
    "tokenIn": "0x...",
    "tokenOut": "0x...",
    "intentHash": "0x... (EIP-712)",
    "signature": "0x..."
  },
  "execution": {
    "txHash": "0x...",
    "decoded": { "summary": "...", "calls": [] },
    "stateChanges": { "outflow": "...", "residualAllowance": "..." }
  },
  "verdict": "pass | fail",
  "violations": [
    { "code": "RESIDUAL_ALLOWANCE", "detail": "...", "evidenceRef": "poc-id" }
  ],
  "evidence": { "type": "foundry-poc | fork-sim", "ref": "...", "reproducible": true },
  "attestation": { "registry": "0x...", "txHash": "0x...", "timestamp": "..." },
  "validator": { "model": "GLM-5.1" }
}
```

> violation `code` 列舉（初版）：`RESIDUAL_ALLOWANCE` · `OUTFLOW_EXCEEDED` · `UNAUTHORIZED_TARGET` · `UNAUTHORIZED_SPENDER` · `VALUE_MISMATCH`。可加，但**加完同步 #2**。

### 1.2 Validator API（#2 的 web 只依賴這幾個）

| Method | Path | 用途 |
|---|---|---|
| `POST` | `/validate` | body `{intent, txHash}` → 回 `{validationId}`（非同步） |
| `GET` | `/validations` | 列表（摘要） |
| `GET` | `/validations/:id` | 完整結果（§1.1 schema） |

**MCP tool（給 host agent）**：`validate_execution(intent, txHash) -> validationId`

> #2 全程對著這個契約 + mock JSON 開發，**不需要等 John 的真邏輯**。

---

## 2. 三人工作拆分

### John（主 / moat）
- [ ] Validator 查證迴圈（GLM-5.1 orchestration）
- [ ] Grounding guard（無可重現 PoC 不報 fail）
- [ ] Integrity 檢查庫 — **複用 AIP**：allowlist / outflow cap / zero-allowance + Foundry sim
- [ ] ERC-8004 Validation Registry 合約（最小合規版）+ agent 上鏈 attest
- [ ] MCP tool 封裝 + Validator API（吐 §1 契約）
- [ ] **前置：回主來源核 ERC-8004 實際介面**（function/event signature）後再定合約

### 技術 #2（web / 直觀）
- [ ] Web dashboard：驗證列表
- [ ] **intent-vs-execution diff 視圖（demo money shot）**
- [ ] 判定 + violations + 證據 + attestation explorer 連結
- [ ] live demo 觸發鈕
- [ ] demo 用「玩具 agent」（發乾淨 / 偏離兩種交易、呼叫 MCP 請求驗證）
- [ ] 部署 / hosting
- [ ] *（若 #2 能碰後端/Solidity：API server、registry 合約、玩具 agent 可從 John 那分過來）*

### 運營
- [ ] pitch 敘事（問題 → 解法 → 為什麼重要）
- [ ] 3–5 分鐘 demo 影片（腳本見 `ARCHITECTURE.md` §3）
- [ ] README / proposal / 提交包（對 `PROPOSAL.md` §10 checklist）
- [ ] Demo Day 上台
- [ ] 進度協調、deadline 盯

---

## 3. Walking skeleton（6/4–6/5，最先做）

1. Validator 端：`GET /validations/:id` **回一筆寫死的 §1.1 JSON**
2. #2 端：dashboard 打這個 API，把那筆假資料完整 render（含 diff 視圖）
3. host 端：MCP tool 呼叫 `validate_execution` 回一個假 `validationId`

→ 三條線當天就串起來（全假資料）。之後每個人把自己後面的真東西填進去，**介面不動**。

---

## 4. 待確認（卡住才問，別空等）

1. **技術 #2 的底子** → 決定 §2 的 backend/合約歸屬。
2. **目標鏈**：沿用 Monad testnet（你 AIP 已部署過）還是換？影響 registry 部署 + tx 撈取。
3. **codename**：`AEGIS` 暫定，團隊定案後全文替換。
4. ERC-8004 registry 實際介面（John 前置核實後回填本檔 §1 與合約細節）。
