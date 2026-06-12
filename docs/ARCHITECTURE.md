# 流程圖 / 架構 — AEGIS

> draft-1 · 2026-06-04 · 配合 `PROPOSAL.md`、`HANDOFF.md`
> 圖用 Mermaid（GitHub / Obsidian / VS Code 直接 render）

---

## 1. 系統架構（誰跟誰講話）

```mermaid
flowchart TB
    subgraph host["任何 Agent（host）"]
        A["Agent 執行鏈上交易"]
        C["Thin client / MCP tool<br/>（裝上的薄殼）"]
        A --> C
    end

    subgraph val["AEGIS Validator（獨立 / moat）"]
        L["GLM-5.1 查證迴圈"]
        G["Grounding guard<br/>無 PoC 不報 fail"]
        I["Integrity 檢查庫<br/>(複用 AIP invariant + Foundry sim)"]
        API["Validator API"]
        L --> G
        G --> I
        API --> L
    end

    CHAIN["鏈上<br/>(tx / state)"]
    REG["ERC-8004<br/>Validation Registry"]
    WEB["Web Dashboard（#2）<br/>diff 視圖 + 證據 + attestation"]

    C -- "請求驗證 (intent, txHash)" --> API
    L -- "獨立撈取執行真相" --> CHAIN
    G -- "寫 attestation" --> REG
    API -- "讀驗證結果" --> WEB
    REG -- "讀 attestation" --> WEB
    C -- "讀回判定" --> A

    classDef moat fill:#1f6feb22,stroke:#1f6feb;
    class val moat;
```

> 關鍵：client 裝在 host 上，但 **validator 自己去鏈上撈執行真相**（不信 host 自述）→ 獨立性成立。

---

## 2. Validator 查證迴圈（核心邏輯）

```mermaid
flowchart TD
    S["收到驗證請求<br/>(intent + txHash)"] --> P1["取授權：解析簽章 intent<br/>(EIP-712 AllowlistedIntent)"]
    P1 --> P2["取執行：鏈上撈 tx<br/>decode calldata + state change"]
    P2 --> P3["GLM-5.1 比對偏離<br/>target/spender? outflow? residual allowance? value?"]
    P3 --> Q{"疑似偏離?"}
    Q -- "否" --> PASS["判定 PASS"]
    Q -- "是" --> E["生成可重現證據<br/>Foundry PoC / fork sim"]
    E --> Q2{"證據跑得出來?"}
    Q2 -- "否（不可重現）" --> P3
    Q2 -- "是" --> FAIL["判定 FAIL + 違反項 + PoC"]
    PASS --> ATT["上鏈 attest 到 ERC-8004"]
    FAIL --> ATT
    ATT --> OUT["回傳結果 + 寫入 API"]
```

> `Q2 否 → 回 P3`：這條迴圈就是 grounding guard —— 報不出可重現證據就不准定 fail，逼它重查或收回。也是「長程 / 自我糾錯」評審項的來源。

---

## 3. Demo 流程（Demo Day 3–5 分鐘）

```mermaid
sequenceDiagram
    participant U as 觀眾/評委
    participant T as Demo 玩具 Agent (#2)
    participant V as AEGIS Validator (John)
    participant CH as 鏈 (testnet)
    participant W as Dashboard (#2)

    U->>T: 場景一：授權「swap A→B、上限 X」
    T->>CH: 執行（乾淨）
    T->>V: 請求驗證(intent, txHash)
    V->>CH: 撈 tx + state
    V->>V: 比對 → 無偏離
    V->>CH: attest PASS
    V->>W: 結果
    W->>U: 綠燈 + attestation 連結

    U->>T: 場景二：授權同上，但偷塞殘留 allowance / 超額 outflow
    T->>CH: 執行（偏離）
    T->>V: 請求驗證
    V->>CH: 撈 tx + state
    V->>V: 抓到偏離 → 跑 Foundry PoC
    V->>CH: attest FAIL + 證據
    V->>W: 結果
    W->>U: 紅燈 + intent-vs-execution diff + PoC + 鏈上 attestation
```

---

## 4. 兩側拆分（哪塊裝得上、哪塊是 moat）

```mermaid
flowchart LR
    subgraph install["可裝在任何 agent（薄）"]
        MCP["MCP tool / SDK<br/>register · request · read"]
    end
    subgraph keep["獨立、不外發（moat）"]
        VAL["Validator 推理 + integrity 邏輯"]
        ATTW["attestation 寫入權"]
    end
    MCP -. "只發請求/讀結果" .-> VAL
```

> 「裝在所有 agent 上」的是左邊薄殼；判定與 attestation 來源永遠在右邊獨立側 → 避免「自己證自己」的循環。
