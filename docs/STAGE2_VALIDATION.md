# Stage 2 Validation Record

本记录与 [Stage 2 技术计划](STAGE2_TECH_PLAN.md) 同步维护。只记录已经执行并有证据的结果；未验证项目保持未完成。

## P0：campaign 数据与预算协议

**状态：完成。**

已实现版本化 `CampaignSpec`、`CampaignRecord`、总截止时间预算账本和异常安全阶段计时器。执行状态、目标命中、增强状态、lineage 状态和 evaluation validity 分开保存。每个阶段记录预算前后值、wall time、失败原因、是否越过总截止时间和清理宽限；阶段状态使用封闭枚举。当前平台没有可移植的完整子进程树 CPU 归因，记录明确保存 `unavailable` 及原因，不以父进程 CPU 代替。

Stage 1 的阶段计时改用相同的异常安全计时器，旧报告字段和完成语义保持不变。

验收命令与结果：

```text
uv run --frozen pytest tests/unit -q
118 passed

SEEDBRIDGE_INTEGRATION=1 uv run --frozen pytest -q --junitxml=runs/stage2-p0/stage1-regression.xml
100 passed

python3 -m compileall -q src tests
git diff --check
```

本机完整回归 XML 位于 `runs/stage2-p0/stage1-regression.xml`。最终证据包会保存可分享的摘要、配置与校验和，避免依赖被 git 忽略的本机 run 路径。

## P1：native continuation 与真实 lineage

**状态：完成。**

已确认 Medusa v1.5.1 的公开 worker 事件只能观察序列执行开始和结束，实际父代选择位于内部 `CallSequenceGenerator` 和 corpus chooser，公开事件没有父代标识。当前工作是验证一个固定版本的最小记录补丁：只暴露 generation id、现有策略名和实际选中的父代 hash；adapter 在真实执行结束事件中关联子代 hash及执行结果。该补丁不得增加 RNG 调用、改变权重或改写输入。

机制运行 `runs/stage2-p1-mechanism/campaign-01.json` 实际完成 300 条序列：1 条 startup replay、92 条全新生成、207 条 mutation。导入的符号 seed hash 被记录为真实父代 110 次，其中 85 次的规范化调用身份与父代不同且子代已执行。代表事件 generation 6 使用 `corpus_head`，四步均成功并保留父代/子代 hash、调用身份、状态与覆盖。

记录开启/关闭对照各执行同一具体导入序列。两边的完整步骤、native digest、状态根、60 个累计 marker、coverage digest 和 observer neutrality 一致；开启时有 2 条 lineage，关闭时为 0 条。补丁源码不调用 RNG、不改选择权重或输入，正式运行统一开启记录。

固定版本构建由 `scripts/prepare-medusa-lineage.sh` 从 Go module cache 的 v1.5.1 副本生成；脚本验证上游文件和补丁后文件 SHA-256，全局 module cache 不被修改。补丁为 `adapters/medusa/patches/medusa-v1.5.1-lineage.patch`。

## P2：新增场景

**状态：完成。**

- `range_gate` 的 4 个 Forge 具体测试通过，普通值 32 在最宽边界配置下可到达 goal。
- `workflow_gate` 的 4 个 Forge 具体测试通过，goal 后可继续到两个不同有限状态并覆盖两个分支。
- `./seedbridge run range_gate ...` 与 `./seedbridge run workflow_gate ...` 均得到 `stage1_confirmed`，两者走同一 codec、harness、Halmos、具体重放和 Medusa 回灌代码。
- ready predicate、前缀长度、有限状态投影和 goal 定义均位于 `src/seedbridge/config.py`；引擎不包含目标参数解。

## P3：独立探索指标

**状态：完成。**

adapter 逐步导出 `(runtime_bytecode_sha256, marker_hex)` 集合及命中次数，并继续核对枚举 marker 数量与 Medusa `BranchesHit()`。`src/seedbridge/metrics.py` 分开计算规范化完整序列、有限状态投影和覆盖集合，保存 warmup/import/continuation 三段及差集。单元测试证明重复重放只增加 hit count，不增加 unique sequence/state/coverage，并验证人工集合的 union/difference。

## P4：三组策略和公平预算

**状态：完成。**

冻结配置位于 `configs/stage2-benchmark.json`。具体增强使用固定边界字典后接带 seed 的随机值，最多 20 次/前缀；候选由一次 Go codec 批处理生成，并在一次 Medusa 编译中批量新部署检查。符号增强每个前缀最多一次 Halmos 查询，模型仍须经过 Forge 和 native replay。两组最多接纳 4 个 seed。

最终三组 smoke `runs/stage2-p4-smoke-05` 共用同一 PhaseCounter warmup，三条结果均 `evaluation_valid=true`：native、concrete、symbolic 的计费 wall time 分别约 7.22、6.99、6.62 秒。concrete 接纳有效候选；symbolic 在 2.5 秒增强总限额处分类为 timeout，随后仍完成约 3.23 秒 native continuation。所有组均在 8 秒总预算内，lineage verified。

## P5：正式实验与报告

**状态：完成。**

第一次完整运行 `runs/stage2-formal-01` 保留 60 个槽位，其中 56 个有效。四个 symbolic campaign 在 deadline 边界遇到清理权限异常或 native 验证超时向外冒泡，不能计为正常策略结果。该运行保存 `superseded.json`，没有挑选部分结果混入最终汇总。

修复进程树清理的 `PermissionError` 处理、symbolic 总截止预留和 native 验证 timeout 分类后，使用同一冻结配置完整重跑为 `runs/stage2-formal-02`。结果为 **60/60 `evaluation_valid=true`**，包括合法的未命中、无合格 prefix、无候选和求解时限结果。所有 arm 的计费 wall time 均未超过 8 秒，且无 stage 标记为 `after_deadline`。

正式结果摘要：

| Fixture | native goal | concrete goal | symbolic goal | 主要观察 |
| --- | ---: | ---: | ---: | --- |
| bounded_ledger | 0/5 | 0/5 | 5/5 | symbolic 五个 seed 均被选择并执行 mutation 子代 |
| phase_counter | 0/5 | 0/5 | 5/5 | symbolic import 每次增加 1 个目标 coverage marker |
| range_gate | 5/5 | 5/5 | 5/5 | 三组命中率与逐次总 coverage 增量一致；额外求解没有命中率收益 |
| workflow_gate | 5/5 | 5/5 | 3/5 | symbolic 接纳 0 个 seed；一次未命中无合格 prefix、增强耗时为零，另一次尝试求解但无候选 |

concrete 共接纳 21 个 seed，symbolic 共接纳 15 个；36 个都与各自 warmup 序列不同，也都作为真实 mutation 父代产生并执行了不同子代。受 seed 归因的子代在 `workflow_gate` concrete 五次重复中合计增加 10 个投影状态和 48 个 coverage marker；在两个狭窄条件中，symbolic 子代合计增加 24 个投影状态，但 coverage 只增加 1 个 marker。未把其余 continuation 的收益归给 seed。`workflow_gate` 的两个 symbolic 未命中不能统一归因于求解开销：repeat 1 没有合格 prefix、求解开销为零；repeat 2 才有三次符号尝试。各 arm 还受 Medusa 内部独立 clock-seeded chooser 影响，因此这里只报告观察关联，不作单一原因的因果解释。

独立审计命令：

```text
uv run --frozen python scripts/audit-stage2.py \
  runs/stage2-formal-02 --output runs/stage2-formal-02/audit.json
```

审计从保存的 29,259 条完整序列重算：60 个 campaign 与 20 个共同 warmup 齐全；29,259 条 lineage 与完整序列逐一对应；20,382 条 mutation 的父代均指向更早已执行序列；60 份 sequence/state/coverage metrics 与保存值完全一致；36/36 接纳种子都有不同且实际执行的子代。`audit.json` 的状态为 `passed`，错误列表为空。公开正式样例只统计 `kind=mutation` 的父代事件，共 170 次；startup replay 不再计入选择次数，首条公开选择事件也来自 mutation。

连续重建 `./seedbridge benchmark-report runs/stage2-formal-02` 后，四个输出的 SHA-256 均保持不变，证明报告只依赖保存数据：`summary.json` 为 `d935434533174e5c52d937a31ec4eadab50899d69eded516170bff430399938c`，`summary.csv` 为 `2f891019a15e8437fe52007f5cd666556b8afb76fd95fb001b0f4d8e46b12054`，`summary.md` 为 `2da77637aef59260171ca9a23d1a2f2c1ed45269aa9647931fc37a51148f0049`，`goal-hits.svg` 为 `bfa275c6ef77e758b4bd40485f0d2ddddc594465e0d54faf9b2ea9a59352eb12`。本轮收尾修正后，报告的 22 个未命中均按实际计费观察结束时间截尾（6.394–7.286 秒），8 秒单列为预算上限；原始 60 条 campaign 未改动。

可分享证据位于 `evidence/stage2/`：包含冻结配置、路径清理后的 manifest、60 条 JSON/CSV/Markdown 汇总、goal-hit SVG、审计结果、代表性的符号 seed → 父代选择 → 子代执行事件及两份原生 Medusa 输入、记录开关中性对照、新 fixture 验收、三组 smoke、被替代运行说明和全包校验和。完整 127,000 余个原始生成文件继续保存在 Git 忽略的 `runs/stage2-formal-02`，避免以小型摘录代替原始记录。

结果解释、指标定义和限制见 [STAGE2_BENCHMARKS.md](STAGE2_BENCHMARKS.md)。四个场景均为仓库自建教学状态机；本记录不声称发现漏洞，也不把结果推广到真实合约。

## 最终回归

```text
python3 -m compileall -q src tests
uv run --frozen pytest tests/unit -q
SEEDBRIDGE_INTEGRATION=1 uv run --frozen pytest -q --junitxml=runs/stage2-final/pytest.xml
cd adapters/medusa && GOTOOLCHAIN=local go test -mod=readonly ./...
cd adapters/medusa && SEEDBRIDGE_INTEGRATION=1 GOTOOLCHAIN=local go test -mod=readonly ./...
git diff --check
```

2026-09-19 的最终结果：`compileall` 与 `git diff --check` 无错误；Python 单元测试 **126 passed**；`SEEDBRIDGE_INTEGRATION=1` 全套 pytest **133 passed in 17.91s**，JUnit 位于 `runs/stage2-closure-pytest.xml`；Go 单元测试通过；Go 原生集成在四个 fixture 上均通过。新增测试覆盖实际观察结束截尾、符号工具/结果错误闭合分类、无效模型与 timeout 负结果保留，以及 Go 原生错误优先于同时发生的 timeout。每个 fixture 的 30 条 warmup 原生序列可按相同 seed 精确重复，真实前缀经 restart 后 observer 开关两侧的 calldata、status、gas、block/timestamp、state root、coverage digest 和 admission 一致。bootstrap 成功校验补丁、构建 adapter，并编译四个 fixture；doctor 的 Forge、solc、Halmos、crytic-compile、Z3、Go、adapter 和 Python 检查全部为 OK。
