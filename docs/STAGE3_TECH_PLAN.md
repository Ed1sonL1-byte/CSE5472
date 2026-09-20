# Stage 3 Tech Plan: Budget Sensitivity and Reproducible Evaluation

**负责人：Edison Li。状态：已完成并通过验收。**

本计划承接已完成的 [Stage 2](STAGE2_VALIDATION.md)，以提交 **abad61a** 为代码起点。这里将“进入下一阶段”编号为 Stage 3；不重做 Stage 2。本文规定工作、验收和产出，不安排开发日程或工时。下文的秒数均为实验变量或运行限额。实际结果见 [Stage 3 Results](STAGE3_RESULTS.md)，验收证据见 [Stage 3 Validation](STAGE3_VALIDATION.md)。

## 1. 目标与研究问题

**在现有四个本地教学状态机上，检验 Stage 2 的结论对总运行预算和目标求解调用限额是否稳定，并交付能够从原始记录独立重算的实验材料。**

回答三个问题：

- **RQ1：总预算变化。** 保持增强策略与调用限额不变，增加总预算后，symbolic 相对于 native/concrete 的命中、状态与覆盖差异是否仍存在？
- **RQ2：目标调用限额变化。** 固定总预算和整轮增强限额，只改变 Halmos 目标调用的进程限额，候选成功率、可处理前缀数量及后续探索如何变化？
- **RQ3：开销与结果边界。** 哪些时间花在准备、调用工具、验证、导入、搜索与证据写盘？未命中发生于无合格前缀、查询超时、没有有效候选，还是后续探索没有命中？

**成功标准是实验正确、材料完整、结论受证据约束，不要求符号增强获胜。** 不把 goal 可达报告成安全漏洞，也不将四个已知源码的教学场景推广成真实合约评估。

## 2. 范围与现状

继续使用 phase_counter、bounded_ledger、range_gate、workflow_gate。保持固定 actor/deployer、零金额、一个 uint256 符号参数、1–3 步具体前缀、最多 4 步完整序列、一个 worker 和一轮增强。

本阶段增加的是实验编排、时间观测、数据保存和分析能力。自适应前缀调度、多步符号执行、复杂 ABI、多 actor、第三方目标和链上连接不属于本阶段。

| 已核查的现状 | 本阶段必须处理 |
| --- | --- |
| Stage 2 有 60 个有效结果，保留正、零及负结果 | 将其作为历史先导结果，Stage 3 使用新协议重新采样 |
| BenchmarkConfig/CampaignSpec、CLI、图表及审计固定五次重复 | 用版本化 study 配置描述矩阵，按配置计算分母及期望槽位 |
| 0.75 秒 query_limit 控制整个 Halmos 子进程 | 分开 prefix check 与 goal invocation 限额，不能称为纯 Z3 求解时间 |
| 当前 censor 使用计费结束时间，其中仍有后处理 | 明确记录搜索停止、有效观察结束、证据写完和总计费结束 |
| adapter 有 10,000 条序列限制 | 主实验必须识别并处理计数上限导致的提前停止 |
| Foundry 编译仍可能使用共享 out/cache；corpus 复制在 ledger 前 | 在隔离工作目录中固定缓存规则，复制及准备计入对应成本 |
| Stage 2 原始输出约 6.1 GB、127,000 多个文件 | 先验证去重后的紧凑原始事件，再扩大实验 |
| Stage 2 公共包是摘要与代表事件 | 新交付物应足以在独立目录重算全部正式结果 |
| formal sample 已正确过滤 mutation；mechanism 摘录仍为 111 而非 110 | 修正剩余导出过滤，保留回归，避免硬编码随机运行的次数 |

当前 evidence/stage2 下的带“ 2”“ 3”文件名副本不属于正式输入。记录其路径与摘要，保留内容不同的文件；不要为得到干净状态而自动删除。它们不应进入 study manifest 或自动证据收集。

## 3. 冻结的实验设计

### 3.1 主实验：仅改变总预算

| 参数 | 设定 |
| --- | --- |
| fixture | 现有四个 |
| arm | native_resume、concrete_augment、symbolic_augment |
| repeat | 每个 fixture/config 10 次，编号 1–10 |
| 总预算 | 8 秒、32 秒 |
| 公共 warmup | 每个 fixture/repeat 一次，40 个完整序列 |
| 整轮增强上限 | 2.5 秒 |
| Halmos prefix check 进程上限 | 0.75 秒 |
| Halmos goal invocation 进程上限 | 0.75 秒 |
| 前缀／接纳种子上限 | 各 4 个，每个前缀最多接纳 1 个 |
| concrete 增强 | 沿用冻结的边界字典和每前缀最多 20 次尝试 |
| 支持范围 | 与本节之前的固定范围相同 |

主矩阵为 **4 × 3 × 2 × 10 = 240 个槽位**。

总预算比较不得同时放宽整轮增强上限、前缀数量、warmup 长度或输入字典。这样比较的是“相同增强策略在更长总预算下是否划算”。

### 3.2 次实验：仅改变目标求解调用限额

固定总预算为 32 秒，整轮增强上限仍为 2.5 秒，prefix check 仍为 0.75 秒。只对 symbolic_arm 比较 goal invocation 上限：

- 0.50 秒；
- 0.75 秒：复用主矩阵中完全相同的 40 条结果；
- 1.50 秒。

新增 **4 × 2 × 10 = 80 个槽位**，共计 **320 个不同的正式槽位**。被复用的 40 条结果不能当成新样本重复累计。

这里研究的是**目标调用的 wall-clock 限额分配**。当前 Halmos 子进程包含启动和相关构建检查，内部 assertion solver timeout 仍是独立设置；记录两个限额的有效值，不声称只改变了 SMT 求解器的计算预算。整轮增强上限不变，因此较长单次调用可能减少后续可尝试的前缀，这属于要报告的效果。

### 3.3 共同输入与运行顺序

- 新生成 40 份公共 warmup：每个 fixture × repeat 一份。各块内的八个配置共用相同 corpus、prefix pool、编译缓存快照及其摘要。
- 使用新的、预先冻结的 Stage 3 seed 表；不挑选 Stage 2 中成功的 warmup 作为正式起点。
- 公共成本在物理上只发生一次，在每个配置的逻辑预算中各计一次。机器实际总支出与逻辑计费总和分开。
- 每个配置自己执行增强与验证，不能把其他配置已解出的模型作为免费输入。只共享约定的 warmup 资料。
- 冻结块内八种配置的运行顺序并轮换，顺序运行，避免并发争抢本机资源。
- 公开可控随机源固定；Medusa 内部 chooser 的 clock-seeded RNG 继续如实披露。相同 warmup 不等于相同随机轨迹，320 个槽位也不等于 320 个彼此独立的样本。
- 无合格前缀、目标在 warmup 已命中、没有模型及合法超时都保留。只排除自身 goal 已成立的前缀，不根据结果替换重复编号。

### 3.4 对照名称

主对照仍是**共同语料重启下的 Medusa 默认策略**，不是不中断运行的 unmodified Medusa。所有 arm 使用同一记录补丁和执行约束。

不中断 native 的独立比较可作为后续扩展，不属于本阶段必需矩阵。最终报告必须列出这一限制；原 proposal 中更广泛的真实性质违反评估与更多合约场景也尚未由这四个教学场景覆盖。

## 4. 工作包

### P0：封存历史基线与补齐遗留导出

**实施状态：完成。** 验收记录与产出索引见 [Stage 3 Validation / P0](STAGE3_VALIDATION.md#p0封存历史基线与补齐遗留导出)。

**做什么**

- 修正 mechanism 摘录的父代选择过滤，使其只统计 mutation；正式样例和机制样例使用同一语义。
- 移除“必须恰好 170 次”这类只适用于一次运行的通用导出断言；该数值可保留为历史数据核对值，不能限制其他实验。
- 保留 Stage 2 原始 campaign、旧协议标识及结果。重建派生资料时记录来源与变更原因。
- 记录 Stage 3 开始时的源码、锁文件、配置、patch、adapter 和 fixture 摘要。HEAD 加 dirty 状态不足以表示未提交源码内容，必要时保存执行源码快照。

**验收**

- Stage 2 的正式样例为 170 次 mutation selection，机制样例为 110 次；36/36 的核心结果保持一致。
- 旧报告与审计仍可读取；Stage 2 原始 campaign 未修改。
- 新运行能够凭 manifest 定位实际执行的源码与工具版本；无关文件副本不混入证据。

**产出**：基线索引、导出回归、源码内容清单、Stage 2 收尾记录。

### P1：版本化 StudySpec 和数据驱动矩阵

**实施状态：完成。** 验收记录与产出索引见 [Stage 3 Validation / P1](STAGE3_VALIDATION.md#p1版本化-studyspec-和数据驱动矩阵)。

**做什么**

- 增加独立 Stage 3 schema，而不是把旧配置里的 5 和 60 散落地改成新数字。
- 配置包含 fixture 白名单、repeat、seed、实验族、总预算 profile、prefix/goal 调用限额、增强限额、arm、顺序和资源限制。
- 每个槽位以 study_id、fixture、repeat、arm、total_budget、goal_invocation_limit 唯一标识；输出目录不能跨预算覆盖。
- 新 runner、reporter、auditor 和 exporter 接收明确 run 路径，以冻结 manifest 为索引。
- 限定到现有四个内置 fixture，允许 smoke 使用其子集；不开放任意外部目标。
- Stage 2 格式和 CLI 保留兼容入口，新的图表分母、实验数和引用均由配置导出。

**验收**

- 配置展开恰好产生 320 个不同正式槽位、40 个公共块，能检测重复、缺失、未知 fixture 和不合法预算。
- 无需实际执行工具，就能生成可检查的 dry-run 矩阵。
- 小型 smoke 配置可用，旧 Stage 2 的 60 槽位语义仍保持不变。

**产出**：StudySpec/schema、冻结配置、矩阵生成器、配置与兼容性测试。

### P2：真实时间边界、停止原因与缓存公平性

**实施状态：完成。** 验收记录与产出索引见 [Stage 3 Validation / P2](STAGE3_VALIDATION.md#p2真实时间边界停止原因与缓存公平性)。

**做什么**

明确区分以下时间：

| 字段 | 含义 |
| --- | --- |
| budget_deadline | 含公共成本的逻辑总截止 |
| search_started / search_stopped | native 实际开始与停止生成、执行 |
| last_observed_event | 最后一个完整、已验证的观察事件 |
| evidence_flush_finished | 必需的在线证据已写完 |
| charged_end | 全部在线计费工作结束 |
| offline_analysis_elapsed | 离线重算／归档耗时，不属于搜索预算 |

- Go 记录单调时钟相对时点，Python 保存子进程与本次账本的映射基准；不能直接比较不同进程的裸时钟值，也不能用读到日志的时刻代替执行时刻。
- 首次 goal 与截尾使用声明的有效观察时间。最后一条完整序列之外的部分执行另行保留；没有完整观察证据的片段不推算成成功。
- 保存 stop_reason：时间到、序列上限、取消、工具错误、证据错误。当前 10,000 条上限须在 campaign 模式配置化或取消为主限制；正式实验以时间协议结束，安全上限提前触发时保留记录并标记协议未满足。
- 截止后的事件保留并标记 after_deadline，不能进入主指标。清理容差不能成为额外搜索时间。
- 将 corpus/缓存复制、harness 生成、构建、工具调用、解析、验证、启动、导入和在线记录纳入计费；提前预留但未使用的预算单独报告。
- 用隔离工作目录冻结 Foundry 缓存：每个公共块从相同基础状态构建并生成快照，各配置取得副本，不共享本轮新增产物。记录复制与构建成本、实际缓存路径和内容摘要。
- 离线指标计算和图表生成离开在线账本；如果某个计算用于下一步选择或验证，它仍是在线成本。
- 区分 prefix check 和 goal invocation 的独立进程上限；实际有效上限可因剩余总预算而缩短，记录 requested 与 effective limit。
- 保留工具错误优先于 timeout 的规则；正常未命中与完整性错误继续分开。

**验收**

- 在受控测试中增加导出延迟只改变写盘/计费结束，不改变搜索停止、首次命中及观察截尾。
- 覆盖时间到、计数上限、部分序列、工具错误与 timeout 同时发生、无候选、无前缀、写盘失败等边界。
- 三组使用相同源码／构建／缓存起点，没有 ledger 外的 arm 专属准备工作。
- 不把旧 Stage 2 的计费结束回填为精确搜索停止；历史数据保留原时间语义。

**产出**：扩展时间协议、停止原因、隔离缓存与预算实现、边界测试、计费样例。

### P3：紧凑原始证据与存储预检

**实施状态：完成。** 验收记录与产出索引见 [Stage 3 Validation / P3](STAGE3_VALIDATION.md#p3紧凑原始证据与存储预检)。

**做什么**

- 每条实际执行记录只保存一次，使用 sequence/event ID 引用前缀；累计状态和覆盖在离线阶段重建。
- 紧凑流至少保留调用身份与上下文、outcome、有限状态、invariant、逐步 native marker、真实父代、生成策略、执行时点及完整性标志。
- 将原生 codec payload 或无损等价表示纳入序列档案；对于抽查序列，重建后的 native hash 与原记录一致。已接纳 seed、公共原生 corpus 和模型／验证来源完整保存。
- 可以使用字典编码、JSONL 及按 campaign 分片的 gzip。减少重复快照，不删除重算所需字段；不只留下 summary。
- 流式写盘，避免随序列数无限累积大型重复对象。在线记录或压缩的成本计入运行，离线归档单独计时。
- 写清 EOF/记录数/校验和；磁盘不足或尾部截断必须报 evidence_error，不能产生 valid 报告。
- 正式矩阵开始前检查本机可用空间和 smoke 的事件、文件、字节量；配置存储保护上限，不能默默截断输出。

**验收**

- 选用既有 Stage 2 数据转换为紧凑格式，在旧协议范围内重算 60 份 sequence/state/coverage 和 lineage 计数，结果一致。
- 缺行、重复 ID、错误字典、截断、父代不存在和校验和错误均被审计识别。
- 新 smoke 的记录体积、文件数量及写盘耗时有实测对照；证明能够承载正式矩阵之后才扩量，不设“必须压缩到某个好看比例”的验收。

**产出**：版本化事件格式、读写器、无损转换与重算测试、存储预检报告。

### P4：冻结配置并运行 320 个槽位

**实施状态：完成。** 320/320 条有效；验收记录与失败历史见 [Stage 3 Validation / P4](STAGE3_VALIDATION.md#p4冻结配置并运行-320-个槽位)。

**做什么**

- 先完成计时、存储、缓存和三组 smoke，再冻结源码、配置、顺序、预算、限额和指标。
- smoke 仅用于检查协议可运行，不以哪组更好来选择预算、fixture 或 prefix。
- 按第 3 节分别执行主实验 240 条、补充实验 80 条。新协议全部重跑，Stage 2 的旧 60 条不混入正式矩阵。
- 允许在完整公共块边界恢复中断任务；恢复必须核对 manifest 与输入摘要，不能复用部分执行冒充新完整结果。
- 原始失败记录永久保留。同一冻结执行版本下的中断或基础设施故障，按完整公共块重试，不只替换表现不好的 arm。
- 若修复改变执行代码、计时协议或需要新观察字段的指标语义，重新冻结并重跑整套 320 槽位矩阵，不能混用执行版本。仅涉及报告、打包或能用完整原始数据离线纠正的派生计算时，保留执行记录、更新 reporter 版本并统一重建派生资料即可。

**验收**

- 最终有 320 条 evaluation_valid=true 的正式记录。正常超时、无前缀、未命中、零收益和负收益可以有效；工具或证据错误不可以。
- 槽位完整性来自 manifest，而非手写数字检查；无不同代码或计时协议混表。
- 每个公共块的八个配置有相同 warmup/prefix/cache 源摘要与公共计费值，且没有免费模型复用。
- 实际总预算、有效查询限额、停止原因和未使用预算均可审计。

**产出**：冻结 manifest、40 份公共输入、320 条正式记录、全部替代/失败历史。

### P5：独立离线审计、统计与完整证据包

**实施状态：完成。** 独立审计、报告重建与完整档案复核均通过；见 [Stage 3 Validation / P5](STAGE3_VALIDATION.md#p5独立离线审计统计与完整证据包)。

**做什么**

- 用独立的集合与计数核查核心指标，避免仅再次调用生产指标函数就称为独立验证。
- 从原始记录验证矩阵、身份、父代先于子代、不同子代、实际执行、native marker、投影边界、目标命中、时间和预算。
- native import、continuation、total 的状态/覆盖分列。seed 子代访问到的增量仍明确参照基线；若报告“首次发现”，必须逐事件扣除此前所有已观察集合，不自动解释为因果净收益。
- 分开输出辅助具体验证首次命中与 native 首次命中。纯符号模型不计作命中。
- 每 fixture/config 展示命中数 /10、所有逐次值、实际观察截止及开销分解；不能只平均命中运行，也不能将各调用当独立实验。
- 预算对比只与相同 fixture/repeat 的公共块对应；共享 warmup 的配置不能当成完全独立样本。十次重复仍属小规模描述性评估，不宣称一般性统计优势。
- 提供总预算对照图、目标调用限额对照图、运行成本分解及未命中原因表。两档总预算只支持两档比较，不拟合通用性能曲线。
- 打包全部紧凑原始记录、manifest、冻结配置、源码/构建摘要、审计器、派生表图和校验和。小型摘要包与完整重算包明确区分。
- 在新目录解压，离线重建全部报告，不依赖本机原 runs 路径、EVM 工具、solver 或网络。先完成本地可分发档案；实际公开位置在发布后填写，不能把未上传的档案说成已公开。

**验收**

- 独立审计通过，所有主表值可追溯到具体事件；历史样例次数不作为新审计通过条件。
- 连续离线重建得到一致的数据与图表摘要。
- 只凭完整档案便能重算 320 条结果及其核心审计；随机抽查数值无需再运行 fuzzing。
- 未命中曲线只使用真实已观测区间，不把报告写盘期间延长成搜索时间。

**产出**：study auditor/reporter、CSV/JSON/Markdown、SVG、完整紧凑证据档案、校验和与离线复核说明。

### P6：课程项目报告与验收记录

**实施状态：完成。** 结果、英文报告、README 和验收记录均已交付；见 [Stage 3 Validation / P6](STAGE3_VALIDATION.md#p6课程项目报告与验收记录)。

**做什么**

- 更新 README，明确 Stage 1 证明桥接、Stage 2 证明 mutation 接入、Stage 3 检验预算变化下的结果。
- 编写英文报告草稿：问题、已有方法定位、工具设计、实验协议、结果、失败情况、限制与复现入口。
- 每条主要结论关联具体表格或原始证据，不把工具集成描述为首次提出 hybrid fuzzing。
- 单独解释 WorkflowGate：是否无前缀、是否调用超时、是否产生有效候选，以及不同随机轨迹如何限制解释。
- 列出与原 proposal 的差距：现有支持类型和长度较窄、只有四个自建场景、对照是重启协议、尚未证明真实安全性质违反发现能力。Stage 3 完成不自动等于原 proposal 的所有承诺完成。
- 验收记录写实际测试命令、结果、数据版本及交付位置，不预填测试通过数量。

**验收**

- 报告回答 RQ1–RQ3，所有正、零及负结果均保留，结论没有超过证据范围。
- README 的新命令可用；Stage 1/2 相关回归及 Stage 3 必需检查通过。
- 交付清单中的代码、配置、原始资料、报告、审计和复现说明齐全。

**产出**：docs/STAGE3_RESULTS.md、docs/STAGE3_VALIDATION.md、docs/PROJECT_REPORT.md 和 README。

## 5. 计划接口与交付目录

以下接口已经实现。它们复用现有桥接、固定 Medusa adapter 和四个内置 fixture，没有另造一套 fuzzer。

```sh
./seedbridge study-plan --config configs/stage3-study.json
./seedbridge study --config configs/stage3-study.json --output runs/<new-study>
./seedbridge study-report <study-directory>
./seedbridge study-audit <study-directory>
./seedbridge study-export <study-directory> --output artifacts/<archive-name>
./seedbridge study-verify-archive artifacts/<archive-name> --output runs/<new-directory>
```

| 产物 | 内容 |
| --- | --- |
| configs/stage3-study.json | 冻结参数、矩阵和顺序 |
| src/seedbridge/study.py 等 | study 入口、配置与执行编排；复用现有桥接 |
| src/seedbridge/budget.py、campaign.py、benchmark.py、metrics.py | 必需的版本兼容、计时与统计调整 |
| adapters/medusa/ | 事件时点、停止原因、紧凑记录及 campaign 限额 |
| runs 下的新 study 目录 | manifest、公共块、每个 profile 的原始事件与派生报告 |
| evidence/stage3/ | 小型索引、表图、配置、审计摘要和完整档案校验和 |
| artifacts 下的完整证据档案 | 全量紧凑记录及离线重建材料 |
| docs/STAGE3_RESULTS.md | 问题、协议、结果与限制 |
| docs/STAGE3_VALIDATION.md | 实际验收及证据入口 |
| docs/PROJECT_REPORT.md | 面向课程读者的英文报告草稿 |

## 6. 最终验收清单

- [x] Stage 2 机制摘录剩余计数问题已修正，原始 campaign 保持不变。
- [x] 新 study schema、旧格式兼容和矩阵 dry-run 通过。
- [x] 搜索、观察、写盘与计费结束可区分；计数限额不会被误当时间限额。
- [x] 缓存与输入准备成本统一，prefix/goal 调用预算独立且有效值可查。
- [x] 紧凑原始证据能无损重算，正式执行前完成存储预检。
- [x] 240 条主实验加 80 条补充实验全部有效，失败及替代记录保留。
- [x] 原始事件的独立审计与全部报告重建通过。
- [x] 完整证据档案在新目录无需外部工具即可离线复核。
- [x] RQ1–RQ3、局限性与原 proposal 范围差距写清；零或负结果正常验收。
- [x] 代码、配置、测试、数据、英文报告草稿与复现文档全部交付。

执行顺序：**P0 → P1 → P2/P3 → P4 → P5 → P6**。P2/P3 可独立推进，但正式矩阵必须等时间、缓存和紧凑记录的检查通过后开始。遇到真实阻塞时保留工作与证据并说明原因，不扩大目标范围，也不把未验证能力写成完成。

## 7. 本地核查依据

本计划来自现有代码及保存结果，不依赖未验证的工具能力：

- src/seedbridge/benchmark.py：固定矩阵、warmup、corpus 复制、预算 reserve、截尾、图表和报告。
- src/seedbridge/campaign.py、budget.py、cli.py：schema、repeat 限制、计费与旧入口。
- src/seedbridge/halmos.py：整个子进程 timeout 与内部 assertion solver timeout。
- adapters/medusa/main.go、observed.go：序列上限、生成与执行记录、timing 与写盘。
- scripts/audit-stage2.py、build-stage2-evidence.py：历史矩阵及样例路径/次数的硬编码。
- [Stage 2 结果与限制](STAGE2_BENCHMARKS.md)、[Stage 2 证据索引](../evidence/stage2/INDEX.md)、[原 proposal](../output/pdf/symbolic-seed-proposal.md)。
