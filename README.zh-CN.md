# EIV Core — Execution-Integrity Validator

[English](README.md) | [繁體中文](README.zh-TW.md) | **简体中文**

AI agent 现在在链上动真钱，而且会被搬空。2026 年 5 月，一个 AI agent 钱包被一条
prompt injection 推文加上一个悄悄提权的 NFT 搬走约 $175K。根本原因是一个范畴错误：

> **模型生成一个动作，不等于那个动作被授权。**

EIV 是一个**独立的事实来源（source of truth）**，回答「agent 的链上执行有没有待在
用户实际签名授权的范围内」。给定签名的意图（IntentSpec）与 agent 实际在链上做的事，
EIV 产生一个确定性的判定。

**EIV 不要求你信任 EIV。** 这个判定是公开输入（签名授权 + 链上执行）的确定性函数，
任何人都能自己重算出同一个结果。可信来自可重现，跟信用评级或审计一样，不是来自 EIV 的权威。

定位：**L2 — 授权符合性**（执行有没有遵守签名授权），而非 L3（有没有理解用户真实意图）。

## 跟现有方案的差异

EIV 验的是**结果对不对得上你的 invariant** —— 你的资金或权限有没有跑出你签的范围 ——
不管牵涉到的是哪个合约。

- **vs allowlist enforcement（如 Cobo）**：白名单只在「有人已经审过的合约」上保护你，
  而长尾永远审不完。EIV 连一个五分钟前刚部署的合约都能保护你，因为它看的是「你的资产发生了什么」，
  不是「对手方在不在名单上」。
- **vs 钱包内置 enforcement（Coinbase / MetaMask）**：钱包替自己的 agent 背书并不中立。
  EIV 是独立验证者，它的判定任何人都能重验。
- **vs LLM guardrail（NeMo / LLM Guard）**：那些概率性地审 prompt，会被绕过——5 月那次攻击
  就绕过了 agent 自己的安全层。EIV 确定性地审链上结果，与 prompt 和 agent 的推理无关。

同一个确定性检查可以放在执行**前**（模拟提案交易 → 拦下）或执行**后**（attest → 积累 agent 的
可验证履历）。判定可通过 **ERC-8004** attest，让信任记录跨生态可携带。

## 零依赖 —— 包括密码学

EIV 的信任模型是「重验，而不是信任」，这也延伸到供应链：整个 validator ——
keccak-256、secp256k1 ECDSA（RFC 6979 签名与 ecrecover）、EIP-712 typed-data 哈希、
RLP、EIP-1559 交易签名、JSON-RPC、HTTP server、web console —— 全部跑在原生 Python
标准库上。任何有 Python 的人都能重算判定；没有需要审计的依赖树。
每次 `python -m eiv.selftest` 都会用公开测试向量验证这些密码学原语。

## 未来方向

现在 EIV 对每笔执行输出一个判定。随着 agent 拿到更多链上权限，这些判定会汇总成一份
可携带、可被独立验证的 reputation —— 一个针对 agent 执行的独立评级层，与钱包或 agent 本身不同。
这是长期方向；目前发布的是确定性验证核心。

→ 完整论证、A–G 检查依据、EIV 与 AIP 的边界、诚实的限制：
**[docs/POSITIONING.md](docs/POSITIONING.md)**。

## 架构

```
                      ┌─────────────────────────────────────────┐
                      │  eiv-core（本 repo，仅标准库）            │
   签名 intent ─────▶ │  Eip712Verifier   (ecrecover == signer) │
                      │        │                                │
   tx hash ────────▶  │  RpcChainAdapter  (receipt + logs +     │
                      │        │           allowance 读取)      │
                      │        ▼                                │
                      │  predicates.py    （确定性 A–G 检查）    │
                      │        │                                │    ERC-8004
                      │        ▼                                │  validation
                      │  OnChainAttestationSink ────────────────┼──────────────▶ contracts/
                      │        │                                │   response     EIVValidationRegistry
                      │        ▼                                │                （Sepolia）
                      │  ValidationStore + HTTP API + console   │
                      └─────────────────────────────────────────┘
                                       │ HTTP / web
                                       ▼
                            dashboard、agent、任何要重验的人
```

- **eiv-core**（本项目）：链下验证服务 —— 确定性引擎、EIP-712 验签、实时 trace 重建、
  attestation 签名、HTTP API 与内置 console。
- **contracts/**（本 repo 内）：极简 ERC-8004 ValidationRegistry（Solidity 0.8.19），
  以 standalone solc-js 编译（不用 Hardhat），由 `contracts/deploy_registry.py` 通过
  eiv-core 自己的 stdlib 签名栈部署。已部署于 Sepolia；部署记录在
  `contracts/DEPLOYMENTS.md`。部署后将地址设置到 `EIV_VALIDATION_REGISTRY_ADDRESS`
  （见 `.env.example`）。

## Console

`python -m eiv.api` 会在 `/` 提供零依赖的 web console：
内置场景（干净 swap、残留 allowance 抽干、未授权目标、2026 年 5 月 Grok/Bankr 事件重演）、
实时验证列表、每笔 record 的完整下钻 —— 签名验证结果、按类别列出的违规、canonical
签名 intent、ERC-8004 attestation payload。完全离线可用；没有 CDN、字体或 build step。

其中一个场景验的是**真实的盗领交易**（[Base mainnet 上的 0x6fc7…739a](https://basescan.org/tx/0x6fc7eb7da9379383efda4253e4f599bbc3a99afed0468eabfe18484ec525739a)，
3,000,000,000 DRB ≈ $175K 流向攻击者）。以 `RPC_URL=https://mainnet.base.org` 启动服务，
EIV 会从链上抓取执行数据，并在**那笔真实交易**上标出 `B:Recipient` —— 不是 mock。

## Result schema（API 契约）

`validate()` 与 HTTP API 返回固定的 result schema —— 下游（dashboard、attestation）的公开契约：

```jsonc
{
  "verdict": "PASS" | "FAIL",
  "violations": [
    { "category": "A:Target",
      "severity": "FAIL" | "WARN-SAFETY" | "WARN-SPEC",
      "detail":   "人类可读的描述" }
  ]
}
```

- `verdict` 只取决于是否存在 `FAIL` 等级的违规；`WARN-*` 不影响。
- Severity：`FAIL`（违反签名 spec 明列字段）、`WARN-SAFETY`（有风险但 spec 没禁止）、
  `WARN-SPEC`（spec 本身写得不够清楚）。
- 类别涵盖 target、recipient、授权扩张、金额/滑点、deadline、残留 allowance 等。
- 金额在 JSON 中一律是字符串（uint256 超过 JavaScript Number 安全范围）。

## HTTP API

| Method | Path | 说明 |
|---|---|---|
| `GET` | `/` | EIV console（内置 web UI） |
| `POST` | `/validate` | 提交 `{intent, tx_ref}`；返回 `{validation_id, verdict, violations}` |
| `POST` | `/gate` | **事前检查**：提交 `{intent, proposed_tx}`，解码 calldata（ERC-20 transfer/approve/transferFrom + 原生 ETH），在任何东西上链之前返回 `{decision: APPROVE\|REJECT, partial, unchecked, result}` |
| `GET` | `/reputation/{addr}` | agent 地址的信任档案：pass-rate 信任分数（0–100）、风险等级、各类别违规统计、近期判定 |
| `GET` | `/validations` | 列出所有验证记录摘要 |
| `GET` | `/validations/{id}` | 完整验证记录（含 result schema） |
| `GET` | `/scenarios` | 内置 demo 场景（已签名 intent 内嵌） |
| `GET` | `/status` | 启用中的组件实现 + 判定计数 |
| `GET` | `/healthz` | 健康检查 |

错误码：`400` 请求格式错误 · `401` 签名验证失败 · `404` 未知 tx_ref / id · `500` 内部错误。

同一个确定性判定服务三种用途：**GATE**（执行前拦下提案交易）、**RECORD**
（执行后验证并 attest）、**reputation**（判定累积成可携带的信任档案）。GATE
对自身限制透明：产出金额与残留 allowance 在执行前无从得知，响应会列在
`unchecked` 里。

## 快速开始

需要 Python 3.9+（开发环境 3.10）；无第三方依赖。

```bash
# 端到端 demo：一份授权、三种执行 -> PASS / FAIL / FAIL
python -m eiv.demo

# 自动化测试：判定、HTTP 行为、密码学向量、RPC 解码、attestation 编码、console endpoints
python -m eiv.selftest

# 启动 HTTP API + console（默认 127.0.0.1:8000）
python -m eiv.api

# 提交验证请求（API 运行中时）
curl -X POST http://127.0.0.1:8000/validate \
  -H "Content-Type: application/json" \
  -d '{"intent": <eiv/fixtures/intents/intent_clean.json 的内容>, "tx_ref": "tx_clean"}'

# 用本地 key 签署 intent（仅限测试 key）
python -m eiv.eip712 sign --intent path/to/intent.json --key 0x...
```

可选安装：`pip install -e .`（MCP 工具：`pip install -e ".[mcp]"`）。

## Python SDK

agent 集成用 `eiv.sdk`，三种 client 共用同一组核心方法
（`validate` / `gate` / `reputation`）：

```python
from eiv.sdk import EivEmbed, EivClient, AsyncEivClient

# 进程内嵌 —— 不需要 server
eiv = EivEmbed()                          # MockChainAdapter（fixtures）
eiv = EivEmbed(rpc_url="https://...")     # 真链验证

# 事前 gate：这笔提案交易该不该放行？
decision = eiv.gate(intent, proposed_tx)  # {"decision": "APPROVE" | "REJECT", ...}

# 事后验证
result = eiv.validate(intent, tx_hash)    # {"validation_id", "verdict", "violations"}

# agent 信任档案
profile = eiv.reputation("0xagent...")    # {"trust_score", "risk_level", ...}

# HTTP client（对应运行中的 `python -m eiv.api`）
client = EivClient("http://127.0.0.1:8000")

# async 包装（两种 client 都能包）
aclient = AsyncEivClient(client)
result = await aclient.validate(intent, tx_hash)

# 验证后 hook（告警、记录、熔断）
eiv.on_validation(lambda r: alert(r) if r["verdict"] == "FAIL" else None)
```

## GLM-5.1 agent 层 — 跑在确定性护栏上的长程执行

`eiv.glm` 和 `eiv.agent_loop` 在 validator **之上**加了一个自主 agent，但它从不进入信任路径。GLM-5.1 驱动一个多步骤 loop；它提出的每个 action 都由 EIV 把关。

- **`eiv/glm.py`** —— `GlmClient`（OpenAI-compatible、stdlib HTTP、在 429/5xx 上 retry/backoff）、`spec_from_prompt`（把白话授权转成一个经过验证的 `IntentSpec`，含修复回合）、`propose_transaction`（GLM 作为 agent）。
- **`eiv/agent_loop.py`** —— `AgentRun`：GLM-5.1 把任务拆成一个 plan，再通过一套 JSON action protocol 行动（`plan` / `propose_tx` / `reputation` / `finish`）。每个 `propose_tx` 都会穿过 `ValidatorService.gate()`；`REJECT` 会把确定性的违规反馈给模型，让它自我修正。整个 run —— plan、tool calls、verdicts、修正 —— 都写入一份 JSONL audit log。`max_steps` 为自主性设上界。
- **`glm_sandbox.py`** —— 端到端 demo（见下）。

**GLM-5.1 在哪里被调用：** 只在 `GlmClient.chat()`（spec 抽取与 agent loop）。通过 `.env` 配置任何 OpenAI-compatible provider（`GLM_API_KEY` / `GLM_BASE_URL` / `GLM_MODEL`）；model id 为 `z-ai/glm-5.1`（在官方 Z.AI endpoint 上为 `glm-5.1`）。

**安全边界 —— 从构造上模型就无法动用资金：**

- agent 只能*提出*一笔交易。通往执行的唯一路径是一个确定性的 GATE `APPROVE`。verdict 来自 `eiv.predicates`、不依赖任何模型 —— 核心模块不 import `glm`/`agent_loop`。
- swap 被建模成一次 router call（router 通过 Permit2 拉取 input token），所以 token 合约永远不是被允许的 target。一笔 drain —— 把 token 直接转给攻击者 —— 因此是对一个未授权 target 的调用，会被拒绝（`A:Target`），**即使模型被完全攻陷也一样。**
- **失败处理：** loop 能承受模型输出格式错误（记为 protocol error、重试）、provider 暂时性失败（retry with backoff；耗尽后 run 以 `status="error"` 结束、log 仍正常关闭），以及步数上限（`status="exhausted"`）。
- **人为介入：** GATE 返回一个决定，它不广播。执行与链上 attestation 仍是明确、由人把关的步骤（`EIV_ATTEST_DRY_RUN=1` 只演练、不广播）。

跑 demo（`python glm_sandbox.py`）—— 在同一笔已签名授权上演三幕：

| 幕 | 发生什么 | 结果 |
|---|---|---|
| **GREEN** | 一个合规任务；GLM-5.1 规划并提出单一 router swap | GATE `APPROVE` → 交付 |
| **RESIST** | 同一个任务，但带一个命令把资金转给攻击者的 prompt injection | GLM-5.1 自己拒绝这个 injection（纵深防御） |
| **BACKSTOP** | 一个被攻陷的 agent 绕过模型、直接送出 drain | GATE `REJECT`（`A:Target`）—— 即使模型被完全掌控也仍然成立的保证 |

## 实现状态

EIV 把外部依赖隔离在可替换的接口后。v0.3.0 起所有 production 实现都是真的、
都有 selftest 覆盖（174 条检查）；参考实现保留给隔离测试与离线 demo。

v0.3.0 新增：token 地址 pinning（symbol 写法的 spec 在真链 adapter 上直接拒
绝）、原生 ETH 检测（EIP-7528 sentinel）、RPC retry + fallback URL、GATE 事
前模式、IntentSpec v1.0 正式 JSON Schema
（[docs/intent-spec-v1.schema.json](docs/intent-spec-v1.schema.json)）、
SQLite store（`EIV_STORE_BACKEND=sqlite`）、reputation API、Python SDK。

| 接口 | Production 实现（配置后默认启用） | 参考实现 |
|---|---|---|
| `EIP712Verifier` | `Eip712Verifier` —— 从 spec 重建 EIP-712 typed-data digest、ecrecover、比对声明 signer。内容被篡改或 signer 不符即拒绝（HTTP 401）。**默认启用。** | `StubEIP712Verifier` |
| `ChainAdapter` | `RpcChainAdapter` —— 通过 JSON-RPC 从真节点重建 trace：receipt、ERC-20 Transfer/Approval logs、区块时间戳、`eth_call` 读执行后 allowance。以 `RPC_URL` 启用。 | `MockChainAdapter`（fixtures） |
| `AttestationSink` | `OnChainAttestationSink` —— ABI 编码 `validationResponse`、签 EIP-1559 交易、广播到 ERC-8004 registry。以 `EIV_VALIDATION_REGISTRY_ADDRESS` + `ATTESTER_PRIVATE_KEY` 启用；`EIV_ATTEST_DRY_RUN=1` 只签不播。 | `StubAttestationSink` |

替换实现不需改动编排服务、API 或验证引擎；组装由环境变量驱动（见 `.env.example`）。

未签名的 intent 默认接受，但 record 会带 `auth.verified = false`，下游永远分得出
「密码学验证过的授权」和「口头声称的授权」。`EIV_REQUIRE_SIGNATURE=1` 则直接拒绝。

### 与 registry 合约的 ABI 对齐

合约接口：
`validationResponse(bytes32 requestHash, bytes response, string responseURI, bytes32 responseHash, string tag)`

| 合约字段 | 实现 |
|---|---|
| `requestHash` | intent 的 EIP-712 typed-data digest（授权者签的那个值） |
| `response` | 单一 byte 分数：`100`（PASS）/ `0`（FAIL） |
| `responseURI` | `EIV_RESPONSE_URI_BASE` + requestHash（未设置时为空） |
| `responseHash` | canonical result JSON 的 keccak-256（承诺到完整违规集合） |
| `tag` | `EIV.L2.{verdict}`（如 `EIV.L2.PASS`）—— 与合约一致 |

### Sepolia 实链记录

这条路径不是纸上谈兵，已在 Sepolia 端到端跑通：

| | |
|---|---|
| `EIVValidationRegistry`（ERC-8004 ValidationRegistry） | [`0x6719c69829740232f652b4b6bad8e6850922a2fb`](https://sepolia.etherscan.io/address/0x6719c69829740232f652b4b6bad8e6850922a2fb) |
| 第一笔真实 attestation（`OnChainAttestationSink`） | [`0xbc50b963d8f9c9f5f34ba7764f510e0f6cddf4d67a4b927584170bdac40ec6f0`](https://sepolia.etherscan.io/tx/0xbc50b963d8f9c9f5f34ba7764f510e0f6cddf4d67a4b927584170bdac40ec6f0)（block 11041392，145,626 gas，已发出 `ValidationResponse` event） |

attest 上链的 `requestHash` 就是 intent 的 EIP-712 digest
`0xe218a34c8204b392b0455de31668d208aef8549a039af6076654fd033ac76748`；链上
`hasValidation(requestHash)` 返回 true，tag 为 `EIV.L2.PASS`。合约部署和
attestation 交易都由 eiv-core 的零依赖 stdlib 密码学栈（`eiv/eth.py`）签署
—— attestation 路径全程没有 Hardhat 或 web3.py。

## 项目结构

```
eiv-core/
├── eiv/
│   ├── predicates.py       # 确定性验证引擎（规则来源）
│   ├── schema.py           # JSON <-> dataclass、金额解析、content hash
│   ├── eth.py              # stdlib 密码学：keccak、secp256k1、RLP、ABI、EIP-1559、JSON-RPC
│   ├── eip712.py           # IntentSpec typed-data digest、签署、验证
│   ├── intent_source.py    # IntentSource 与 EIP712Verifier 接口
│   ├── chain_adapter.py    # MockChainAdapter + RpcChainAdapter（实时 JSON-RPC）
│   ├── attestation.py      # StubAttestationSink + OnChainAttestationSink（ERC-8004）
│   ├── service.py          # ValidatorService 编排（run + gate）
│   ├── store.py            # ValidationStore（JSON）+ SqliteValidationStore（WAL、索引查询）
│   ├── reputation.py       # 验证历史 -> 信任档案聚合
│   ├── sdk.py              # Python SDK：EivClient / EivEmbed / AsyncEivClient + hooks
│   ├── glm.py              # GLM-5.1 client + 白话->IntentSpec + agent 提案（demo 层）
│   ├── agent_loop.py       # 长程 GLM-5.1 loop，每个 action 都过 EIV gate
│   ├── api.py              # HTTP API + console（标准库）
│   ├── static/index.html   # EIV console（零依赖 web UI）
│   ├── demo.py             # 端到端 demo
│   ├── selftest.py         # 自动化测试（含公开密码学向量）
│   ├── mcp_tool.py         # MCP 工具（可选）
│   └── fixtures/           # 已签名示例 intent、execution traces、scenarios
├── contracts/              # ERC-8004 ValidationRegistry（Solidity）+ stdlib 部署工具
├── docs/                   # 设计文档
├── pyproject.toml
├── .env.example
└── LICENSE
```

## 许可

MIT License —— 见 [LICENSE](LICENSE)。

## 团队

AI × Web3 Agentic Builders Hackathon · Z.AI 赛道。
