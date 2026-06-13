# EIV — Demo Day 运营手册

一页搞定:开机 → 演示流程 → 话术 → 备援。

## 0. 开机（演示前 5 分钟）

```bash
cd D:\dev\eiv-core
# （可选）接真链 / 真 attestation 用：在 .env 填 RPC_URL、ATTESTER_PRIVATE_KEY
python -m eiv.api          # 启动后端 + 两个前端，默认 http://127.0.0.1:8000
```

打开两个页面备用：
- **Console**（叙事 + 一键情境）：`http://127.0.0.1:8000/`（中文：`/zh`）
- **Dashboard**（实操 GATE）：`http://127.0.0.1:8000/dashboard`（中文：`/dashboard/index_zh.html`）

> 注：端口以启动时打印为准（开发机上是 8742，默认 8000）。

## 1. 演示流程（3–5 分钟，主角是 agent run）

| 时长 | 做什么 | 在哪 |
|---|---|---|
| 0:00–0:30 | **讲问题**：AI agent 上链被注入 / 无上限授权 → 被搬空（Grok 事件 ~$175K） | 口述 |
| 0:30–2:30 | **放 agent run 录像**：`python glm_sandbox.py` 的三幕——GLM-5.1 被叫 approve 无上限 → 自己读授权改 bounded（process adjustment）；拒注入；EIV 挡盗领。**这段拿分。** | 录像 |
| 2:30–3:30 | **现场互动**：Dashboard → GATE 分页，贴 INTENT，先贴 GOOD 看 **APPROVE**、再贴 DRAIN 看当场 **REJECT** | Dashboard |
| 3:30–4:00 | **可重验 / 上链**：Console 看 validations + record 下钻；Etherscan 开 Sepolia attestation | Console + 浏览器 |

GATE 现场要贴的三段 JSON：见 [`docs/demo-run/gate-live-demo.md`](demo-run/gate-live-demo.md)。

## 2. 话术（一句话版）

- **开场**：「模型『生成』一个动作，不等于那个动作『被授权』——这是 agent 被搬空的根因。」
- **agent run**：「GLM-5.1 自主规划、逐步执行；被要求 approve 无上限时，它读签名授权、自己改成 bounded——签名授权赢过运行指令。EIV 对每一步给确定性判定。」
- **GATE 对比**：「同一份签名授权:合规的放行,盗领的当场挡下——判定来自规则,不信任模型,模型被攻陷也挡得住。」
- **收尾**：「EIV = 让长程 agent 不跑偏的确定性护栏。零依赖、selftest 182/182、判定可上链 attest。」

## 3. 链上证据（随时可亮）

- Registry（Sepolia）：`0x6719c69829740232f652b4b6bad8e6850922a2fb`
- 真 attestation tx：`0xbc50b963d8f9c9f5f34ba7764f510e0f6cddf4d67a4b927584170bdac40ec6f0`
- Etherscan：`https://sepolia.etherscan.io/tx/0xbc50b963d8f9c9f5f34ba7764f510e0f6cddf4d67a4b927584170bdac40ec6f0`

## 4. 备援 / 排错

- **agent run 跑一轮要 15–30 分钟**（GLM-5.1 推理慢）→ **一定用录像**，不要台上 live 跑。
- 后端没起来 → Dashboard 会空白；先确认 `python -m eiv.api` 在跑。
- 复现验证（评委要）：`python -m eiv.selftest`（182/182 全绿，含密码学向量、自我修正测试）。
- 一键情境：Console 的 scenario 卡可直接 Run（含 Grok 真盗领 → 判 FAIL），不用打字。

## 5.（可选）公开部署

零第三方依赖,任何能跑 Python 3.9+ 的主机都行,启动命令：

```bash
python -m eiv.api --host 0.0.0.0 --port $PORT
```

Render / Railway / Fly 免费层即可（无 build step）。要真链/真 attestation 就在主机环境变量填 `RPC_URL` + `ATTESTER_PRIVATE_KEY`（**绝不提交 key**）。本机跑也满足「可运行 Demo」规则，部署是加分项。
