# EIV × Z.AI 賽道 — 優化筆記（本地,不 push）

> 研究 + 發想。2026-06-12。deadline 6/13 12:00 UTC+8。
> 這份只存本地,不進公開 repo（策略/研究不該公開）。

---

## A. 研究情報 + 策略含義

### A1. GLM-5.1 官方定位（z.ai / NVIDIA / 媒體）
- 賣點:**「長程 agentic LLM,單一任務可連續自主工作 8 小時」**,SWE-Bench Pro SOTA,754B MoE,200K context。
- 官方四拍框架:**long-horizon planning → stepwise execution → process adjustment → result delivery**。
- agentic/tool benchmark:τ³-Bench 70.6、MCP-Atlas 71.8、Terminal-Bench 63.5。
- 主打跟 coding agent(Claude Code 等)整合。

**含義(高槓桿)**:我們的 demo 敘事要**逐字對齊 Z.AI 自己的四拍**——
| GLM-5.1 官方拍子 | EIV demo 對應 |
|---|---|
| long-horizon planning | agent `plan`(多步拆解) |
| stepwise execution | 每步 `propose_tx` 過 EIV GATE |
| **process adjustment** | **REJECT → 讀違規 → 自我修正**(= EIV 讓這拍變確定性 grounded) |
| result delivery | `finish` 交付報告 |
評審來自 Z.AI,看到自家模型的招牌強項被我們的架構 1:1 展示 + EIV 讓「process adjustment」從機率變確定 → 直接加分。**這是把 EIV「別信任模型」從劣勢翻成「我讓 GLM 的長程更可靠」的最強話術。**

### A2. 評審/評估慣例
- 維度 ~各 20%:Idea / Technical / **Tool Use(用好 sponsor 工具=GLM-5.1)** / Presentation(3 分鐘) / **Autonomy(無人工介入)**。
- **Agent-as-a-Judge 評「整條軌跡」**:中間步驟 + 工具調用,不只結果。
  - **含義**:我們的 **JSONL run log**(逐事件:plan/gate/violations/finish)正是 trajectory-eval 要的東西 → 提交一定要附,且要乾淨可讀。`docs/demo-run/` 就是為此。
  - Autonomy 要「無人工介入」→ demo 要強調 agent 自己跑完,人只簽授權。

---

## B0. 最終決定（已定案 06-13）
- **兩次 live 證實:GLM-5.1 看得到 spec 就不犯規**——連明確叫它 approve `type(uint256).max`,它都自己改 bounded(delivery 明寫「bounded_approval=true overrode the task's request」)。**live GATE-level 自我修正觸發不了。**
- **選 A**:主打 **GLM process adjustment**(它讀授權、推翻 max 指令、改 bounded = GLM 真自我調整,對齊官方四拍)+ **selftest D11** 當 GATE REJECT→修正迴圈的確定性證據。**全 live、不腳本化、最誠實。**
- 三幕定案:ACT1 PROCESS ADJUSTMENT / ACT2 RESIST / ACT3 BACKSTOP。commit 7feee12(本地)。
- 小瑕疵(可選修):GLM 推 `min_amount_out=0`(授權沒寫最低)→ 無滑點保護。要修就在 AUTHORIZATION 加「at least 0.02 WETH」再重跑。deadline 前不急。

## B. 關鍵發現:live 自我修正觸發問題

- 第一次 live(誘導 "this and future swaps"):GLM-5.1 **太守規矩,第一次就 bounded approve**,沒觸發 REJECT。
- 根因:**模型看得到 spec**,任何 spec-可檢查的約束它都會先遵守 → 騙不動。
- 對策(進行中):ACT 1 任務改成**明確叫 agent approve 最大額度**(operator 為省 gas)→ 製造「**運行指令 vs 簽章授權**」衝突。預期:agent 照指令提 unlimited → C:AuthExpansion REJECT → 修正成 bounded。
  - 即使這次還是不觸發(模型可能 refuse-in-plan),**selftest D11 是確定性鐵證**(REJECT→APPROVE→APPROVE),提交時當「自我修正機制」證據。
- **誠實底線**:不宣稱 live 演到自我修正,除非真的演到。沒演到就用 D11 + 機制說明 + 「模型很守規矩本身也是好事(EIV 證明它合規)」。

---

## C. 24 小時內優化行動(按槓桿排序)

1. **【做】ACT 1 觸發自我修正**(運行指令 vs 簽章授權衝突)→ 拿到 live process-adjustment 鏡頭。重跑中。
2. **【做】輸出 ASCII 上鏡化** → 錄影乾淨。已改。
3. **【做】敘事對齊 GLM-5.1 四拍**:glm_sandbox 結尾 + README + 影片腳本都用 planning→stepwise→process adjustment→delivery 的字眼。
4. **【做】提交清單對齊 rubric**(見 D)。
5. **【選】min_amount_out=0 修掉**:授權加回「at least 0.02 WETH」,讓 spec 有滑點保護,顯得完整(GLM 現在推 min_out=0)。
6. **【選】reputation 工具進 ACT 1**:多一個工具調用 beat(Tool Use 分),但語意要真(查交易對手/自身歷史),別硬塞。時間夠才做。

---

## D. 提交清單(對齊賽道硬要求)

- [ ] **GitHub Repo + README**:目標/架構/運行方式/**GLM-5.1 調用位置與關鍵流程** ← README 已有 GLM 段,要更新成三幕 + 四拍框架。
- [ ] **可運行 Demo**:`python glm_sandbox.py`(GLM 驅動)+ `python -m eiv.selftest`(180/180)。
- [ ] **3-5 分鐘 Demo 影片**(運營錄):主角 = agent run,證據 = dashboard + Etherscan。腳本見 E。
- [ ] **長程任務運行記錄**:`docs/demo-run/` 的 JSONL(拆解/工具/修復/交付)← trajectory-eval 命脈。
- [ ] **Web3 證明**:Sepolia registry `0x6719…a2fb` + 真 attestation `0xbc50…c6f0`(已有)。
- [ ] **邊界說明**:安全/失敗/人工介入 ← README 已有 safety boundary 段。

---

## E. 影片腳本骨架(3-5 分鐘,主角 = agent run)

1. **0:00-0:30 問題**:AI agent 被注入 / unlimited approval → $175K 被搬空。一句話。
2. **0:30-1:00 授權**:白話 mandate → GLM-5.1 生 IntentSpec → 簽章。「簽章 = 唯一授權真相」。
3. **1:00-3:00 主戲(ACT 1)**:GLM-5.1 自主跑——
   - **planning**:拆多步計畫
   - **stepwise execution**:每步過 EIV GATE
   - **process adjustment(money shot)**:operator 叫它 approve max → **EIV 擋(C:AuthExpansion)** → agent 讀違規 → 改 bounded → APPROVE
   - **result delivery**:交付
   旁白點題:「GLM-5.1 的長程招牌 + EIV 讓 process adjustment 從機率變確定」。
4. **3:00-3:40 韌性**:ACT 2 注入被模型自拒 + ACT 3 BACKSTOP 確定性擋 drain。
5. **3:40-4:10 證據**:dashboard 那筆 record + Etherscan 上 Sepolia 真 attestation。「可重驗、上了鏈」。
6. **4:10-end 收**:EIV = 讓長程 agent 不跑偏的確定性護欄。selftest 180/180、零依賴。

---

## F. Deadline 後 / 加分項(不急)

- **agent-run 視覺化前端**(解法 B):計畫浮現 + 每步 verdict + 自我修正高亮。比靜態 dashboard 更貼賽道。
- **真上鏈閉環**:agent approve+swap 真廣播 Sepolia → RECORD 驗 → attest(補 #3 execute+verify)。需 mock ERC20/router。
- **多步複雜任務**:rebalance(多 swap 串聯)/ 帶 reputation gating 的交易對手檢查 → 更長 horizon。
- **dashboard 與 console 收斂**:目前兩個前端,理清主從。

---

## G. 一句話定位(對外統一口徑)
> EIV 是讓長程 GLM-5.1 agent 不跑偏的**確定性護欄**:GLM 自主規劃、逐步執行、自我修正、交付;EIV 對每一步給出可重驗、可上鏈(ERC-8004)的確定性判定。模型負責聰明,EIV 負責不出事。
