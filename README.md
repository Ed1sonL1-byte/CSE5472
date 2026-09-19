# SeedBridge — Stage 1

SeedBridge 是 CSE 5472 semester project 的本地工具原型：把 Medusa 实际执行过的具体调用前缀交给 Halmos，只求解下一步的一个参数，再将经过具体重放验证的序列回灌 Medusa。

Stage 1 使用仓库内两个无害教学状态机，验证跨工具流程和证据是否可靠。两个场景已通过端到端验收；84 项 pytest 检查全部通过，其中包含实际原生工具集成。验收范围与证据见 [STAGE1_VALIDATION.md](docs/STAGE1_VALIDATION.md)。目标可达不等于发现漏洞，也不构成性能提升结论。

完整设计见 [Stage 1 Tech Plan](docs/STAGE1_TECH_PLAN.md)。

## 流程与支持范围

```text
Medusa 执行与原生语料
  → 选择目标尚未成立的具体前缀
  → Halmos 独立检查前缀重放
  → 求解下一步 uint256 参数
  → Forge 在新部署上具体重放
  → 原生 codec 导出 seed
  → Medusa 重启执行并确认 mutation admission
  → JSON / Markdown 报告
```

- 两个内置 fixture：`phase_counter` 和 `bounded_ledger`。
- 每个 fixture 固定一个目标合约和 actor；前缀包含 1–3 个成功调用，随后追加一个单参数 `uint256` 调用。
- `msg.value = 0`；目标不依赖时间、gas、自身地址或复杂跨交易副作用。
- 比较 fixture 声明的有限状态投影，不宣称完整 EVM 世界状态等价。
- 一个 worker、一轮批次回灌；求解和运行预算写入报告。

| Fixture | 用来验证什么 |
| --- | --- |
| `PhaseCounter` | 通过具体调用建立阶段和计数器状态，再求解能进入目标阶段的参数 |
| `BoundedLedger` | 用不同的整数记账状态复用相同编排流程，并分别检查目标标志和记账不变量 |

两者都没有真实资金、外部调用或攻击载荷。它们证明集成机制是否工作，不是安全漏洞 benchmark。

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

bootstrap 执行 `uv sync --frozen`，必要时安装 solc 0.8.36，构建 Go 适配器，将 doctor 结果写入 `configs/toolchain.local.json`，再编译两个固定 fixture。首次安装需要能够取得锁定依赖。现有全局 Z3 4.13.0 不作为项目求解器；不需要另外安装 Medusa CLI。

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

## 运行两个场景

```sh
./seedbridge run phase_counter
./seedbridge run bounded_ledger
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

## Warmup 与随机种子的边界

Stage 1 warmup 采用 Medusa 原生的 **new-sequence-only generator** 固定策略，并使用单 worker，以减少语料 mutation 调度对集成复现的影响。具体调用仍由原生生成器产生；编排器不手写目标调用顺序或目标解。

这是一项明确的实验配置，不等同于 stock Medusa 的默认调度策略。因此，Stage 1 的覆盖率、耗时或目标命中结果不能用于宣称优于原生 Medusa。

`--seed` 只保证控制到的随机源使用给定种子，不是整个工具链完全确定性的承诺。跨版本、不同构建产物、solver 行为及 wall-clock 截止均可能影响结果。复现应使用报告中的实际工具版本、有效配置、原生语料和已确认序列；不要仅凭种子相同就声称执行一致。

回灌验收分别检查 seed 被执行，以及进入 mutation 候选集合。进入该集合不代表已经证明后续 mutation 有效果，也不代表 fuzzing 性能提升。

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

完整验收包含两个端到端流程、八个 Forge 具体测试，以及 Go 原生往返／观察对照／确定性检查：

```sh
SEEDBRIDGE_INTEGRATION=1 uv run --frozen pytest -q
```

Go 测试从适配器目录运行：

```sh
cd adapters/medusa
GOTOOLCHAIN=local go test -mod=readonly ./...
```

单元测试主要检查数据校验、模型解析、重放接受条件和进程清理；端到端实测与通过统计由 `docs/STAGE1_VALIDATION.md` 单独记录。

## 目录与来源

| 路径 | 内容 |
| --- | --- |
| `src/seedbridge/` | Python CLI、配置、序列选择、harness、求解、重放与报告 |
| `adapters/medusa/` | Go 原生 codec、执行观察和回灌适配器 |
| `fixtures/` | 两个教学状态机与 Foundry 配置、测试 |
| `scripts/bootstrap.sh` | 锁定依赖安装和适配器构建 |
| `tests/unit/` | Python 单元测试 |
| `runs/` | 每次运行的原始证据和报告 |
| `docs/STAGE1_TECH_PLAN.md` | S0–S6 的范围、验收与产出 |
| `output/pdf/` | 课程 proposal 及其生成材料 |

项目建立在 [Medusa](https://github.com/crytic/medusa)、[Halmos](https://github.com/a16z/halmos) 和 [Foundry](https://github.com/foundry-rs/foundry) 上。[Optik](https://github.com/crytic/optik) 已有符号执行辅助 fuzzing 的相关实践；本项目的定位是受限接口集成与评估，不将 hybrid fuzzing 本身作为新的方法。
