# Stage 1 验收记录

**结果：两个内置 fixture 均完成 Stage 1 的完整流程。** 验收限于仓库自建状态机的可达性集成；不代表已发现漏洞或证明相对基线的性能提升。

## 最终验收入口

```sh
./scripts/bootstrap.sh
SEEDBRIDGE_INTEGRATION=1 uv run --frozen pytest -q --junitxml=runs/validation/pytest.xml
```

实际结果为 **84 passed，0 failures，0 errors，0 skipped**：79 个 Python 单元检查和 5 个原生工具集成入口。两个 fixture 集成入口运行了 8 个 Forge 具体测试；Go 集成入口对两个 fixture 分别验证真实序列往返、getter 开关对照和重复运行的确定性。

此外单独执行 `go test -mod=readonly -count=1 -json ./...`，Go codec 单元测试通过；该次默认跳过的原生集成测试已经由上面的完整 pytest 命令显式运行。不能将嵌套测试的数量重复累计为独立实验样本。

以下为本次工作区中的本机证据路径；`runs/` 与 `configs/toolchain.local.json` 包含本机路径并由 `.gitignore` 排除。公开仓库可按上述命令生成同结构的新记录。

- pytest JUnit：`runs/validation/pytest.xml`
- Go 单元测试原始结果：`runs/validation/go-tests.json`
- 实际本机工具链记录：`configs/toolchain.local.json`

## 两个端到端结果

各运行由 Medusa 原生生成器产生 40 个完整调用序列，从实际执行记录选择前缀；使用同一核心编排代码。目标值由 Halmos 模型产生，没有在 Python 中硬编码求解结果。

| Fixture | 具体前缀末状态 | 模型参数 | 最终状态 | 验收 |
| --- | --- | --- | --- | --- |
| PhaseCounter | `(phase=2, counter=9, unused=0, goal=false)` | `74` | `(3, 9, 0, true)` | `stage1_confirmed` |
| BoundedLedger | `(phase=2, total=21, reserved=14, goal=false)` | `160` | `(3, 21, 14, true)` | `stage1_confirmed` |

本次工作区证据入口：

- PhaseCounter：`runs/phase_counter-eb63c3fc051a/report.md`、`report.json`、`scenario.json`、`attempt-0/novelty.json`
- BoundedLedger：`runs/bounded_ledger-4f77019641ba/report.md`、`report.json`、`scenario.json`、`attempt-0/novelty.json`

两份报告均确认：原生 codec 往返与重启、getter 观察开关对照、独立前缀检查、有效目标模型、新部署具体重放、原生完整序列执行及 mutation admission。PhaseCounter 候选 hash 不在 96 个 warmup hash 中，BoundedLedger 候选 hash 不在 101 个 warmup hash 中；完整集合和比较结果保存在各自的 `novelty.json`。各阶段检查基线源码与目标字节码摘要；最后一步也核对实际 sender、calldata、value、block 和 timestamp。

原始序列、生成的 Solidity、模型 JSON、Forge 输出、Medusa 观察及 coverage digest 均保留在各 run 目录，具体路径记录于 `report.json`。这些目录由 `.gitignore` 排除，复制或分享验收材料时需要一并带上，或按命令重新生成。

## 各部分验收与产出

| 部分 | 已通过的验收 | 产出 |
| --- | --- | --- |
| S0 环境 | doctor 检查通过；实际编译配置与跨执行器目标字节码一致 | Python / Go 锁文件、bootstrap、toolchain manifest |
| S1 fixture | 两合约各 4 个具体测试通过；目标与不变量分开 | 两个 Foundry 项目、共同观察接口、场景注册表 |
| S2 原生序列 | 各 fixture 的 30 个序列在重复运行中一致；往返后真实重启；getter 开关的 receipt、状态根、上下文、覆盖摘要与 admission 一致 | Go adapter、原生 JSON、逐步观察与完成事件证据 |
| S3 前缀与 harness | 从真实生成序列选择前缀，自动重建并通过逐步状态检查 | PrefixCase、选择器、自动生成 Solidity 与 manifest |
| S4 求解 | 两 fixture 都生成 typed model；真实 0.3.3 输出解析测试通过 | Halmos runner、原始模型、参数文件、错误分类 |
| S5 回灌 | 两非重复完整序列具体重放为真，之后由 Medusa 实际执行并接纳 | Forge 测试、`novelty.json`、native seed、原生重放及 admission 证据 |
| S6 CLI 与文档 | 完整测试套件通过，报告可从保存的 JSON 重新生成 | `doctor/run/report`、README、tech plan、验收记录 |

## 负向与完整性检查

测试覆盖错误前缀状态、缺少必要阶段、目标预先成立、回滚或非零 value、错误 actor／target、ABI metadata 与 calldata 不一致、无效或错误来源模型、uint256 边界、缺失／损坏结果、超时进程组清理、编译产物变化、最后一步上下文变化和缺少 admission 证据。具体重放另行覆盖成功、断言不匹配、进程／JSON 不一致、不可读输出和超时；管线分别保留外层原生工具的 `timeout` / `tool_error` 与证据验证的 `state_mismatch` / `observer_mismatch` 分类。

实际负向 Halmos 检查中，将 BoundedLedger 前缀记录的 total 从 12 改为 13：独立检查返回 `prefix_mismatch`；目标测试返回 `all_paths_reverted` 且没有模型。其余错误分类和数据边界由单元测试覆盖。

## 结果边界

- warmup 是固定的原生 random/new-sequence-only 配置，未用作 stock Medusa 的性能对照。
- 选择的是实际执行的原生序列快照；它不一定是 Medusa 按覆盖反馈独立持久化的 corpus 项。
- 对比的是 fixture 声明的有限状态，未证明完整跨执行器世界状态等价。
- admission 根据固定 v1.5.1 的控制流和完成事件确认，没有直接检查私有 chooser，也没有声称观察到该种子随后被选中变异。
- 第三个场景、更多参数类型、长前缀、预算策略及公平性能评估属于后续阶段。
