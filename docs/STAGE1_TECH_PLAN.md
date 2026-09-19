# Stage 1 Tech Plan: Symbolic Seed Augmentation

本计划依据 `output/pdf/symbolic-seed-proposal.md`，按工作内容、验收标准和产出组织。实现与测试证据记录在 [Stage 1 验收记录](STAGE1_VALIDATION.md)，使用入口见 [README](../README.md)。

## Stage 1 Goal

在仓库内两个自行编写的无害状态机 fixture 上，完成可重复的可达性集成验证：

**Medusa 生成并执行调用序列 → 自动选择具体前缀 → Halmos 重放前缀并求解下一步参数 → 新部署具体重放 → 回灌 Medusa → 确认实际执行和进入 mutation 候选。**

开发者提供部署、合法操作、目标谓词和有限状态观测；工具负责转换、选择、测试生成、求解、验证、回灌和证据记录。第二个 fixture 只能新增配置及 Solidity 适配代码，不得在编排器中硬编码其调用顺序或目标解。

到达目标状态不等于发现安全漏洞。本阶段验证接口正确性与可复用性，不承诺发现真实漏洞或优于原生 Medusa。

**最终产出：**

- Python 编排 CLI：`seedbridge doctor`、`seedbridge run <scenario>`、`seedbridge report <run-id>`。
- 固定版本的薄 Go Medusa 适配器：原生语料 codec、执行观察和批次回灌。
- 两个无害 fixture：`PhaseCounter`、`BoundedLedger`，以及配置、观测接口和具体测试。
- 每个 fixture 的原生语料、自动生成 harness、求解原始结果、具体重放测试和 Medusa 回灌证据。
- 可复现的 JSON / Markdown 报告、单元及集成测试、环境锁定文件和 README。

## 支持范围与公共约束

| 项目 | Stage 1 范围 |
| --- | --- |
| 目标 | 仅仓库自建 fixture；每个场景一个目标合约、固定部署配方和固定 actor |
| 序列 | 1–3 个成功的具体调用，随后一个只有单个 `uint256` 参数的符号调用 |
| 执行 | `msg.value = 0`；一轮批次回灌；一个 worker；固定随机种子 |
| 状态 | 开发者提供有限 getter 和目标谓词，比较声明的状态投影 |
| 排除项 | 第三方目标、真实资金、主网分叉、代理升级、动态部署、复杂回调、密码学条件、原始 storage 迁移 |
| 语义限制 | fixture 不依赖时间、gas、自身地址、transaction nonce、transient storage 或复杂跨交易副作用 |
| 资源配置 | 配置并记录单查询 timeout、子进程 timeout、累计求解预算和前缀数量上限；不在本文指定具体秒数 |

Python 负责编排，不模拟 EVM、不实现求解器、不手写猜测 Medusa 原生 JSON。Go 适配器使用固定 release 的 API，不修改 Medusa 的覆盖反馈和 mutation 核心。[1]

为复现集成流程，warmup 使用公开 hook 固定 worker 随机源、排序方法列表，并选用 Medusa 原生 random/new-sequence-only 策略。该配置不等于 stock Medusa 的性能基线。前缀来自真实执行的原生序列快照；Medusa 自己按覆盖反馈保存的 corpus 另外保留，两种来源明确标注。

## S0：环境与项目骨架

**做什么**

- 建立 Python 3.12 独立环境、uv 锁文件、Go module 和本地版本管理，保留现有材料。
- 安装并固定 Medusa，核实 Medusa → crytic-compile → Foundry 编译路径，以及 Halmos 所需的 Foundry AST、storage layout 等产物。[7]
- 固定 solc、optimizer、EVM target、solver 路径；采用 Shanghai，清理子进程的环境覆盖，并保存实际解析后的编译配置。
- 使用一个最小无害 smoke fixture 检查工具组合，并保存实际命令、版本、commit、二进制及构建摘要。

工具链约定如下；版本检查不能代替后续集成验收：[1][2][5]

| 组件 | 固定配置 |
| --- | --- |
| 主机 | macOS / arm64，优先原生运行 |
| Python | 项目独立环境使用 3.12 |
| Go | 1.26.4 |
| Forge | 1.3.2，commit `c4245d663339cdfdf478a4a17588c8fc0528e896` |
| solc / crytic-compile | 0.8.36 / 0.3.11 |
| Halmos / Z3 | 0.3.3 / 4.12.6，由 uv 锁定；不使用原全局 Z3 4.13.0 |
| Medusa | 固定 v1.5.1 Go module，构建为本地适配器；无需全局 Medusa CLI |

**怎么验收**

- Medusa、Forge、Halmos 均能编译并运行同一 smoke fixture。
- 保存两侧实际编译命令；目标 ABI 和字节码一致。若存在 metadata 等差异，说明并验证比较规则，不直接忽略。
- solver 使用显式路径，运行期间不隐式下载依赖；缺失或不兼容组件由 `doctor` 明确报告。

**最终产出**

`pyproject.toml`、`uv.lock`、`adapters/medusa/go.mod` 与锁定依赖、`configs/toolchain.*`、`seedbridge doctor`、smoke run 记录。

## S1：两个 fixture 与公共配置

**做什么**

- 实现 `PhaseCounter`：具体调用建立 phase / counter 状态，下一步参数使无害目标成立。
- 实现 `BoundedLedger`：以不同记账状态验证适配器复用，目标可达性与记账不变量分别表达。
- 定义 `ScenarioSpec`：schema / fixture ID、源码与构建摘要、部署配方、逻辑合约与 actor 绑定、初始化上下文、允许调用、目标调用、符号参数类型及范围、`goal_id`、`observe_id`、执行和求解预算。

**怎么验收**

- 两个 fixture 的普通具体测试通过，观测 getter 能表达预期状态。
- 每个 fixture 至少存在一个目标尚未成立的有效前缀，以及一次能使目标成立的合法后续调用。
- 目标条件与安全不变量使用不同函数和结果字段；不把两者混为一谈。

**最终产出**

`fixtures/phase_counter/`、`fixtures/bounded_ledger/`、`src/seedbridge/config.py` 中的内置场景配置、每次运行的 `scenario.json`、fixture 具体测试。

## S2：Medusa 原生语料与无干扰观察

**做什么**

- 实现 Go 适配器入口 `run-observed`、`roundtrip`、`decode-corpus`、`encode-candidate`，使用原生 `CallSequence` / `CallMessage` codec。[3]
- 通过真实 `Fuzzer.Start()` 的 `CallSequenceTestFuncs` hook 记录逐步调用结果和有限 getter 观测；语料本身不提供这些状态记录。[4]
- 观察调用使用独立执行／tracer，并明确快照回滚边界。读取、写入 calldata 时同步处理 ABI metadata。
- 在引入 Halmos 前，先证明原生语料自身能 decode → encode → restart。

**怎么验收**

- 同一原生序列往返后，actor、逻辑目标、calldata、value、区块／时间上下文及逐步 outcome / 观测一致。
- 开启／关闭 getter 观察的对照不改变持久状态、后续执行结果、覆盖反馈或 corpus admission；两组都保留 receipt、状态根和 coverage 仪表。比较原生覆盖 marker/count 的摘要，不能只比较分支数量或凭 getter 标为 `view` 判定无干扰。
- 明确如何观察序列完成后的 mutation admission；公开 API 无法确认时报告 `admission_unverified`，先解决此接口问题再进入后续步骤。

**最终产出**

`adapters/medusa/`、原生 corpus 往返测试、逐步执行记录、observer 对照结果、admission 观测方式与证据样例。

admission 使用固定 v1.5.1 的源码控制流与 `CallSequenceTested` 完成事件作为证据，并检查输入 hash、完整步数、无取消和无 shrink。它证明该版本执行了加入 chooser 的路径，不代表观察到后续实际选中该 seed 做 mutation。

## S3：前缀协议、选择与 Harness 生成

**做什么**

- 定义 `PrefixCase`：来源 corpus 与 ScenarioSpec 摘要；逐步逻辑目标、actor、ABI 签名、typed arguments、raw calldata、value；实际 block number / timestamp、outcome、状态观测和部署地址映射。
- 过滤不支持、含 revert 或末尾 `goal == true` 的前缀，再去重，按短序列与稳定 ID 排序。不得删掉失败调用后假称仍为原始前缀。
- 使用同一部署配方生成临时 Foundry / Halmos harness，具体重放所选前缀，逐步检查身份、outcome 与状态投影。
- uint256 在 JSON 中使用字符串；地址以逻辑 ID 绑定。不能按未知含义替换 calldata 字节，也不能把 delay 为零直接解释为区块和时间不变。

**怎么验收**

- 前缀来自 Medusa 实际生成并执行的语料，可通过摘要追溯。
- 生成 harness 后，两个执行器的逐步状态投影、调用身份和结果匹配；这不代表完整世界状态等价。
- 修改前缀参数造成状态不同、缺少前置步骤、目标已成立或原生地址无法绑定时，明确拒绝或报告不匹配，不进入目标求解。

**最终产出**

`src/seedbridge/trace.py`（协议与选择）、`harness.py`（内置 Solidity 模板）、规范化前缀文件、自动生成 harness 和前缀重放报告。

## S4：Halmos 单步求解与结果解析

**做什么**

- 前缀检查独立通过后，生成专用目标测试：保持前缀具体，仅最后一步的一个 `uint256` 参数符号化，以目标谓词的否定作为专用断言请求 witness。
- 按本地 Halmos 0.3.3 的实际 JSON 实现解析，固定 contract / test 签名，不使用 minimal JSON。[5]
- 定义 `Candidate`：来源 PrefixCase、目标测试及调用签名、参数名／类型／值、原始结果路径。
- 验证模型的 `is_valid`、变量映射、类型和范围；不硬编码内部随机后缀。分别控制 solver 与子进程 timeout，并清理所创建的超时子进程组。

**怎么验收**

- 保存真实运行 JSON 为解析测试样本；只接受来自指定目标测试的有效模型。
- 前缀断言失败、其他测试的模型、缺失变量、类型错误或歧义均被拒绝；大整数无精度损失。
- PASS 或未获得模型不得解释为目标不可达；保存路径截断 warning、界限及未完成原因。
- 运行器能区分以下结果，不沿用旧 run 的文件：

| 情况 | 状态 |
| --- | --- |
| 编译／启动失败、结果缺失或损坏 | `tool_error` |
| 测试数量或签名不匹配 | `result_mismatch` |
| 求解或子进程达到限时 | `timeout` |
| 全部路径回滚／执行卡住 | `all_paths_reverted` / `stuck` |
| 界限内未获得模型 | `no_witness_within_bounds` |
| 模型无效或参数不符合协议 | `invalid_model` |
| 有效且可解析的目标模型 | `candidate` |

编译目标、原生状态或 observer 对照证据与基线不一致时，分别使用 `state_mismatch` / `observer_mismatch`，不得归入 `tool_error`。

**最终产出**

`src/seedbridge/halmos.py`、typed candidate 文件、版本化结果解析器、真实输出样本、超时与错误分类测试。

## S5：具体重放与 Medusa 回灌

**做什么**

- 在新部署上具体重放完整候选，核对前缀观测、参数范围和目标从 false 到 true 的变化。
- 对完整序列去重；通过原生 codec 写入新目录的 `call_sequences/`，同步更新 calldata 和 ABI metadata。[3]
- 将候选 Medusa hash、全部 warmup hash 和比较结果保存为独立 `novelty.json`，报告中引用该证据，不能只依赖未走 duplicate 分支来推断新颖性。
- 重启单 worker Medusa，记录实际执行、目标结果，以及完整序列结束后的 mutation admission。[4]

**怎么验收**

- 只有具体重放匹配且目标成立的候选标记为 `reachable_confirmed`；不匹配标记为 `replay_mismatch` / `candidate_rejected`。具体重放和每次 Medusa restart 都重新核对基线源码／字节码摘要；最后一步实际上下文也必须匹配。
- 具体重放的进程限时、不可读输出、测试身份／数量不符和断言不匹配分别记录为 `timeout`、`tool_error`、`result_mismatch` 和 `replay_mismatch`；外层工具限时不得折叠成普通工具错误。
- 重复序列记录为 duplicate，不计为新增种子；错误目标、未执行或上下文不同的导入不能通过。
- 分别提供 `exported`、`replayed_by_medusa`、`admitted_for_mutation` 的证据。文件产生或执行成功均不能单独证明 admission。
- 不在最后一步 hook 中立即结束 worker：v1.5.1 的 admission 处理发生在完整序列完成后。无法证明时保留 `admission_unverified`，不得计为阶段完成。

**最终产出**

`src/seedbridge/replay.py`、`pipeline.py`、具体重放测试、`novelty.json`、候选原生 seed、Medusa restart 日志、执行与 admission 证据。

## S6：完整 CLI、验收与复现文档

**做什么**

- 接通 `seedbridge doctor`、`seedbridge run <scenario>`、`seedbridge report <run-id>`。
- 定义 `RunRecord` 并生成 JSON / Markdown 报告：toolchain、源码与构建摘要、随机种子、prefix 来源、模型来源、重放与目标结果、Medusa 执行／admission、逐阶段耗时、失败原因和产物路径。
- 每次运行使用新目录，保留原始结果与摘要；完成单元测试、两个 fixture 的集成测试和 README。

**怎么验收**

- 按 README 从干净配置运行两个 fixture，各产生至少一个非重复的有效目标模型，并通过新部署具体重放、Medusa 实际执行及 mutation admission 验证。
- 第二个 fixture 只增加配置及 Solidity 适配代码，核心引擎没有目标特例。
- 负向检查覆盖缺少前置步骤、状态不匹配、目标已成立、无效／错误来源模型、超时／缺失结果、大整数、重复 seed、错误目标及导入未执行。
- 报告能区分未找到、工具失败、目标可达和独立性质结果；CLI 返回 0 或报告文件存在不单独构成通过。
- 覆盖率和耗时仅作为运行记录，不据此声称算法优于基线。

**最终产出**

```text
README.md
pyproject.toml / uv.lock
configs/                 场景、构建、预算和工具版本
src/seedbridge/           Python CLI、编排与报告
adapters/medusa/          固定版本 Go codec / observer
fixtures/phase_counter/
fixtures/bounded_ledger/
tests/unit/
tests/integration/
runs/<run-id>/           原生语料、前缀、harness、模型、重放、日志和报告
```

执行顺序为 S0 → S1 → S2 → S3 → S4 → S5 → S6。S2 的原生往返或 admission 观察未通过前，先解决接口问题，不开展前缀评分和性能对比。Stage 1 的最终结论限于这两个自建 fixture 的可达性集成验证。

## 核查来源

1. [Medusa v1.5.1 release](https://github.com/crytic/medusa/releases/tag/v1.5.1) 与 [Medusa 官方说明](https://github.com/crytic/medusa)：候选版本与已有 fuzzing 能力。
2. 本机 `forge --version`、`solc --version`、`halmos --version`、`halmos --help`、`go version`、`z3 --version` 的既有核查：仅说明环境起点，未证明跨工具集成。
3. Medusa v1.5.1 [CallSequence](https://github.com/crytic/medusa/blob/v1.5.1/fuzzing/calls/call_sequence.go)、[CallMessage](https://github.com/crytic/medusa/blob/v1.5.1/fuzzing/calls/call_message.go)、[Corpus](https://github.com/crytic/medusa/blob/v1.5.1/fuzzing/corpus/corpus.go)：原生格式和导入约定。
4. Medusa v1.5.1 [Fuzzer](https://github.com/crytic/medusa/blob/v1.5.1/fuzzing/fuzzer.go)、[Worker](https://github.com/crytic/medusa/blob/v1.5.1/fuzzing/fuzzer_worker.go)、[TestChain](https://github.com/crytic/medusa/blob/v1.5.1/chain/test_chain.go)、[序列执行](https://github.com/crytic/medusa/blob/v1.5.1/fuzzing/calls/call_sequence_execution.go)：观察、重放与 admission 路径，待集成验证。
5. 项目锁定环境 `.venv/lib/python3.12/site-packages/halmos/` 中的 `__main__.py`、`solve.py`、`calldata.py`、`cheatcodes.py`，以及 [release 源码](https://github.com/a16z/halmos/blob/v0.3.3/src/halmos/__main__.py)：结果结构来自实现核查，S4 补实际运行样本。
6. [Optik](https://github.com/crytic/optik)：已有符号执行辅助 fuzzing 的相关工作；本阶段定位为工具扩展与集成验证。
7. [Medusa compilation 配置](https://secure-contracts.com/program-analysis/medusa/docs/src/project_configuration/compilation_config.html)：crytic-compile 编译桥接；兼容性在 S0 验证。
