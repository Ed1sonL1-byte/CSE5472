# Stage 2 Tech Plan: Continued Fuzzing and Controlled Evaluation

**负责人：Edison Li。状态：完成；P0–P5 与最终验收均有保存证据。**

本计划承接 [Stage 1 验收记录](STAGE1_VALIDATION.md)。Stage 1 基线提交为 **4bf442f**（Complete SeedBridge Stage 1）；规划时工作区干净。这里不安排开发日程或估时，只规定工作、验收与产出。实验运行限额属于测量协议，必须在执行前写入配置。

### 实施状态

| 工作包 | 状态 | 当前证据 |
| --- | --- | --- |
| P0 campaign 数据与预算协议 | 完成 | `src/seedbridge/budget.py`、`campaign.py`；成功、合法未命中、工具错误、证据错误和截止时间分开落盘 |
| P1 native continuation 与 lineage | 完成 | 300 序列机制运行：207 mutation，导入 seed 被选 110 次，85 个不同子代实际执行；记录开关对照一致 |
| P2 两个新增场景 | 完成 | 两个具体测试套件各 4 项通过；两个新场景均通过完整 Stage 1 核心流程 |
| P3 独立新颖性指标 | 完成 | 原生 marker 集合/次数、有限状态投影、规范化序列身份及分段差集已实现并测试 |
| P4 三组公平执行 | 完成 | 同 warmup 三组 smoke 均有效；增强成本计入总预算，超时后仍完成 native continuation |
| P5 正式实验与报告 | 完成 | `stage2-formal-02` 的 60/60 结果有效；60 份 metrics 从原始事件重算一致；报告重复生成哈希不变；小型证据包含校验和 |

逐项命令、结果和可分享证据索引维护在 [Stage 2 验收记录](STAGE2_VALIDATION.md)。

## 1. 本阶段目标

**让经过验证的符号种子真正参与后续 Medusa mutation，并在相同总运行预算内，测量它对本地教学状态机探索的影响。**

回答三个问题：

1. 导入种子是否被实际选中，是否生成并执行了不同的后续序列？
2. 导入及后续探索各自增加了哪些状态和覆盖？
3. 加上编译、求解、重放、重启的成本后，符号增强与两个对照相比表现如何？

验收要求机制正确、实验公平、证据完整；**收益为零或负值也可以是有效结果**。本阶段测量可达性和探索，不把目标命中报告为漏洞发现，也不把四个教学场景的结果推广到真实合约。

## 2. 从现有实现出发

| 已核查的现状 | Stage 2 必须处理的差距 |
| --- | --- |
| 两个 fixture 已通过 solve → replay → reseed → admission | admission 尚未证明 seed 被选中或产生子代 |
| observed.go 要求导入数等于执行数，导入完成即停止 | 新增独立的 campaign 模式，区分启动重放和后续生成 |
| Stage 1 强制 NewSequenceProbability=1，使用 RandomValueGenerator | 比较实验恢复 pinned Medusa 的默认生成与 mutation 策略 |
| coverage.go 已枚举 native marker，但只输出数量与摘要 | 保存 marker 集合，计算真实并集与差集 |
| trace.py 将 ready 条件固定为 observe[0] == 2 | 将 readiness 与前缀长度限制移入受验证的场景配置 |
| 两个现有场景都是狭窄整数条件，goal 后没有新行为 | 增加容易命中的对照和 goal 后仍有行为的场景 |
| 某些异常路径没有记录对应阶段耗时 | 用统一计时器在成功、失败、超时路径均落盘 |

本地 Medusa v1.5.1 源码还确认：公开 hook 足够恢复默认 generator/mutator，但没有直接记录父代选择的事件；corpus chooser、mutation strategy chooser 各有内部随机源。设置 worker seed 不等于整个 campaign 完全确定。

## 3. 固定范围

| 项目 | 本阶段约束 |
| --- | --- |
| 场景 | 共四个仓库自建的无害教学状态机，保留原有两个 |
| 接口 | 每个场景一个本地合约；固定 actor/deployer；零金额；无外部调用 |
| 符号输入 | 一个 uint256；具体前缀 1–3 步；一次增强批次 |
| campaign | 单 worker；每个完整序列最多 4 步；不在 goal 命中时停止整场实验 |
| 前缀策略 | 沿用稳定的短序列优先策略，每批最多 4 个；本阶段不做自适应评分 |
| 新种子 | 每个前缀最多接纳 1 个，全批最多 4 个；按固定顺序处理 |
| 比较规模 | 4 fixtures × 5 个重复编号 × 3 arms = 60 个主实验结果槽位 |
| 不扩展 | 任意第三方目标、真实资产或链上连接、多 actor、复杂 ABI、多步符号执行、多轮调度、分布式执行、GUI |

保留 Stage 1 的集成模式和原有验收语义。Stage 2 的新行为通过独立配置与命令入口启用，不能静默改变旧报告的含义。

## 4. 工作包与验收

### P0：建立 campaign 数据与预算协议

**做什么**

- 新增版本化 CampaignSpec、CampaignRecord，记录场景、构建、策略、语料来源、预算、重复编号、随机源控制范围和阶段结果。
- 定义顺序阶段：公共构建与 warmup → 前缀选择 → 可选增强及验证 → native startup replay → continuation → 汇总。
- 将计时改为 finally 落盘；阶段不可重叠累计。区分运行 wall time、子进程资源用量和报告生成时间。
- 独立记录 execution_status、goal_reached、augmentation_status、lineage_status、evaluation_valid。未命中目标不能自动等同工具故障。
- 给每个进程传递剩余预算，超时清理所属进程树。若平台无法完整采集子进程 CPU 用量，明确标记不可用，不以父进程 CPU 代替。

**怎么验收**

- 成功、无候选、模型失败、求解超时、具体重放失败和 campaign 截止均有阶段记录和原因。
- 预算测试证明增强阶段不能占用未记账的时间；报告可以从记录重算累计成本。
- 原有 Stage 1 单元及原生集成检查仍通过；不预设修改后的测试总数。

**产出**：campaign schema/config、共用计时与预算组件、错误分类和计时测试。

### P1：恢复 continuation，并证明真实父子关系

**做什么**

- 新增 Go adapter 的 campaign 模式。完整重放导入语料后继续运行 native fuzzer，分别记录 startup_replays、new_sequences、mutation_sequences。
- 保留 Medusa v1.5.1 默认的生成概率、值生成器、mutator 与策略权重；固定的单 worker、调用长度、actor、环境和测试观察配置由三个 arm 共同使用。有效配置全部导出。
- 先核实公开 API 能观察到什么。当前版本缺少可靠 lineage hook，因此把一个**固定版本的最小记录补丁**作为前置可行性工作：只记录真实生成事件，不实现新 mutation 算法、不改变选择权重。
- 事件至少关联 generation_id、生成策略、实际父代 hash 列表、生成结果 hash 与实际执行结果。拼接类策略可能有多个父代，不能强行只留一个。
- 补丁须可复现地应用到项目内的固定版本副本，保存上游版本、补丁摘要及构建来源；不能修改全局 Go module cache。三个 arm 使用相同构建与记录开关。
- 区分 seed 的 imported、replayed、admitted、selected_as_parent、different_child_generated、child_executed。只有 calldata 或调用结构改变才算非平凡 mutation；nonce 或时间记录变化不算。

**怎么验收**

- 在一个受控的仓库 fixture 机制测试中，真实完成：符号 seed 导入 → 实际父代选择事件 → 不同子代 → 子代执行记录。不得用手写子代替代 native mutation。
- 即使目录里只有一条 seed，也必须提供选择事件；startup replay 的中间前缀可能另行进入 corpus，单 seed 目录不是来源证明。
- 记录开关不改变给定具体输入的结果、状态与覆盖；检查记录路径不调用 RNG、不改输入。正式实验统一开启记录，并计入成本。
- 若记录补丁无法提供可靠证据，输出 lineage_unverified 与具体阻塞原因，不能宣布这一工作包通过或虚构父子关系。

**产出**：native campaign mode、版本固定的记录补丁及说明、lineage.jsonl、机制验收记录。

**随机性边界**：本阶段不以整个 fuzzing 轨迹逐位确定为完成条件。固定公开可控的 seed、导入顺序和方法顺序，列出内部未控制的随机源；五个编号是五次重复，不声称各 arm 消耗相同随机流。实际语料、事件与重放输入必须保存。完整 RNG 注入及所有无序集合规范化不列为必需扩展。

### P2：新增两个场景，避免单一评估

| 场景 | 角色 | 具体要求 |
| --- | --- | --- |
| phase_counter | 已有集成回归 | 源码及原 Stage 1 行为保持兼容 |
| bounded_ledger | 已有集成回归 | 独立不变量与目标标志继续分开 |
| range_gate（新增） | 容易探索的对照 | 使用宽松范围条件，普通边界输入即可到达目标；用于观察求解开销是否抵消收益 |
| workflow_gate（新增） | 非终止目标与结构变化 | 通过两步具体操作建立有限状态，再经过一个分段整数条件；goal 成立后还有一步可执行操作，进入其他有限状态和分支 |

**做什么**

- 新场景继续采用三个有界整数加一个 goal 布尔值的观测接口，不引入资产、外部依赖或漏洞载荷。
- 将 ready_predicate、允许的前缀长度、有限状态投影及 goal 定义纳入内置场景配置并校验。编排器不得按 fixture ID 写目标解或调用顺序特例。
- workflow_gate 用最多两步的增强前缀，使“前缀 + 符号调用 + 后续操作”能落在 4 步范围内；goal 可保持为真，后续状态仍允许变化。
- 完成普通具体测试后冻结四个场景与策略。workflow_gate 不用于根据比较结果调参，但不将自建已知源码称为盲测或第三方 benchmark。

**怎么验收**

- 四个场景都有明确的合法路径、有限观测域、ready 条件、目标与独立不变量。
- range_gate 的具体测试证明普通边界输入有效；workflow_gate 的具体测试证明 goal 后确有额外可达状态及覆盖。具体测试路径仅作 fixture 正确性检查，不注入正式 warmup。
- 新场景经过同一 codec、harness、重放和 campaign 路径，核心代码没有场景专用解。

**产出**：两套 fixture、场景配置及具体测试、docs/STAGE2_BENCHMARKS.md。

### P3：定义可核查的探索指标

**做什么**

- 保存 native marker 集合，元素使用 (runtime_bytecode_sha256, marker_hex)；另存命中次数。覆盖集合限同一目标 runtime，排除 harness/getter 的附加执行。
- 保留已有 marker 枚举数量与 native BranchesHit() 的一致性检查；集合导出失败不能用摘要代替。
- 状态新颖性使用预先声明的有限投影，不使用包含 nonce 的全局状态根，也不让任意原始输入自动制造一个新状态。
- 全序列去重覆盖 warmup 实际执行快照及本轮已接受候选；将序列 hash、状态 hash、覆盖集合分别保存。
- 记录首次目标命中的实际阶段和时间，同时记录由 mutation 子代带来的状态或覆盖；后者必须有 P1 的来源证据。
- 主表的状态/覆盖指标只统计 native warmup、import 和 continuation。B/C 的辅助候选检查另记为 auxiliary validation，不混入 native 覆盖集合；其具体目标命中和运行成本仍须记录。

**怎么验收**

- 对小型人工集合验证 union/difference，并用真实 native 重放检查稳定 marker 身份。
- 同一个 seed 多次重放不增加 unique coverage/state；命中次数变化不能被算成新覆盖。
- 下列指标必须能从原始事件独立重算：

| 指标 | 定义 |
| --- | --- |
| 新序列 | 规范化完整调用身份此前不存在；不等同新状态 |
| 新状态 | 固定投影下此前不存在的状态；仅在同一 fixture 内比较 |
| 总覆盖增量 | warmup、import、continuation 的覆盖并集，减去 warmup 集合 |
| continuation 覆盖增量 | continuation 集合减去 warmup 与 import 的并集 |
| seed 使用情况 | 各导入 seed 被选中、产生不同子代、子代被执行的次数 |
| goal 命中 | 独立具体观察为真；与 invariant 结果分列 |

状态增量采用同样的分段集合计算。导入本身的收益与后续探索收益必须分别展示；若要归因到某个 seed 的子代，再按 lineage 事件过滤，不能将所有 continuation 收益都归因给增强。

**产出**：coverage.json、states.json、分段指标与重算测试。

### P4：实现三个策略和公平预算

三个 arm 使用同一 campaign 引擎、目标信息、观测、构建和资源配置：

| Arm | 增强行为 | 继续运行 |
| --- | --- | --- |
| A：native_resume | 不生成额外候选 | 默认 Medusa 生成与 mutation 策略 |
| B：concrete_augment | 对共同前缀尝试固定 boundary/random 混合输入 | 同一策略 |
| C：symbolic_augment | 对共同前缀用 Halmos 求解一个 uint256 | 同一策略 |

**B/C 的共同规则**

- 使用同一份冻结的、最多 4 个具体前缀及相同顺序。每个前缀最多导出一个满足相同 goal 的有效种子，全批最多 4 个。
- B 的通用边界字典及随机抽样规则预先写入配置；默认每个前缀最多 64 次具体尝试。不得读取 C 的模型、从目标公式手算答案或在看到结果后调整字典。
- B 使用一次编译后可重复新部署的具体执行路径；不为了每个普通输入重新编译整个工程。候选的最终身份、状态、goal、invariant 和 native 回灌检查与 C 相同。
- C 对每个前缀最多进行一次有界目标求解，前置检查与编译均计入成本。超时或模型无效后按剩余预算处理下一个前缀或进入 continuation。
- 两组均对重复候选和失败候选留证。匹配前缀机会与导出上限，不事后匹配成功数量，不为落后 arm 额外补抽。
- 排除自身 goal 已成立的 prefix；没有合格 prefix 时记录原因并直接继续 fuzzing，不能挑选新的重复 seed 代替该次运行。
- warmup 在其他序列中已经命中 goal，不触发全局取消增强：只要还有合格的 goal=false 前缀，B/C 仍按同一固定策略处理。这样容易命中的场景仍能检验额外求解是否值得。报告单列 warmup 已命中情况；全局 goal 早停优化不属于本阶段策略。

**总预算规则**

公共构建与 warmup 成本为 T_common。每个 arm 从同一个总预算 B_total 中扣除该成本；余下成本包括前缀处理、编译、增强、全部具体检查、进程启动、import replay 和 continuation。

**计费总成本 = 公共成本 + 前缀处理 + 增强及验证 + 启动及导入 + continuation。**

- 所有阶段遵守一个外层截止；增强另有限额，不能把全部剩余预算预留给 solver。完成较快的 arm 获得更多 continuation 时间。
- 公共构建与 warmup 也有独立上限；配置必须为启动、导入和 continuation 留出预算。意外耗尽预算时记录实际停止阶段，不能为了补足执行量越过总截止。
- wall-clock 是主预算。单 worker、单并发 solver；arm 顺序执行，记录 host、线程配置、资源用量及无法保证的隔离限制。不把普通本机运行写成严格 CPU 隔离。
- B_total、warmup 序列上限、增强限额、单查询限额及停止/清理容差在正式运行前冻结。本文不指定秒数，由 smoke run 校准可执行配置；校准只检查可运行性，不能按收益挑预算。
- 编译缓存采用固定协议：每个重复先使用隔离目录产生共同构建及 warmup；各 arm 从同一缓存副本开始。新增 harness、重编译、重启等成本计入所属 arm。禁止 arm 间共享新增生成产物。
- 报告生成和离线分析放在计量外；运行时事件记录必须计量。记录停止和清理尾差，不能隐藏启动或日志开销。
- 停止与清理期间到达的结果仍须保存，但只有实际执行完成时累计计费时间不超过 B_total 的事件进入主指标。保存事件时间与阶段时间基准；截止后结果标记 after_deadline，不将清理尾差变成额外探索时间。

**怎么验收**

- 使用受控预算测试确认 B/C 不获得“免费求解/验证”；超时后仍能在剩余预算内继续 native fuzzing。
- 每次接受、拒绝、去重及未尝试都有原因、输入来源和成本记录。
- 能用同一 fixture 完成三组 smoke run，且 configuration diff 只包含明确允许的策略差异。

**产出**：三个 arm 的编排实现、具体增强器、冻结的 configs/stage2-benchmark.json、预算及公平性测试。

### P5：运行主实验并交付可复核结果

**共同 warmup 协议**

1. 对每个 (fixture, repeat_id) 执行一次默认策略 warmup，共 20 份。保存实际 native corpus、完整执行快照、前缀池、状态/覆盖集合、构建和实际成本。
2. 原生持久化 corpus 与“所有已执行前缀快照”分开保存；前者用于共同启动语料，后者用于前缀选择与去重，不能混称 native coverage corpus。
3. 三个 arm 从同一语料与缓存副本重新启动，B/C 额外加入验证后的种子。共同语料保持相同导入顺序，新增种子的导入顺序预先固定。
4. 公共部分物理上只运行一次，但其实际成本分别计入 A/B/C。记录逻辑计费成本和整个实验的实际支出，不能重复相加后冒充机器实际运行时长。
5. 使用重复编号 1–5，并按预先生成的顺序轮换三个 arm；不得同时争抢本机资源。保留所有 60 个结果槽位和重试历史。

**基线名称与推论边界**

A 是“从共同 warmup 语料重启的 Medusa 默认策略对照”。语料重启不是保存整个进程、RNG 或 EVM 内存状态，因此不能称作精确 checkpoint 恢复；这也不是不中断运行的 unmodified Medusa。

本阶段主实验用于隔离增强的影响。另可在一个固定 fixture 上做不中断 native 运行的诊断，记录重启代价；它不是必需的第四组，也不足以替代完整的 unmodified-Medusa 性能比较。原 proposal 的更广泛最终评估仍未在 Stage 2 完成。

**失败与统计规则**

- 每个 fixture 分别报告三组的 goal 命中次数 /5、全部重复的状态/覆盖增量、种子有效率及使用率、编译/求解/验证/重启/continuation 成本。
- 第一次命中时间包括已计量的公共构建与 warmup。warmup 已命中时保留原始事件时间；B 的具体尝试命中也须记录，C 的符号模型本身不算具体命中。另列首次 native 命中，避免混淆执行器。
- 搜索在实际观察结束时仍未命中属于右截尾，截尾时间记录该 arm 的实际计费观察结束时间；总预算上限另列，不能拿预算上限替代提前结束的观察时间。展示所有运行的 hit 曲线或逐次数据，不能只平均成功运行的时间。
- 求解超时、没有合格 prefix、未找到模型是有效策略结果。构建错误、证据缺失、执行语义不一致属于独立工具/完整性错误；不能当正常未命中混入统计。
- 一个组的结果无效时，保留该条记录并明确比较不完整；修复后以新 manifest 运行受影响的完整比较块，保留被替代记录，不能只重跑不喜欢的结果。最小比较块是同一 fixture/repeat 的公共 warmup 和三个 arm；共享核心逻辑、补丁或协议变化时，重跑全部受影响块，不能混用不同实验版本。
- 五次重复只用于初步比较，展示离散程度及逐次值。不能把事务、候选或测试用例数量当独立样本，也不在不同 fixture 的 marker ID 上做跨合约覆盖并集。

**怎么验收**

- 60 个预定槽位都有记录，正式汇总选用的 60 条结果均为 evaluation_valid=true。合法未命中和求解超时可以有效；未解决的工具/证据错误即使有解释，也不能算作有效结果。零命中或零提升无需修改场景让结果变好。
- 报告可从保存的 JSON/events 重新生成，不重新 fuzz 或调用 solver；抽查集合、计时与汇总值一致。
- 结果明确分开机制诊断、正式比较和已有 Stage 1 证据。

**产出**：benchmark CLI、逐次 CSV/JSON、图表及 Markdown 结果报告、复现清单。

## 5. 计划新增的用户入口与文件

以下接口均已实现，README 给出可直接运行的命令。

```sh
./seedbridge campaign <fixture> <arm-name> --repeat <1..5> --config <path>
./seedbridge benchmark --config configs/stage2-benchmark.json --output runs/<new-directory>
./seedbridge benchmark-report runs/<benchmark-directory>
```

其中 arm-name 为 native_resume、concrete_augment 或 symbolic_augment。

| 产出 | 内容 |
| --- | --- |
| src/seedbridge/campaign.py、benchmark.py 等 | 单场编排、三组运行、预算与汇总；具体拆分按现有架构保持简洁 |
| adapters/medusa/ | continuation、lineage 记录接入、native coverage 集合 |
| fixtures/range_gate/、fixtures/workflow_gate/ | 新场景与具体测试 |
| configs/stage2-benchmark.json | 已冻结的配置、策略、预算与重复编号 |
| `runs/<benchmark-id>/manifest.json` | code/tool/patch/fixture/config 摘要、缓存规则、运行顺序和结果索引 |
| `runs/<benchmark-id>/warmup/` | 20 份共享输入及成本证据 |
| `runs/<benchmark-id>/arms/` | 各组候选、原始日志、native 语料、lineage、状态与覆盖事件 |
| `runs/<benchmark-id>/summary.{json,csv,md}`、`goal-hits.svg` | 全部重复、汇总及描述性图表 |
| docs/STAGE2_BENCHMARKS.md | 场景角色、指标定义、冻结协议与限制 |
| docs/STAGE2_VALIDATION.md | 实际命令、通过/失败、机制证据与报告入口 |
| evidence/stage2/ | 可分享的小型证据包及校验和；避免只有被 git 忽略的本机路径 |

保留完整原始 run，另外生成最小证据包：manifest、summary、配置、代表性父子事件及对应 native 输入、重放记录、关键集合与校验和。证据包避免包含用户本机绝对路径；大型日志是否另行打包须在索引中写清。

## 6. 最终验收清单

- [x] Stage 1 两个场景及原有测试回归通过，旧报告语义保持一致。
- [x] 真实 startup replay 后有实际 native continuation，使用默认生成及 mutation 策略。
- [x] 至少一个受控机制测试有“符号 seed → 实际父代选择 → 不同子代 → 实际执行”的完整链条。
- [x] 四个场景覆盖原有回归、容易命中对照、goal 后续行为；投影与条件在配置中声明。
- [x] sequence/state/coverage 三种新颖性分开，import 收益与 continuation 收益分开。
- [x] A/B/C 共同输入、同一总预算与固定缓存协议，所有失败及额外开销留存。
- [x] 完成 60 个 evaluation_valid=true 的正式结果，保留未命中、超时和被替代记录；未解决的工具或证据错误没有混入有效结果。
- [x] 报告可离线重建，测试及实际验收证据、复现说明与小型证据包完整。
- [x] 总结回答哪里有收益、哪里无收益、成本在哪里；结论限于本地教学状态机。

依赖顺序：**P0 → P1 可行性门槛 → P2/P3 → P4 → P5 → 最终验收。** P2 和 P3 可独立准备；P1 的 lineage 门槛未通过前，不将正式性能对比作为阶段收尾。遇到真实阻塞时交付已有证据及准确原因，不扩展目标范围来掩盖缺口。

## 7. 核查依据

本次依据仓库实际源码与锁定版本源码编写，没有将未来功能写成已存在的 API：

- 仓库：adapters/medusa/observed.go、coverage.go，src/seedbridge/config.py、trace.py、pipeline.py、cli.py。
- Medusa v1.5.1：fuzzing/fuzzer.go 的默认 generator，fuzzer_worker_sequence_generator.go 的策略及父代选择，corpus/corpus.go 的 chooser，fuzzer_worker_events.go / fuzzer_hooks.go 的公开观察接口。
- [Stage 1 技术计划](STAGE1_TECH_PLAN.md)、[Stage 1 验收](STAGE1_VALIDATION.md)、[课程 proposal](../output/pdf/symbolic-seed-proposal.md)。
