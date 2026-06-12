# EIV Core — Execution-Integrity Validator

[English](README.md) | **繁體中文** | [简体中文](README.zh-CN.md)

AI agent 現在在鏈上動真錢，而且會被搬空。2026 年 5 月，一個 AI agent 錢包被一條
prompt injection 推文加上一個悄悄提權的 NFT 搬走約 $175K。根本原因是一個範疇錯誤：

> **模型生成一個動作，不等於那個動作被授權。**

EIV 是一個**獨立的事實來源（source of truth）**，回答「agent 的鏈上執行有沒有待在
使用者實際簽章的授權範圍內」。給定簽章的意圖（IntentSpec）與 agent 實際在鏈上做的事，
EIV 產生一個確定性的判定。

**EIV 不要求你信任 EIV。** 這個判定是公開輸入（簽章授權 + 鏈上執行）的確定性函數，
任何人都能自己重算出同一個結果。可信來自可重現，跟信用評級或審計一樣，不是來自 EIV 的權威。

定位：**L2 — 授權符合性**（執行有沒有遵守簽章授權），而非 L3（有沒有理解使用者真實意圖）。

## 跟現有方案的差異

EIV 驗的是**結果對不對得上你的 invariant** —— 你的資金或權限有沒有跑出你簽的範圍 ——
不管牽涉到的是哪個合約。

- **vs allowlist enforcement（如 Cobo）**：白名單只在「有人已經審過的合約」上保護你，
  而長尾永遠審不完。EIV 連一個五分鐘前剛部署的合約都能保護你，因為它看的是「你的資產發生了什麼」，
  不是「對手方在不在名單上」。
- **vs 錢包內建 enforcement（Coinbase / MetaMask）**：錢包替自己的 agent 背書並不中立。
  EIV 是獨立驗證者，它的判定任何人都能重驗。
- **vs LLM guardrail（NeMo / LLM Guard）**：那些機率性地審 prompt，會被繞過——5 月那次攻擊
  就繞過了 agent 自己的安全層。EIV 確定性地審鏈上結果，與 prompt 和 agent 的推理無關。

同一個確定性檢查可以放在執行**前**（模擬提案交易 → 擋下）或執行**後**（attest → 累積 agent 的
可驗證履歷）。判定可透過 **ERC-8004** attest，讓信任紀錄跨生態可攜帶。

## 零依賴 —— 包括密碼學

EIV 的信任模型是「重驗，而不是信任」，這也延伸到供應鏈：整個 validator ——
keccak-256、secp256k1 ECDSA（RFC 6979 簽章與 ecrecover）、EIP-712 typed-data 雜湊、
RLP、EIP-1559 交易簽名、JSON-RPC、HTTP server、web console —— 全部跑在原生 Python
標準函式庫上。任何有 Python 的人都能重算判定；沒有需要審計的依賴樹。
每次 `python -m eiv.selftest` 都會用公開測試向量驗證這些密碼學原語。

## 未來方向

現在 EIV 對每筆執行輸出一個判定。隨著 agent 拿到更多鏈上權限，這些判定會彙總成一份
可攜帶、可被獨立驗證的 reputation —— 一個針對 agent 執行的獨立評級層，與錢包或 agent 本身不同。
這是長期方向；目前釋出的是確定性驗證核心。

→ 完整論證、A–G 檢查依據、EIV 與 AIP 的邊界、誠實的限制：
**[docs/POSITIONING.md](docs/POSITIONING.md)**。

## 架構

```
                      ┌─────────────────────────────────────────┐
                      │  eiv-core（本 repo，僅標準函式庫）        │
   簽章 intent ─────▶ │  Eip712Verifier   (ecrecover == signer) │
                      │        │                                │
   tx hash ────────▶  │  RpcChainAdapter  (receipt + logs +     │
                      │        │           allowance 讀取)      │
                      │        ▼                                │
                      │  predicates.py    （確定性 A–G 檢查）    │
                      │        │                                │    ERC-8004
                      │        ▼                                │  validation
                      │  OnChainAttestationSink ────────────────┼──────────────▶ contracts/
                      │        │                                │   response     EIVValidationRegistry
                      │        ▼                                │                （Sepolia）
                      │  ValidationStore + HTTP API + console   │
                      └─────────────────────────────────────────┘
                                       │ HTTP / web
                                       ▼
                            dashboard、agent、任何要重驗的人
```

- **eiv-core**（本專案）：鏈下驗證服務 —— 確定性引擎、EIP-712 驗章、即時 trace 重建、
  attestation 簽名、HTTP API 與內建 console。
- **contracts/**（本 repo 內）：極簡 ERC-8004 ValidationRegistry（Solidity 0.8.19），
  以 standalone solc-js 編譯（不用 Hardhat），由 `contracts/deploy_registry.py` 透過
  eiv-core 自己的 stdlib 簽章堆疊部署。已部署於 Sepolia；部署記錄在
  `contracts/DEPLOYMENTS.md`。部署後將地址設定到 `EIV_VALIDATION_REGISTRY_ADDRESS`
  （見 `.env.example`）。

## Console

`python -m eiv.api` 會在 `/` 提供零依賴的 web console：
內建情境（乾淨 swap、殘留 allowance 抽乾、未授權目標、2026 年 5 月 Grok/Bankr 事件重演）、
即時驗證列表、每筆 record 的完整下鑽 —— 簽章驗證結果、依類別列出的違規、canonical
簽章 intent、ERC-8004 attestation payload。完全離線可用；沒有 CDN、字型或 build step。

其中一個情境驗的是**真實的盜領交易**（[Base mainnet 上的 0x6fc7…739a](https://basescan.org/tx/0x6fc7eb7da9379383efda4253e4f599bbc3a99afed0468eabfe18484ec525739a)，
3,000,000,000 DRB ≈ $175K 流向攻擊者）。以 `RPC_URL=https://mainnet.base.org` 啟動服務，
EIV 會從鏈上抓取執行資料，並在**那筆真實交易**上標出 `B:Recipient` —— 不是 mock。

## Result schema（API 契約）

`validate()` 與 HTTP API 回傳固定的 result schema —— 下游（dashboard、attestation）的公開契約：

```jsonc
{
  "verdict": "PASS" | "FAIL",
  "violations": [
    { "category": "A:Target",
      "severity": "FAIL" | "WARN-SAFETY" | "WARN-SPEC",
      "detail":   "人類可讀的描述" }
  ]
}
```

- `verdict` 只取決於是否存在 `FAIL` 等級的違規；`WARN-*` 不影響。
- Severity：`FAIL`（違反簽章 spec 明列欄位）、`WARN-SAFETY`（有風險但 spec 沒禁止）、
  `WARN-SPEC`（spec 本身寫得不夠清楚）。
- 類別涵蓋 target、recipient、授權擴張、金額/滑點、deadline、殘留 allowance 等。
- 金額在 JSON 中一律是字串（uint256 超過 JavaScript Number 安全範圍）。

## HTTP API

| Method | Path | 說明 |
|---|---|---|
| `GET` | `/` | EIV console（內建 web UI） |
| `POST` | `/validate` | 提交 `{intent, tx_ref}`；回傳 `{validation_id, verdict, violations}` |
| `POST` | `/gate` | **事前檢查**：提交 `{intent, proposed_tx}`，解碼 calldata（ERC-20 transfer/approve/transferFrom + 原生 ETH），在任何東西上鏈之前回傳 `{decision: APPROVE\|REJECT, partial, unchecked, result}` |
| `GET` | `/reputation/{addr}` | agent 地址的信任檔案：pass-rate 信任分數（0–100）、風險等級、各類別違規統計、近期判定 |
| `GET` | `/validations` | 列出所有驗證紀錄摘要 |
| `GET` | `/validations/{id}` | 完整驗證紀錄（含 result schema） |
| `GET` | `/scenarios` | 內建 demo 情境（已簽章 intent 內嵌） |
| `GET` | `/status` | 啟用中的元件實作 + 判定計數 |
| `GET` | `/healthz` | 健康檢查 |

錯誤碼：`400` 請求格式錯誤 · `401` 簽章驗證失敗 · `404` 未知 tx_ref / id · `500` 內部錯誤。

同一個確定性判定服務三種用途：**GATE**（執行前擋下提案交易）、**RECORD**
（執行後驗證並 attest）、**reputation**（判定累積成可攜帶的信任檔案）。GATE
對自身限制透明：產出金額與殘留 allowance 在執行前無從得知，回應會列在
`unchecked` 裡。

## 快速開始

需要 Python 3.9+（開發環境 3.10）；無第三方依賴。

```bash
# 端到端 demo：一份授權、三種執行 -> PASS / FAIL / FAIL
python -m eiv.demo

# 自動化測試：判定、HTTP 行為、密碼學向量、RPC 解碼、attestation 編碼、console endpoints
python -m eiv.selftest

# 啟動 HTTP API + console（預設 127.0.0.1:8000）
python -m eiv.api

# 提交驗證請求（API 執行中時）
curl -X POST http://127.0.0.1:8000/validate \
  -H "Content-Type: application/json" \
  -d '{"intent": <eiv/fixtures/intents/intent_clean.json 的內容>, "tx_ref": "tx_clean"}'

# 用本地 key 簽署 intent（僅限測試 key）
python -m eiv.eip712 sign --intent path/to/intent.json --key 0x...
```

選擇性安裝：`pip install -e .`（MCP 工具：`pip install -e ".[mcp]"`）。

## Python SDK

agent 整合用 `eiv.sdk`，三種 client 共用同一組核心方法
（`validate` / `gate` / `reputation`）：

```python
from eiv.sdk import EivEmbed, EivClient, AsyncEivClient

# 行程內嵌 —— 不需要 server
eiv = EivEmbed()                          # MockChainAdapter（fixtures）
eiv = EivEmbed(rpc_url="https://...")     # 真鏈驗證

# 事前 gate：這筆提案交易該不該放行？
decision = eiv.gate(intent, proposed_tx)  # {"decision": "APPROVE" | "REJECT", ...}

# 事後驗證
result = eiv.validate(intent, tx_hash)    # {"validation_id", "verdict", "violations"}

# agent 信任檔案
profile = eiv.reputation("0xagent...")    # {"trust_score", "risk_level", ...}

# HTTP client（對應運行中的 `python -m eiv.api`）
client = EivClient("http://127.0.0.1:8000")

# async 包裝（兩種 client 都能包）
aclient = AsyncEivClient(client)
result = await aclient.validate(intent, tx_hash)

# 驗證後 hook（告警、記錄、熔斷）
eiv.on_validation(lambda r: alert(r) if r["verdict"] == "FAIL" else None)
```

## GLM-5.1 agent 層 — 跑在確定性護欄上的長程執行

`eiv.glm` 和 `eiv.agent_loop` 在 validator **之上**加了一個自主 agent，但它從不進入信任路徑。GLM-5.1 驅動一個多步驟 loop；它提出的每個 action 都由 EIV 把關。

- **`eiv/glm.py`** —— `GlmClient`（OpenAI-compatible、stdlib HTTP、在 429/5xx 上 retry/backoff）、`spec_from_prompt`（把白話授權轉成一個經過驗證的 `IntentSpec`，含修復回合）、`propose_transaction`（GLM 作為 agent）。
- **`eiv/agent_loop.py`** —— `AgentRun`：GLM-5.1 把任務拆成一個 plan，再透過一套 JSON action protocol 行動（`plan` / `propose_tx` / `reputation` / `finish`）。每個 `propose_tx` 都會穿過 `ValidatorService.gate()`；`REJECT` 會把確定性的違規回饋給模型，讓它自我修正。整個 run —— plan、tool calls、verdicts、修正 —— 都寫入一份 JSONL audit log。`max_steps` 為自主性設上界。
- **`glm_sandbox.py`** —— 端到端 demo（見下）。

**GLM-5.1 在哪裡被呼叫：** 只在 `GlmClient.chat()`（spec 抽取與 agent loop）。透過 `.env` 設定任何 OpenAI-compatible provider（`GLM_API_KEY` / `GLM_BASE_URL` / `GLM_MODEL`）；model id 為 `z-ai/glm-5.1`（在官方 Z.AI endpoint 上為 `glm-5.1`）。

**安全邊界 —— 從構造上模型就無法動用資金：**

- agent 只能*提出*一筆交易。通往執行的唯一路徑是一個確定性的 GATE `APPROVE`。verdict 來自 `eiv.predicates`、不依賴任何模型 —— 核心模組不 import `glm`/`agent_loop`。
- swap 被建模成一次 router call（router 透過 Permit2 拉取 input token），所以 token 合約永遠不是被允許的 target。一筆 drain —— 把 token 直接轉給攻擊者 —— 因此是對一個未授權 target 的呼叫，會被拒絕（`A:Target`），**即使模型被完全攻陷也一樣。**
- **失敗處理：** loop 能承受模型輸出格式錯誤（記為 protocol error、重試）、provider 暫時性失敗（retry with backoff；耗盡後 run 以 `status="error"` 結束、log 仍正常關閉），以及步數上限（`status="exhausted"`）。
- **人為介入：** GATE 回傳一個決定，它不廣播。執行與鏈上 attestation 仍是明確、由人把關的步驟（`EIV_ATTEST_DRY_RUN=1` 只演練、不廣播）。

跑 demo（`python glm_sandbox.py`）—— 在同一筆已簽章授權上演三幕：

| 幕 | 發生什麼 | 結果 |
|---|---|---|
| **GREEN** | 一個合規任務；GLM-5.1 規劃並提出單一 router swap | GATE `APPROVE` → 交付 |
| **RESIST** | 同一個任務，但帶一個命令把資金轉給攻擊者的 prompt injection | GLM-5.1 自己拒絕這個 injection（縱深防禦） |
| **BACKSTOP** | 一個被攻陷的 agent 繞過模型、直接送出 drain | GATE `REJECT`（`A:Target`）—— 即使模型被完全掌控也仍然成立的保證 |

## 實作狀態

EIV 把外部依賴隔離在可替換的介面後。v0.3.0 起所有 production 實作都是真的、
都有 selftest 覆蓋（174 條檢查）；參考實作保留給隔離測試與離線 demo。

v0.3.0 新增：token 地址 pinning（symbol 寫法的 spec 在真鏈 adapter 上直接拒
絕）、原生 ETH 偵測（EIP-7528 sentinel）、RPC retry + fallback URL、GATE 事
前模式、IntentSpec v1.0 正式 JSON Schema
（[docs/intent-spec-v1.schema.json](docs/intent-spec-v1.schema.json)）、
SQLite store（`EIV_STORE_BACKEND=sqlite`）、reputation API、Python SDK。

| 介面 | Production 實作（設定後預設啟用） | 參考實作 |
|---|---|---|
| `EIP712Verifier` | `Eip712Verifier` —— 從 spec 重建 EIP-712 typed-data digest、ecrecover、比對宣告 signer。內容被竄改或 signer 不符即拒絕（HTTP 401）。**預設啟用。** | `StubEIP712Verifier` |
| `ChainAdapter` | `RpcChainAdapter` —— 透過 JSON-RPC 從真節點重建 trace：receipt、ERC-20 Transfer/Approval logs、區塊時間戳、`eth_call` 讀執行後 allowance。以 `RPC_URL` 啟用。 | `MockChainAdapter`（fixtures） |
| `AttestationSink` | `OnChainAttestationSink` —— ABI 編碼 `validationResponse`、簽 EIP-1559 交易、廣播到 ERC-8004 registry。以 `EIV_VALIDATION_REGISTRY_ADDRESS` + `ATTESTER_PRIVATE_KEY` 啟用；`EIV_ATTEST_DRY_RUN=1` 只簽不播。 | `StubAttestationSink` |

替換實作不需更動編排服務、API 或驗證引擎；組裝由環境變數驅動（見 `.env.example`）。

未簽章的 intent 預設接受，但 record 會帶 `auth.verified = false`，下游永遠分得出
「密碼學驗證過的授權」和「口頭宣稱的授權」。`EIV_REQUIRE_SIGNATURE=1` 則直接拒絕。

### 與 registry 合約的 ABI 對齊

合約介面：
`validationResponse(bytes32 requestHash, bytes response, string responseURI, bytes32 responseHash, string tag)`

| 合約欄位 | 實作 |
|---|---|
| `requestHash` | intent 的 EIP-712 typed-data digest（授權者簽的那個值） |
| `response` | 單一 byte 分數：`100`（PASS）/ `0`（FAIL） |
| `responseURI` | `EIV_RESPONSE_URI_BASE` + requestHash（未設定時為空） |
| `responseHash` | canonical result JSON 的 keccak-256（承諾到完整違規集合） |
| `tag` | `EIV.L2.{verdict}`（如 `EIV.L2.PASS`）—— 與合約一致 |

### Sepolia 實鏈記錄

這條路徑不是紙上談兵，已在 Sepolia 端到端跑通：

| | |
|---|---|
| `EIVValidationRegistry`（ERC-8004 ValidationRegistry） | [`0x6719c69829740232f652b4b6bad8e6850922a2fb`](https://sepolia.etherscan.io/address/0x6719c69829740232f652b4b6bad8e6850922a2fb) |
| 第一筆真實 attestation（`OnChainAttestationSink`） | [`0xbc50b963d8f9c9f5f34ba7764f510e0f6cddf4d67a4b927584170bdac40ec6f0`](https://sepolia.etherscan.io/tx/0xbc50b963d8f9c9f5f34ba7764f510e0f6cddf4d67a4b927584170bdac40ec6f0)（block 11041392，145,626 gas，已發出 `ValidationResponse` event） |

attest 上鏈的 `requestHash` 就是 intent 的 EIP-712 digest
`0xe218a34c8204b392b0455de31668d208aef8549a039af6076654fd033ac76748`；鏈上
`hasValidation(requestHash)` 回傳 true，tag 為 `EIV.L2.PASS`。合約部署和
attestation 交易都由 eiv-core 的零依賴 stdlib 密碼學堆疊（`eiv/eth.py`）簽署
—— attestation 路徑全程沒有 Hardhat 或 web3.py。

## 專案結構

```
eiv-core/
├── eiv/
│   ├── predicates.py       # 確定性驗證引擎（規則來源）
│   ├── schema.py           # JSON <-> dataclass、金額解析、content hash
│   ├── eth.py              # stdlib 密碼學：keccak、secp256k1、RLP、ABI、EIP-1559、JSON-RPC
│   ├── eip712.py           # IntentSpec typed-data digest、簽署、驗證
│   ├── intent_source.py    # IntentSource 與 EIP712Verifier 介面
│   ├── chain_adapter.py    # MockChainAdapter + RpcChainAdapter（即時 JSON-RPC）
│   ├── attestation.py      # StubAttestationSink + OnChainAttestationSink（ERC-8004）
│   ├── service.py          # ValidatorService 編排（run + gate）
│   ├── store.py            # ValidationStore（JSON）+ SqliteValidationStore（WAL、索引查詢）
│   ├── reputation.py       # 驗證歷史 -> 信任檔案聚合
│   ├── sdk.py              # Python SDK：EivClient / EivEmbed / AsyncEivClient + hooks
│   ├── glm.py              # GLM-5.1 client + 白話->IntentSpec + agent 提案（demo 層）
│   ├── agent_loop.py       # 長程 GLM-5.1 loop，每個 action 都過 EIV gate
│   ├── api.py              # HTTP API + console（標準函式庫）
│   ├── static/index.html   # EIV console（零依賴 web UI）
│   ├── demo.py             # 端到端 demo
│   ├── selftest.py         # 自動化測試（含公開密碼學向量）
│   ├── mcp_tool.py         # MCP 工具（選擇性）
│   └── fixtures/           # 已簽章範例 intent、execution traces、scenarios
├── contracts/              # ERC-8004 ValidationRegistry（Solidity）+ stdlib 部署工具
├── docs/                   # 設計文件
├── pyproject.toml
├── .env.example
└── LICENSE
```

## 授權

MIT License —— 見 [LICENSE](LICENSE)。

## 團隊

AI × Web3 Agentic Builders Hackathon · Z.AI 賽道。
