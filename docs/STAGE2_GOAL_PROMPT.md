# Stage 2 Goal Prompt

将下面的内容作为新 goal 的 prompt。完整工作与验收约定见 [STAGE2_TECH_PLAN.md](STAGE2_TECH_PLAN.md)。

```text
在 /Users/edisonli/Desktop/CSE5472 中完成 SeedBridge Stage 2。负责人是 Edison Li。

先阅读 README.md、docs/STAGE1_VALIDATION.md 和 docs/STAGE2_TECH_PLAN.md，核对当前工作区及版本，以现有 Stage 1 为基础实施 Stage 2 技术计划。不要重建项目，不覆盖用户已有修改。创建并持续推进一个 goal，直到计划的必需工作与验收完成；不要添加开发日程或工时估算。

目标：让验证过的符号种子真正参与 Medusa 后续 mutation，并在同一总运行预算内，完成四个仓库自建教学状态机上三种策略、各五次重复的公平比较。收益为零或负值可以是有效结论，不以必须跑赢基线作为验收条件。

必须完成：
1. 保留 Stage 1 集成模式及验收，补齐所有成功、失败和超时路径的计时与结果记录。
2. 新增 native campaign 模式，恢复 Medusa 默认生成/mutation 策略，区分 startup replay 与 continuation。
3. 先解决真实 seed 父子关系的证据。核查 pinned v1.5.1 接口；必要时制作仅用于记录的最小版本固定补丁，三个 arm 使用相同构建。至少在一个受控机制测试中证明：符号 seed 被实际选中、产生调用内容不同的子代、子代真实执行。不能将 admission、单 seed 目录或相似前缀当作 lineage 证据。
4. 按计划加入 range_gate 和 workflow_gate，使总计四个场景包含容易命中的对照及 goal 后仍有行为的状态机。保持固定 actor、零金额、一个 uint256 符号参数、短前缀、单 worker 和一次增强批次；只支持仓库自建的无害 fixture。
5. 独立记录序列去重、有限状态投影及 native coverage 集合。分别计算 import 与 continuation 收益，保存可核查的事件和父子记录。
6. 实现 native_resume、concrete_augment、symbolic_augment 三个 arm。遵守共同 warmup、相同前缀及导出上限、固定缓存规则和包含全部编译/求解/验证/重启成本的总预算。不事后匹配成功种子数，不给 solver 免费运行时间。
7. 先跑机制与三组 smoke 检查，再冻结实验配置并完成 4×5×3=60 个 evaluation_valid=true 的正式结果。合法未命中和求解超时可以有效；保存无合格前缀及重试历史，工具错误和完整性错误单独处理。修复后重跑受影响的完整比较块；截止后事件保存但不进入主指标。A 准确标记为共同语料重启的默认策略对照，不能冒称不中断的 unmodified Medusa。明确未控制随机源，不能承诺整个 fuzzing 轨迹确定。
8. 交付可用 CLI、适配器及补丁来源、四个 fixture、配置、测试、原始实验记录、CSV/JSON/Markdown 汇总与图表、可离线重建的报告、README、docs/STAGE2_BENCHMARKS.md、docs/STAGE2_VALIDATION.md 和 evidence/stage2/ 小型证据包。

验收以 docs/STAGE2_TECH_PLAN.md 的清单为准。运行必要的 Python、Go 和原生集成检查，验证关键计时、去重、coverage 差集、父子证据及报告重建；记录实际结果，不预设测试数量。测试通过之后不要无理由反复跑同一检查。

每完成一个工作包就更新实现状态与证据位置，并继续下一项。真实接口阻塞必须明确报告，未取得证据的能力标为 unverified，不虚构结果或用替代指标冒充完成。不扩展到第三方目标、真实资产、多步符号执行或复杂调度。

最终报告说明：实现了什么、实际验收结果、三组比较结果、证据入口和仍存在的限制。只有机制、正式评估与交付物均满足计划，才将 goal 标记为完成；如果效果不佳，如实分析成本和原因。
```
