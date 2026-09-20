# Stage 3 Results: Budget Sensitivity and Reproducible Evaluation

Stage 3 使用冻结配置 `configs/stage3-study.json`，在四个仓库自建教学 fixture 上完成了
40 个共同 warmup 区组和 320 个不同槽位。独立审计从 gzip JSONL 原始事件重新计算结果，
320/320 条均为 `evaluation_valid=true`。本页报告描述性结果；这些场景不是漏洞基准，十次重复也
不足以支持对第三方合约或一般 fuzzing 性能的推断。

## 协议与数据完整性

- 主实验：4 fixtures × 3 arms × 2 个总预算 × 10 repeats = 240 个槽位。
- 目标调用限额实验：32 秒 symbolic arm 的 0.50/0.75/1.50 秒比较；0.75 秒复用主实验的
  40 条记录，另外新增 80 条，合计仍为 320 个不同槽位。
- 每个 fixture/repeat 的八个 profile 共用相同 warmup、prefix pool、cache 和 corpus 摘要；
  每个 profile 获得独立副本，公共成本在各自逻辑预算中计费。
- 固定单 worker、actor、`msg.value = 0`、一个 `uint256` 符号参数、1–3 步具体前缀、最多
  4 步完整序列和一轮增强。
- 正式数据包含 791,282 条完整序列及 553,708 条 mutation 事件。全部 40 个区组完整提交，
  没有工具错误、证据错误、状态不匹配或失败重试混入结果。

## 汇总结果

下表把四个 fixture 的十次重复合并。每行分母为 40；32 秒 symbolic 的三种调用限额分别列出。

| Profile | Goal hits | Accepted seeds | Mean charged end |
| --- | ---: | ---: | ---: |
| 8 s native | 17/40 | 0 | 6.245 s |
| 8 s concrete | 22/40 | 40 | 6.237 s |
| 8 s symbolic, q=0.75 s | 39/40 | 36 | 6.217 s |
| 32 s native | 20/40 | 0 | 30.853 s |
| 32 s concrete | 25/40 | 40 | 30.848 s |
| 32 s symbolic, q=0.50 s | 40/40 | 39 | 30.815 s |
| 32 s symbolic, q=0.75 s | 40/40 | 39 | 30.833 s |
| 32 s symbolic, q=1.50 s | 40/40 | 40 | 30.825 s |

8 秒和 32 秒是预算上限。首次命中与未命中截尾使用实际观察结束点；profile 的平均实际观察
结束约为 6.0 秒和 30.0 秒。表中的 charged end 还包含公共构建/warmup 分摊、输入复制、增强、
seed 导入、进程启动和在线证据验证，但不包含离线报告和归档。

## RQ1：总预算从 8 秒增加到 32 秒

| Fixture | 8 s native | 32 s native | 8 s concrete | 32 s concrete | 8 s symbolic | 32 s symbolic |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| PhaseCounter | 0/10 | 0/10 | 3/10 | 3/10 | 10/10 | 10/10 |
| BoundedLedger | 0/10 | 0/10 | 2/10 | 2/10 | 10/10 | 10/10 |
| RangeGate | 10/10 | 10/10 | 9/10 | 10/10 | 10/10 | 10/10 |
| WorkflowGate | 7/10 | 10/10 | 8/10 | 10/10 | 9/10 | 10/10 |

配对的 40 个 fixture/repeat 比较中，32 秒相对 8 秒为 native、concrete、symbolic 分别增加
3、3、1 次命中；没有配对从命中变为未命中。新增命中集中在 RangeGate/WorkflowGate。
PhaseCounter 和 BoundedLedger 的狭窄条件没有因为 native continuation 变长而改变：native 仍为
0/20，concrete 仍为 5/20，symbolic 仍为 20/20。

更长预算显著增加了执行量。32 秒相对 8 秒时，每个配对平均新增完整序列约为 native 2,937、
concrete 2,706、symbolic 2,496；平均新增有限状态分别为 6.25、5.70、6.18。状态和覆盖是运行
观察量，受 Medusa 未受控的 clock-seeded chooser 影响，不能把各 arm 的差值解释为纯因果效果。

## RQ2：目标调用限额

在 32 秒 symbolic profile 中，0.50、0.75 和 1.50 秒三档均为 40/40 命中。相对 0.75 秒：

| Goal invocation limit | Goal-hit delta | Accepted-seed delta | State delta | Coverage delta |
| --- | ---: | ---: | ---: | ---: |
| 0.50 s | 0 | 0 | +19 | 0 |
| 1.50 s | 0 | +1 | +6 | 0 |

因此，本协议没有观察到把单次目标调用从 0.50 秒放宽到 0.75 或 1.50 秒所带来的命中收益。
1.50 秒多接纳一个 seed，但没有增加目标命中或 runtime coverage。状态差值的正负随重复变化，
与独立 Medusa 随机轨迹混杂，不能据此声称较长调用限额提高探索质量。

这些限额是整个 Halmos goal-invocation 子进程的 wall-clock 上限，包含启动及相关检查；它们不是
隔离的 SMT CPU 时间。整轮增强仍受 2.5 秒上限约束，单次调用更长也可能减少可尝试前缀数。

## RQ3：成本和负结果边界

平均公共构建/warmup 分摊为 0.987 秒。8 秒 profile 中，native 的后续启动与搜索平均为
5.250 秒；concrete 增强平均使用 0.854 秒，后续 native 为 4.389 秒；symbolic 增强平均使用
1.821 秒，后续 native 为 3.402 秒。32 秒 profile 的对应增强均值约为 concrete 0.877 秒、
symbolic 1.825–1.833 秒，其余时间主要用于 native continuation。输入/缓存复制、seed import 和
在线验证均单独记录，没有作为免费准备工作隐藏。

320 条记录的最终原因如下：

| Reason | Count | Interpretation |
| --- | ---: | --- |
| `native_import_goal_reached` | 151 | 具体重放通过的 seed 由 Medusa 实际导入执行并命中 |
| `native_continuation_goal_reached` | 52 | 默认 native continuation 命中 |
| `warmup_goal_reached` | 40 | 共同 warmup 已命中，保留而不替换该重复 |
| `native_continuation_no_goal` | 43 | 观察区间内 native continuation 未命中 |
| `no_candidate` | 31 | 有前缀池但没有通过完整增强/验证的候选 |
| `no_eligible_prefix` | 2 | 没有目标尚未成立且满足范围的前缀 |
| `augmentation_timeout` | 1 | 增强总限额到期；作为有效负结果保留 |

WorkflowGate 的 8 秒结果说明不能把负结果统一归因于求解开销：concrete 包含一次
`no_eligible_prefix` 和一次 `no_candidate`；symbolic 有一次整轮增强超时；native 有三次
continuation 未命中。该 fixture 的独立随机轨迹也会改变后续搜索。32 秒时三组均为 10/10，
只说明在这十个共同区组中增加观察时间覆盖了短预算的缺口。

## 机制与复核

Stage 3 没有改变 Stage 1 的信任链：前缀来自 Medusa 的真实执行记录；Halmos 在同一 actor、
value 和状态投影下重放并求解最后一个 `uint256`；Forge 在新部署上具体确认 false→true；原生
codec 导出的新 seed 再由 Medusa 执行。compact v2 保存每条完整序列的无损 native payload、
所有已执行前缀引用、逐步状态/覆盖标记和父子 lineage。独立审计要求 mutation 父代更早存在，
并核对接纳 seed 的重放和实际使用。

完整档案 `artifacts/stage3-formal-v1.tar.gz` 为 3,358,084,381 bytes，SHA-256 为
`91bf6e5063a4d7644e0f84a1c8187480a35c66185e4f929d275384db6ad2ad25`。它包含
43,482 个 study 文件及 5,333,122,321 bytes 解压数据。档案已在新目录逐文件校验，并只用
Python 标准库连续重建两次；两次 Markdown、CSV 和 JSON 结果一致。小型公开证据见
`evidence/stage3/INDEX.md`。

## 解释限制

- 四个 fixture 均为已知源码、有限状态的教学场景，不代表生产合约、真实漏洞或一般安全性。
- native 对照是共同 warmup 语料重启后的 Medusa 默认策略，不是一次不中断的 stock Medusa。
- 每个 profile 只有十次重复，共享 warmup，且 Medusa 部分 chooser 使用 clock-seeded RNG；
  320 个槽位不是 320 个相互独立的统计样本。
- 两档总预算只支持这两个点的配对描述，不能拟合通用预算曲线。
- 覆盖和有限状态投影用于可审计比较，不等于完整 EVM 世界状态或漏洞发现能力。
- Stage 3 支持范围仍是固定 actor、零 value、一个符号 `uint256`、短序列、单 worker 和一轮增强。

逐槽值位于 `evidence/stage3/observations.csv`，结构化汇总位于
`evidence/stage3/summary.json`，生成图位于同一目录。完整验收命令和失败历史见
`docs/STAGE3_VALIDATION.md`。
