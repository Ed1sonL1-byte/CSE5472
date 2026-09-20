# SeedBridge — Symbolic Seed Augmentation

SeedBridge 是 CSE 5472 semester project 的本地工具原型：把 Medusa 实际执行过的具体调用前缀交给 Halmos，只求解下一步的一个参数，再将经过具体重放验证的序列回灌 Medusa。

Stage 1 使用两个无害教学状态机验证跨工具流程。Stage 2 保留这两个场景，新增容易探索的 `RangeGate` 和 goal 后仍可继续变化的 `WorkflowGate`，让已验证种子真正参加 Medusa mutation，并在同一总 wall-clock 预算下比较三种策略。正式矩阵的 4 × 5 × 3 共 60 条结果全部通过完整性审计。Stage 3 增加版本化 study、真实观察边界、隔离缓存、紧凑原始事件、独立审计和离线归档，在两档总预算与三档目标调用限额下完成 320/320 条有效记录。

设计、结果与证据分别见 [Stage 1 Tech Plan](docs/STAGE1_TECH_PLAN.md)、[Stage 2 Tech Plan](docs/STAGE2_TECH_PLAN.md)、[Stage 2 benchmark 说明](docs/STAGE2_BENCHMARKS.md)、[Stage 2 验收记录](docs/STAGE2_VALIDATION.md)、[Stage 3 Tech Plan](docs/STAGE3_TECH_PLAN.md)、[Stage 3 Results](docs/STAGE3_RESULTS.md)、[Stage 3 验收记录](docs/STAGE3_VALIDATION.md) 和 [Stage 3 证据索引](evidence/stage3/INDEX.md)。[英文项目报告](docs/PROJECT_REPORT.md) 汇总完整方法、实验、失败历史和限制。目标可达不等于发现漏洞；四个自建场景的结果也不代表第三方合约上的性能。

## 流程与支持范围

```text
Medusa 执行与原生语料
  → 选择目标尚未成立的具体前缀
  → Halmos 独立检查前缀重放
  → 求解下一步 uint256 参数
  → Forge 在新部署上具体重放
  → 原生 codec 导出 seed
  → Medusa 重启执行并确认 mutation admission
  → 默认 generator / mutator 继续探索并记录真实父子 lineage
  → JSON / Markdown 报告
```

- 四个内置 fixture：`phase_counter`、`bounded_ledger`、`range_gate` 和 `workflow_gate`。
- 每个 fixture 固定一个目标合约和 actor；前缀包含 1–3 个成功调用，随后追加一个单参数 `uint256` 调用。
- `msg.value = 0`；目标不依赖时间、gas、自身地址或复杂跨交易副作用。
- 比较 fixture 声明的有限状态投影，不宣称完整 EVM 世界状态等价。
- 一个 worker、一轮批次回灌；求解和运行预算写入报告。

| Fixture | 用来验证什么 |
| --- | --- |
| `PhaseCounter` | 狭窄整数条件；验证符号 seed 能否补足普通具体输入难以命中的目标 |
| `BoundedLedger` | 独立记账状态与不变量；检验同一核心流程是否跨场景复用 |
| `RangeGate` | 宽范围条件；观察普通边界输入已有效时的额外增强成本 |
| `WorkflowGate` | 分段条件及 goal 后行为；观察增强与 continuation 时间的取舍 |

四者都没有真实资金、外部调用或攻击载荷。它们用于验证集成和受控比较，不是安全漏洞 benchmark。

## 环境与安装

从仓库根目录执行以下命令。预先准备 `uv`、Go 1.26.4 和 Forge 1.3.2；Python 版本由 `.python-version` 指定为 3.12。bootstrap 不负责安装 Go 或 Forge。

| 组件 | 固定版本／来源 |
| --- | --- |
| Python | 3.12，项目 `.venv` |
| Go | 1.26.4，构建薄适配器时使用 `GOTOOLCHAIN=local` |
| Forge | 1.3.2 |
| solc | 0.8.36，显式二进制路径 |
| Halmos | 0.3.3，由 `uv.lock` 锁定 |
| crytic-compile | 0.3.11，由 `uv.lock` 锁定 |
| Z3 | 4.12.6，使用项目锁定环境中的版本 |
| Medusa | v1.5.1，作为 Go module 依赖构建进 `.bin/medusa-adapter` |

```sh
./scripts/bootstrap.sh
./seedbridge doctor
```

bootstrap 执行 `uv sync --frozen`，必要时安装 solc 0.8.36，复制并校验 Medusa v1.5.1 的最小 lineage 补丁，构建 Go 适配器，将 doctor 结果写入 `configs/toolchain.local.json`，再编译四个固定 fixture。首次安装需要能够取得锁定依赖。现有全局 Z3 不作为项目求解器；不需要另外安装 Medusa CLI。

solc 默认使用以下已安装二进制：

```text
$HOME/.solc-select/artifacts/solc-0.8.36/solc-0.8.36
```

如编译器位于其他目录，先设置其绝对路径，再运行 bootstrap 和后续命令：

```sh
export SEEDBRIDGE_SOLC="/absolute/path/to/solc-0.8.36"
./scripts/bootstrap.sh
```

bootstrap 使用 `solc-select install`，不执行 `solc-select use`，因此不切换全局默认编译器。工具子进程通过显式编译器配置执行。

请使用根目录的 `./seedbridge` 启动器。它自动设置 `PYTHONPATH=src` 并使用锁定的 Python 环境，也避开 macOS 将 editable 安装的 `.pth` 标为 hidden 时产生的导入问题。

`doctor` 检查路径、版本和构建来源。检查通过仅说明环境就绪，不能替代端到端验收。

## 运行 Stage 1 单场流程

```sh
./seedbridge run phase_counter
./seedbridge run bounded_ledger
./seedbridge run range_gate
./seedbridge run workflow_gate
```

每次运行使用独立的 `runs/<run-id>/` 目录。命令会打印状态及 `report.md` 的位置。指定输出目录时必须使用尚不存在的目录：

```sh
./seedbridge run phase_counter --seed 1 --output runs/phase-counter-review
```

可调整的参数：

| 参数 | 含义 |
| --- | --- |
| `--seed` | 传给适配器的随机种子；其复现边界见下一节 |
| `--warmup-tests` | warmup 的完整序列数量上限 |
| `--max-prefixes` | 最多选择多少个具体前缀进入后续检查 |
| `--process-timeout` | 单个原生命令的外层运行时间限制 |
| `--total-solve-timeout` | 本轮累计求解预算 |
| `--output` | 新建的运行产物目录 |

具体默认值以 `./seedbridge run --help` 为准。达到预算而没有目标模型是未找到 witness，不是“目标不可达”。

重新生成某次运行的 Markdown 报告：

```sh
./seedbridge report RUN_PATH
```

将 `RUN_PATH` 替换为已有 run 目录，例如 `runs/phase-counter-review`。这个命令读取已有 `report.json`，不重新执行求解或重放。

## 运行 Stage 2 campaign 与 benchmark

冻结配置位于 `configs/stage2-benchmark.json`。单个 arm、完整 60 槽位矩阵和纯离线报告分别使用：

```sh
./seedbridge campaign phase_counter symbolic_augment --repeat 1 --output runs/campaign-review
./seedbridge benchmark --config configs/stage2-benchmark.json --output runs/stage2-review
./seedbridge benchmark-report runs/stage2-review
uv run --frozen python scripts/audit-stage2.py runs/stage2-review --output runs/stage2-review/audit.json
uv run --frozen python scripts/build-stage2-evidence.py
```

三个 arm 是 `native_resume`、`concrete_augment` 和 `symbolic_augment`。每个 `(fixture, repeat)` 只执行一次共同 warmup，三组从相同 corpus 副本开始；共同成本分别计入每组的 8 秒总预算。未命中按实际计费观察结束时间右截尾，8 秒只作为预算上限另行保存。原始运行保存在被 Git 忽略的 `runs/`，小型、无本机绝对路径的证据保存在 `evidence/stage2/`。

## 运行与复核 Stage 3 study

正式配置位于 `configs/stage3-study.json`，展开为 320 个不同槽位和 40 个共同区组。先检查矩阵；正式运行的输出目录必须不存在：

```sh
./seedbridge study-plan --config configs/stage3-study.json
./seedbridge study --config configs/stage3-study.json --output runs/stage3-review
```

运行只能在已核验的完整 common-block 边界恢复，并会核对冻结配置、源码内容和 adapter 哈希：

```sh
./seedbridge study --resume --config configs/stage3-study.json \
  --output runs/stage3-review
```

从原始 gzip JSONL 独立审计和离线生成报告：

```sh
./seedbridge study-audit runs/stage3-review \
  --output runs/stage3-review/derived/audit.json
./seedbridge study-report runs/stage3-review \
  --output runs/stage3-review/derived
```

完整归档包含冻结源码、配置、compact 原始记录、native seed、模型/重放证据、派生报告、逐文件校验和与标准库重建脚本：

```sh
./seedbridge study-export runs/stage3-review \
  --output artifacts/stage3-review.tar.gz
./seedbridge study-verify-archive artifacts/stage3-review.tar.gz \
  --output runs/stage3-review-offline-verify
```

正式 `stage3-formal-v1` 的结果是 320/320 valid、243 个 goal-hit 槽位、791,282 条完整序列和 553,708 条 mutation。完整档案的 SHA-256 为 `91bf6e5063a4d7644e0f84a1c8187480a35c66185e4f929d275384db6ad2ad25`；其 3.1 GB 单文件被 Git 忽略，本地路径和两次离线重建哈希记录在 `evidence/stage3/archive.json`。可提交的小型证据包包含全部 320 行 observations、审计、结构化汇总和图表。

## Warmup 与随机种子的边界

Stage 1 warmup 采用 Medusa 原生的 **new-sequence-only generator** 固定策略，并使用单 worker，以减少语料 mutation 调度对集成复现的影响。具体调用仍由原生生成器产生；编排器不手写目标调用顺序或目标解。

这是一项明确的实验配置，不等同于 stock Medusa 的默认调度策略。因此，Stage 1 的覆盖率、耗时或目标命中结果不能用于宣称优于原生 Medusa。

`--seed` 只保证控制到的随机源使用给定种子，不是整个工具链完全确定性的承诺。跨版本、不同构建产物、solver 行为及 wall-clock 截止均可能影响结果。复现应使用报告中的实际工具版本、有效配置、原生语料和已确认序列；不要仅凭种子相同就声称执行一致。

回灌验收分别检查 seed 被执行，以及进入 mutation 候选集合。进入该集合不代表已经证明后续 mutation 有效果，也不代表 fuzzing 性能提升。

Stage 2 campaign 恢复 Medusa v1.5.1 的默认生成和 mutation 策略。仓库内固定版本补丁只暴露现有策略选出的 generation id 与真实父代，不增加随机调用或改变权重。worker seed、运行顺序和导入顺序受控；Medusa 内部 clock-seeded corpus 与 mutation strategy chooser 仍属于明确记录的非受控随机源，因此五个 repeat 是独立重复，不是逐位相同的随机轨迹。

## 运行产物与验收证据

入口是每次运行的 `report.md` 和 `report.json`。其余文件的实际路径由 JSON 报告及生成的 manifest 记录。

| 产物 | 用途 |
| --- | --- |
| `report.md` | 查看总体状态、原生往返、observer 对照、候选求解／重放／admission 结果 |
| `report.json` | 保存结构化结果、版本与摘要、配置、阶段耗时、错误原因及证据路径 |
| 原生 corpus 与 seed | 保留真实 Medusa 调用序列；codec 导出的新序列可用于重启执行 |
| 规范化 prefix | 串联来源摘要、actor、目标、calldata、实际区块上下文和逐步观测 |
| 生成的 Foundry 项目与 manifest | 保存前缀检查、目标求解和具体重放所用代码与上下文 |
| Halmos 原始 JSON 与日志 | 检查目标测试身份、typed model、warning、界限和未完成原因 |
| Forge 与 Medusa 执行记录 | 确认具体调用成功、状态匹配、目标变化及原生 admission |
| `novelty.json` | 保存候选 Medusa hash、warmup hash 集合及逐项去重结论 |
| `lineage.jsonl` | 记录 startup replay、new sequence、mutation、真实父代和实际执行结果 |
| `metrics.json` / `coverage.json` / `states.json` | 分开保存序列、有限状态和目标 runtime coverage 的 warmup/import/continuation 集合 |
| `campaign.json` | 保存 Stage 2 各阶段状态、总预算计费、合法未命中及工具／证据错误分类 |
| `summary.{json,csv,md}` | 从原始事件离线生成 60 条逐次结果与分组汇总 |
| `events.jsonl.gz` / `events.meta.json` | Stage 3 compact v2 原始执行、native payload、前缀引用、lineage、时点、EOF 和校验和 |
| `manifest.json` / `frozen-config.json` | Stage 3 完整区组、预注册矩阵、执行源码与工具哈希、缓存协议和恢复边界 |
| `derived/audit.json` | 不复用生产指标函数的 320 槽位独立原始记录审计 |
| `derived/summary.*` / `derived/*.svg` | 预算、目标调用限额、逐槽观测、成本和未命中原因的离线报告 |
| `artifacts/*.tar.gz` | 自包含完整档案；含逐文件 manifest、冻结源码和标准库重建入口，不提交大文件本体 |

一次场景运行只有同时取得以下证据，才应标记为 `stage1_confirmed`：

1. 原生语料能无损往返；observer 不改变状态、执行结果、覆盖反馈或 admission。
2. 所选 prefix 确实来自 Medusa 执行，且重放身份、outcome 和声明的状态投影一致。
3. 指定目标测试返回有效模型；新部署具体重放使目标从 false 变为 true。
4. 候选不是已有完整序列的重复，且由重启后的真实 Medusa 执行。
5. 有序列完成后进入 mutation 候选集合的独立证据。

两个 fixture 都满足这些条件，才构成 Stage 1 的完整验收。模型存在、CLI 返回 0、报告文件存在或 native seed 被写入，均不能单独替代这些证据。

## 状态与失败排查

| 状态／现象 | 含义与优先检查项 |
| --- | --- |
| `candidate` | 得到可解析目标模型，尚未通过具体重放和回灌 |
| `reachable_confirmed` | 具体重放确认目标成立，尚需检查原生回灌和 admission |
| `result_mismatch` | 原生工具返回的测试数量、身份或进程结果与 JSON 结果不一致 |
| `tool_error` | 检查对应进程日志、编译结果和工具版本 |
| `timeout` / `stuck` / `all_paths_reverted` | 本轮执行或求解未完成；检查预算、上下文及合法前置步骤 |
| `no_witness_within_bounds` | 配置界限内没有目标模型，不是不可达证明 |
| `invalid_model` / `decode_error` | 模型有效性、变量名、类型或范围不符合接口，不应回灌 |
| `state_mismatch` / `observer_mismatch` | 编译目标、原生重放状态或 observer 对照证据不一致 |
| `prefix_mismatch` / `replay_mismatch` / `candidate_rejected` | 检查源码与构建摘要、actor、原生地址绑定、calldata 和逐步状态 |
| duplicate / 目标已成立 | 跳过重复序列或不需要求解的前缀，不计作新增种子 |
| `admission_unverified` | 已执行或已导出不足以证明进入 mutation 集合，仍不能完成验收 |

`run` 仅在总体状态为 `stage1_confirmed` 时返回成功退出码。报告重渲染的成功退出码只说明报告已生成。

## 测试

Python 单元测试从仓库根目录运行：

```sh
uv run --frozen pytest tests/unit -q
```

完整验收包含四个端到端流程、四套 Forge 具体测试，以及 Go 原生往返／观察对照／lineage 检查：

```sh
SEEDBRIDGE_INTEGRATION=1 uv run --frozen pytest -q
```

Go 测试从适配器目录运行：

```sh
cd adapters/medusa
GOTOOLCHAIN=local go test -mod=readonly ./...
```

单元测试主要检查数据校验、模型解析、重放接受条件和进程清理；端到端实测与通过统计由 `docs/STAGE1_VALIDATION.md` 单独记录。

Stage 3 还要求配置展开、compact corruption、时间边界、隔离缓存、完整区组恢复、独立审计和离线归档测试。正式证据核查使用：

```sh
./scripts/audit-stage3-protocol.py
./seedbridge study-audit runs/stage3-formal-02
./scripts/build-stage3-evidence.py
(cd evidence/stage3 && shasum -a 256 -c checksums.sha256)
```

完整原始 run 被 `.gitignore` 排除；公开仓库中的 `evidence/stage3/` 是路径清理后的审计与逐槽结果，不替代本地完整档案。

## 目录与来源

| 路径 | 内容 |
| --- | --- |
| `src/seedbridge/` | Python CLI、配置、序列选择、求解、预算、campaign、指标与报告 |
| `adapters/medusa/` | Go 原生 codec、执行观察、continuation 与固定版本 lineage 接入 |
| `fixtures/` | 四个教学状态机与 Foundry 配置、测试 |
| `configs/stage2-benchmark.json` | 冻结的正式实验矩阵、预算、顺序和随机种子 |
| `configs/stage3-study.json` | 冻结的 320 槽位预算/调用限额矩阵、顺序和随机种子 |
| `evidence/stage2/` | 路径清理后的正式汇总、机制链条、审计结果和校验和 |
| `evidence/stage3/` | 320 槽位逐次结果、独立审计、图表、协议与归档验证索引 |
| `artifacts/` | 本地完整离线档案说明与已跟踪的 SHA-256 文件；大档案本体忽略 |
| `scripts/bootstrap.sh` | 锁定依赖安装和适配器构建 |
| `scripts/build-stage3-evidence.py` | 从冻结正式 run 构建路径清理后的 Stage 3 小型证据包 |
| `tests/unit/` | Python 单元测试 |
| `runs/` | 每次运行的原始证据和报告 |
| `docs/STAGE1_TECH_PLAN.md` | S0–S6 的范围、验收与产出 |
| `docs/STAGE2_TECH_PLAN.md` | P0–P5 的范围、完成状态、验收与产出 |
| `docs/STAGE3_TECH_PLAN.md` | P0–P6 的范围、完成状态、验收与产出 |
| `docs/STAGE3_RESULTS.md` | Stage 3 RQ1–RQ3、成本、负结果和限制 |
| `docs/PROJECT_REPORT.md` | 英文课程项目报告草稿 |
| `output/pdf/` | 课程 proposal 及其生成材料 |

项目建立在 [Medusa](https://github.com/crytic/medusa)、[Halmos](https://github.com/a16z/halmos) 和 [Foundry](https://github.com/foundry-rs/foundry) 上。[Optik](https://github.com/crytic/optik) 已有符号执行辅助 fuzzing 的相关实践；本项目的定位是受限接口集成与评估，不将 hybrid fuzzing 本身作为新的方法。
