# 企劃書 — Agent Execution-Integrity Validator

> **暫定 codename：`AEGIS`**（Agent Execution-integrity Guard & Independent attestation Service）— 團隊可改名
> AI × Web3 Agentic Builders Hackathon · **Z.AI 賽道（Web3 × Long-Horizon Task）**
> draft-1 · 2026-06-04 · 草稿，待團隊 review

---

## 1. 一句話

一隻**獨立、GLM-5.1 驅動的驗證 agent**：自主查證「某個 agent 有沒有照它被授權的去執行鏈上交易」，把判定 attest 進 **ERC-8004 Validation Registry**。不碰錢，做跨在所有 agent 之上的 notary。

## 2. 問題

- agent 開始自己持錢、自己上鏈執行（agentic economy）。**授權（intent / mandate）與實際執行之間會偏離**：殘留 allowance、超額 outflow、打到未授權 target、value 不符。
- 現有玩家（FluxA / Cobo / Google AP2）都在「**自己的錢包、花錢當下、事前**」擋 —— 封閉、各家一套、且本質是自我宣稱。
- **缺一層**：獨立、事後 / 第三方、跨系統、可信的**驗證 + 上鏈 attestation**。ERC-8004 Validation Registry 正是為此設計（獨立 validator 把驗證結果提交上鏈），但還是 Draft、缺工具。

## 3. 解法

| 元件 | 內容 |
|---|---|
| **Validator（核心 / moat）** | 自主查證迴圈：取授權 → 取鏈上執行 → 查證偏離 → 出判定 + 證據 → 上鏈 attest |
| **Grounding guard（差異化人格）** | 任何 `fail` 必須附**可重現的鏈上證明**（Foundry PoC / fork sim）才准報。會自己查，但絕不報沒證據的結論 |
| **Thin client（裝得上的那層）** | MCP tool / SDK：讓任何 agent 註冊一下就能「請求驗證 + 讀回 attestation」。**裝的是薄殼，不是 validator 本體** |
| **Niche（承重牆）** | 只驗**鏈上交易執行完整性**。因為是鏈上，validator 自己撈 tx、不信自述 → 就算 agent 自己裝 client 也造不了假，獨立性成立。鏈下行為標 future |

## 4. 為什麼能贏（對 Z.AI 評審）

| 評審項 | 怎麼中 |
|---|---|
| 賽道匹配 / 長程自主 | 查證→模擬→推理→上鏈 attest 是多步自主迴圈 |
| GLM-5.1 關鍵性 | GLM-5.1 驅動查證與判斷推理 |
| 任務複雜度與閉環 | 授權→執行→驗證→證據→鏈上紀錄，完整閉環 |
| 自我糾錯 | 形成假設 → 模擬驗 → 修正 |
| Web3 價值 | 「可驗證的 agent 完整性」是熱題（ERC-8004 + AP2 Authenticity 都在講） |
| 安全 / 邊界 | 本體即驗安全邊界；對「憑什麼信 validator」誠實標 future（staking/TEE） |
| 可演示 / 可復現 | web dashboard 把隱形的驗證視覺化 + 鏈上 attestation 可查 |

## 5. 為什麼是我們（moat）

- **AIP V1→V7 對抗式強化日誌** → 我們知道「執行偏離承諾」長怎樣（殘留 allowance / unbounded executor / intent-execution divergence）。別人做泛式審計，我們專打這個 niche。
- **Hermes harness 的可靠性 / grounding 紀律**（鬆 prompt → 模型編造的教訓）→ 直接變成 validator 的「不唬爛」性格。
- **Foundry / Solidity / EIP-712 簽章**現成。
- FluxA / Cobo 在錢包層有錢有背書、9 天 clone 不贏；但**獨立 verifier 這條他們沒做、我們的深度跟得上**。

## 6. 範圍

- **MVP（必做）**：on-chain 執行完整性驗證；GLM-5.1 + Foundry sim 的 grounded 查證；ERC-8004 Validation Registry（最小合規版）+ agent 上鏈 attest；MCP client，於 Hermes 上 demo 一個整合；web dashboard。
- **砍掉 / future**：zkML、TEE、多 validation method、Reputation Registry 串接、鏈下行為驗證、「通用所有 agent」的多框架支援（demo 證一個整合，pitch 講願景）。

## 7. 團隊與分工（細節見 `HANDOFF.md`）

| 角色 | 人 | 主責 |
|---|---|---|
| 主 / 技術 | **John** | Validator 核心、integrity 檢查、ERC-8004 合約、MCP、validator API |
| 技術 #2 | TBD | web dashboard（含 intent-vs-execution diff 視圖）、demo 玩具 agent、部署 |
| 運營 | TBD | pitch 敘事、3–5 分鐘 demo 影片、README/proposal、Demo Day、協調 |

> ⚠️ 待確認：技術 #2 能否碰 Solidity / 後端 → 決定 ERC-8004 合約與 API server 是 John 全扛還是分得出去。

## 8. 里程碑（2026-06-04 → 06-14）

| 日期 | 目標 |
|---|---|
| 6/4（今天）| 鎖企劃 + 介面契約（schema/API）+ 搭假資料 walking skeleton |
| 6/5–6/6 | 各自骨架：validator 迴圈框架、ERC-8004 registry、web 殼接 mock API |
| 6/7–6/9 | 填肉：integrity 檢查 + grounding guard、dashboard diff 視圖、真資料整合 |
| 6/10–6/11 | end-to-end 整合、3 個 demo 場景、邊界硬化 |
| 6/12 | 凍結、錄 demo 影片、寫 README、彩排 |
| **6/13 12:00** | **提交截止** |
| 6/14 | Demo Day |

## 9. 技術棧

GLM-5.1（核心推理）· Hermes harness（model-agnostic，指向 GLM-5.1，跑 agent）· Foundry / Solidity · ERC-8004（Validation Registry）· MCP（client）· web（框架 #2 定）· **複用 AIP 的 EIP-712 intent 格式 + invariant 檢查庫**。

## 10. 提交需求 checklist（Z.AI）

- [ ] GitHub repo + README（目標 / 架構 / 運行 / GLM-5.1 調用位置）
- [ ] 可跑 demo 或 3–5 分鐘影片
- [ ] 長程任務運行記錄（agent 的查證 / 工具調用 / 迭代軌跡）
- [ ] Web3 證明（合約地址、testnet tx、attestation 紀錄）
- [ ] 安全 / 邊界說明（validator 信任假設、失敗處理、人工介入）

## 11. 風險

| 風險 | 對策 |
|---|---|
| ERC-8004 是 Draft，介面可能變 / reference 不全 | **動手前回主來源核實際介面**（下一步）；架構不依賴 signature 細節 |
| 「憑什麼信 validator」真實世界要 staking/TEE | demo 明講成 future，當邊界說明寫進 README（評審吃這個） |
| scope 蠕變（想驗任何 agent 任務） | 守 niche：只驗鏈上執行完整性 |
| 三人隊整合翻車（第 8 天接不起來） | Day 1 凍結介面契約 + 早接 walking skeleton（見 `HANDOFF.md`） |
