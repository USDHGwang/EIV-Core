# EIV — 定位、驗證模型與差異化

> 2026-06-09 整理。涵蓋:定位、判斷依據(A–G)、verdict 的三種用法、跟現有方案的差異、
> 為什麼可信、誠實邊界、demo 計畫。核心程式碼未因本文件變動。

## 一句話

EIV 對 AI agent 的鏈上執行做**獨立、確定性**的驗證:檢查「實際發生的」符不符合
「使用者簽章授權的」,產出可被任何人重驗、可攜帶的判定與 reputation。定位 **L2 — 授權符合性**。

## 問題:Reasoning ≠ Authorization

模型生成一個動作,**不等於**該動作被授權。多數系統默認接受了「生成即執行」。

2026 已是真實風險,不是未來賭注:
- Grok/Bankr 被 prompt injection + 一個 NFT 提權搬走 ~$175K。
- LLM router 中間人搬走 $500K。
- agent 已在動真錢:x402 在 Base 破 1 億筆支付;Coinbase / MetaMask 都已推 agent 錢包。

## 判斷依據(A–G)

EIV 的判定是確定性函數 `(簽章授權, 鏈上執行) → {verdict, violations}`。每條檢查對應一個真實攻擊類型:

| 檢查 | 驗什麼 | 對應攻擊 |
|---|---|---|
| A:Target | 碰到的合約要在授權集合內 | 呼叫惡意/未授權合約 |
| B:Recipient | 產出只能流向授權 recipient | 資產轉去攻擊者(Grok) |
| C:AuthExpansion | approve 對象要授權、額度不得超量 | 無限/超額 approve、權限提升(Grok) |
| D:Amount | amountIn ≤ 上限、amountOut ≥ 下限 | 超額花費、爛價/MEV |
| E:Deadline | 須在 deadline 前 | 過期/重放 |
| F:Residual | 執行後殘留 allowance 須歸零 | 留 dangling approval 之後再搬 |
| G:SpecQuality | 授權本身缺約束時標記 | 誠實標出授權品質不足 |

分級:`FAIL`(違反簽章明列)/ `WARN-SAFETY`(有風險但沒禁)/ `WARN-SPEC`(授權沒寫清楚)。

Grok 那筆對應 `B:Recipient` + `C:AuthExpansion`(+`A:Target`)。EIV 不看 prompt、不看 agent 被提升成什麼權限,
只比對「鏈上結果 vs 簽章授權」—— 提權對它無效,因為它讀的是使用者的簽章,不是 agent 的權限狀態。

## verdict 的三種用法(要刻意選)

一個 verdict 本身不值錢;它值多少等於後面接什麼後果。

- **GATE** — 放執行**前**(模擬提案交易 → 驗 → 不過不送)。真阻止,連單筆致命也擋得到。代價:進執行路徑 = enforcement。
- **BREAK** — 放**每步後**,一違規就凍結 agent。控制損害(賠一筆 vs 賠光);對單筆致命無效。
- **RECORD** — 放執行**後**,出 attestation。**救不了當下那筆**,價值是向前的:累積 reputation(下次誰敢用)+ 問責(押金 slash / 保險理賠 / 糾紛仲裁)。

誠實:純事後審計(RECORD)不能阻止當下損失。要保護當下的錢,必須用 GATE。

## 跟現有方案的差異

| 對手 | 他們做什麼 | EIV 的不同 |
|---|---|---|
| allowlist enforcement(Cobo) | 看合約身份,只放行白名單合約 | **看結果不看身份**:對未知/新合約也保護(只要結果違反你的 invariant 就抓),不靠團隊審合約 |
| in-wallet enforcement(Coinbase / MetaMask) | 在自己錢包內 enforce policy | **中立第三方 + 可攜帶 reputation**;錢包替自己 agent 背書不算 trustless |
| LLM guardrail(NeMo / LLM Guard) | 機率性審 prompt / output | **確定性審鏈上結果**;繞過 Grok guardrail 的攻擊繞不過 outcome check |
| AIP(同團隊) | 鏈上原子 enforce,不符就 revert | 見下 |

**EIV vs AIP**:AIP 的 prevention 更硬(原子、上鏈、沒模擬破口、裝了繞不過),但只在**裝了 module 的帳戶**、且**不產出可攜帶的信任紀錄**。EIV 更廣(驗任何 agent、不用改帳戶)且產出可攜帶 reputation,但 prevention 較軟。底層同一套 invariant,不同落點。類比:AIP = 門上的鎖;EIV = 驗屋 + 信用評分。兩者互補。

invariant vs allowlist 的類比:allowlist = 舊式防毒(比對特徵庫,新威脅就漏);EIV = 行為偵測(看實際做了什麼)。

## 為什麼可信(trust-minimization)

不是「信我們」。EIV 的判定是:可重現(任何人拿同樣公開輸入重跑得同一 verdict)、規則公開、上鏈錨定(ERC-8004)、不託管不執行。可信度來自「可被獨立重驗」,不是權威。`predicates.py` 做成確定性、模型不能動的核心,就是這個理由。

## 誠實邊界(別被尖評審反殺)

- **L2 not L3**:驗「符合你簽的」,不驗「你簽的是對的」。簽了爛授權,EIV 照樣判合規。
- 守你的**下限**,不保證最佳執行。
- `token_out` 要用**地址** pin,不能用符號(否則假 token 過關)。
- invariant **只守它涵蓋的範圍**(錢被動的攻擊面守得好;沒寫到的怪招會漏 → `G` 標出)。
- GATE 模式靠**模擬**,有 simulation-divergence(模擬乖、實際壞)→ 靠 RECORD 那層補。
- **現況**:確定性核心 + 編排 + 儲存 + HTTP API 真且測過(selftest 23/23);三個邊界(簽章驗證 / 取 trace / 上鏈 attest)仍是 stub,介面凍好、可填真實作。

## Demo 計畫

**Agent Trust Sandbox**(網頁,打現有 EIV API):
① 白話設授權 → ② GLM agent 提案動作 + EIV 即時 ✓/✗ → ③ 🔴 重演 Grok 攻擊被擋 → ④ agent 成績單 / 信任查詢。

補強(投報率排序):
1. **跑真的 Grok tx**(公開、Base 上):顯示 EIV 對真實 $175K 盜領判 FAIL。最高槓桿、最省力。
2. **attestation 真寫 Sepolia**:用 `eiv-contracts` 的 `EIVValidationRegistry`,把 stub 換成真上鏈一次,Etherscan 可查。
3. **跟 allowlist 並排**:演「未知合約 EIV 照樣保護、allowlist 工具做不到」。

天花板:verification 天生比炫 app 安靜;強度靠真實 + 可信(真 tx、真上鏈),不是視覺煙火。

## 市場 grounding(sources)

- [Coinbase Agentic Wallets](https://cointelegraph.com/news/coinbase-launches-crypto-wallets-built-ai-agents)
- [MetaMask agent wallet (2026-06-08)](https://www.coindesk.com/tech/2026/06/08/metamask-launches-ai-agent-wallet-with-built-in-security-for-crypto-trades)
- [Grok/Bankr $175K drain](https://www.cryptotimes.io/2026/05/04/xais-grok-ai-loses-175k-in-crypto-heist-via-clever-prompt-injection-then-gets-it-all-back/)
- [CoinDesk: critical security gap](https://www.coindesk.com/tech/2026/04/13/ai-agents-are-set-to-power-crypto-payments-but-a-hidden-flaw-could-expose-wallets)
- [The Hacker News: agents as authz bypass](https://thehackernews.com/2026/01/ai-agents-are-becoming-privilege.html)
- [Cobo agentic wallet (Pact policies / MPC)](https://www.cobo.com/post/agentic-wallet-ai-crypto-wallet-guide)
- [x402 / Chainalysis (100M payments)](https://www.chainalysis.com/blog/x402-agentic-payments-adoption/)
- [ERC-8004 (mainnet 2026-01)](https://eips.ethereum.org/EIPS/eip-8004)
