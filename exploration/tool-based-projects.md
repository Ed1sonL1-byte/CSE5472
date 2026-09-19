# 基于现有 fuzzing / symbolic 工具的 semester project 候选

2026-09-07。根据最新讨论，优先探索现有分析工具的扩展。以下均为候选设计；本轮完成文档与源码调查，未运行这些组合的端到端实验，未选定提交题目。

## 选择原则

复用成熟的执行器、编译支持和约束求解，把自行实现的工作集中在一个明确的测试机制。课程贡献可以是有用、可复用、经过对照评估的工具扩展，不需要宣称新的通用分析算法。界面和串行运行多个工具不能独自构成主要增量。

| 基础工具 | 可以复用的能力 | 扩展注意点 |
| --- | --- | --- |
| [Medusa](https://github.com/crytic/medusa) | 覆盖反馈、交易序列、语料库、缩减、Go hooks | 定制 sender 与序列拼接可能需要小幅修改 generator；固定版本 |
| [Halmos](https://github.com/a16z/halmos) | Solidity/Foundry 风格的符号测试与有界状态探索 | 求解目标和安全性质需定义；超时及不支持不等于安全 |
| [Slither](https://github.com/crytic/slither) | 解析、变量读写、调用与数据依赖等分析 API | 辅助生成测试，不能自动恢复完整的正确业务政策 |
| [Echidna](https://github.com/crytic/echidna) | 属性驱动的交易序列 fuzzing、覆盖语料与缩减 | 本身已结合 Slither；首版选择一个 fuzzer 后端即可 |

## A. 具体前缀驱动的符号种子增强

可能的题目：**Symbolic Seed Augmentation for Stateful Smart-Contract Fuzzing**。

用户：已有 Medusa 测试的合约开发者。问题：fuzzer 已到达有意义的状态，但难以生成满足后续数值／状态条件的输入，有限的符号执行预算能否帮助它探索并暴露安全性质违反？

方法：

1. 运行 Medusa，读取其已有合法调用序列。
2. 选一个具体前缀，自动生成 Solidity harness 重放；保持 sender、value、时间、区块与部署语义一致。
3. 仅将最后一个调用的参数设为符号量，由 Halmos 求解用户声明的可达性目标。
4. 将模型转换为 calldata，在具体执行器中重新运行。验证成功且有用的序列加入下一轮 fuzzing；安全漏洞仍由独立的安全性质判定。

自行实现：语料格式转换、前缀选择与预算分配、harness 生成、模型解码、具体重放和批次式回灌。核心可检验机制是保留可达的具体状态构建过程，仅在短后缀上花费求解预算。

实际接口依据：[Medusa corpus](https://github.com/crytic/medusa/blob/master/fuzzing/corpus/corpus.go)；[Halmos 状态测试](https://a16zcrypto.com/posts/article/modern-invariant-testing-with-halmos/)；[Halmos 模型](https://github.com/a16z/halmos/blob/main/src/halmos/solve.py)。Halmos JSON 模型不等于现成的分支翻转接口，需要自行构造目标测试。例如 `assert(!goal)` 的反例可以提供达到目标的种子，但不能直接作为安全漏洞报告。

最接近的已有工作是 [Optik](https://github.com/crytic/optik)：它已使用 Maat 重放 Echidna corpus、约束求解产生新输入，并结合 Slither 做增量种子生成。[ConFuzzius](https://arxiv.org/abs/2005.12156) 和 [ItyFuzz](https://github.com/fuzzland/ityfuzz) 也已有混合分析。不能把连接 fuzzing 与 symbolic execution 或语料回灌描述成首次提出。这里的课程贡献是现代后端适配、受限后缀策略和实证评价。

首版边界：本地固定部署，基本 ABI 类型，有限 actors，4–6 步以内具体前缀加一步符号后缀。具体长度是计划边界，仍需实验调整。优先重放合法调用重建状态，不直接导入任意引擎 snapshot。两个后端的语义一致性是主要工程风险。

对照：原生 Medusa；同样前缀加随机／常量边界种子；符号种子增强；可行时加入同样深度的独立 Halmos。所有组共享初始化、actors、目标谓词、安全性质和预算信息；计入编译、求解、重放时间及 CPU 资源。测量缺陷发现、首次发现时间、覆盖增量、种子重放率和未完成比例。覆盖提升不能代替缺陷发现；不能只选自造的精确常量门槛样例。

期中交付：一个合约端到端完成“读取序列—求解—具体重放—重新进入 fuzzing”，并在另一个实现上验证适配可复用。期末加入独立公开案例、多种子和消融。

风险控制：如果循环回灌成本超出预期，核心仍可交付“Medusa 前缀驱动的有界安全检查与 Foundry 反例导出”；自动回灌作为增强能力。新独立案例的可运行性必须在早期预检。

## B. 权限撤销后的定向 fuzzing

可能的题目：**RevokeFuzz: Testing Authorization After Role Changes**。

基础：Medusa，Slither 辅助。

机制：记录 actor 曾经成功执行的敏感调用。在撤权或已完成所有权交接后，保留前缀，优先让旧 actor 重放和变异这些调用；同时检查当前合法 actor 的正向操作。观察敏感状态是否改变，而不是只看是否 revert。

自行实现：撤权边界保留与旧调用重放 mutator、权限状态观察、政策配置与效果断言。政策由用户明确声明；撤销一个角色不意味着该地址失去通过其他角色取得的所有权限，Ownable2Step 发起交接也不意味着交接已经完成。

已有 [SMARTIAN](https://github.com/SoftSec-KAIST/Smartian) 处理数据依赖和调用约束；[SPCon](https://github.com/Franklinliu/SpCon-Artifact) 已研究角色挖掘和权限攻击序列。因此增量应限定为撤权边界的专项变异策略。

范围：Ownable、Ownable2Step、AccessControl 风格的简单非代理项目。基线提供相同 actors、角色常量、函数及安全性质，比较原 Medusa、静态权限种子、增加撤权重放的版本。

数据风险：公开 access-control 漏洞不都涉及撤权。目前未确认足够的独立撤权案例。正确公开实现加明确标注的应用层缺陷变体可做功能验证，不能作为大量真实漏洞检出的替代。若具体案例不足，将题目定位成权限回归测试生成，而不承诺通用漏洞发现优势。

## C. 安全补丁的行为约束检查

可能的题目：**PatchScope: Checking Behavioral Contracts of Security Patches**。

基础：Halmos 进行有界检查，Foundry 具体重放。用户提供两个代码版本、配对部署 fixture、观测量，以及补丁允许改变哪些行为。

方法：

1. 在允许改变的输入域内，检查补丁后的明确安全性质。
2. 在该域外，检查新旧版本的指定行为关系。
3. 将已知漏洞样例的调用骨架保留，对参数做符号探索；检查两个输入域可达，避免空约束或“拒绝所有调用”掩盖问题。
4. 分类和具体重放反例：漏洞未修复、额外行为变化、预期差异、未完成分析。

增量是关系性质生成、允许差异域检查和反例分类。[Diffusc](https://github.com/crytic/diffusc) 已能自动生成升级差分 fuzzing 测试；其[官方说明](https://blog.trailofbits.com/2023/07/07/differential-fuzz-testing-upgradeable-smart-contracts-with-diffusc/)讨论了需要人工调整预期差异。不能把两个版本比较本身作为新增能力。单纯更换执行后端也不足以说明安全价值。

公开数据入口：[OpenZeppelin 安全公告](https://github.com/OpenZeppelin/openzeppelin-contracts/security/advisories)。候选包括 ERC721Consecutive 单元素批量铸造余额修复，以及 ERC165Checker 对非标准返回值的处理修复。公告与源码需固定版本并编译、重放后再纳入评估。本轮仅完成来源核查。

首版同 ABI、局部补丁、明确观测量，单调用为主或2–3步固定短序列。已允许的差异可能造成后续状态不同，必须在该检查点结束比较或由用户定义状态关系，不能继续盲目全等。

对照：原 PoC 重放、普通新旧等价检查、同性质的 Foundry fuzzing、完整工具。测错误补丁检出、正确补丁误拒绝、反例重放率、完成率、时间与适配工作量。合成错误补丁与真实历史补丁分组报告。

主要风险是政策质量和双版本路径数量。非空检查不能证明允许域写得正确；符号执行结论始终有输入、循环和序列界限。

## 当前取舍

- 最直接实践 fuzzing 与 symbolic 协同：A。它有清晰接口工作，但需最先验证跨引擎具体执行一致性。
- 最适合深入修改一个 fuzzer：B。新增代码集中，不过独立撤权案例仍是缺口。
- 补丁使用场景和公开历史版本较明确：C。主要难点从执行接口转为正确表达补丁意图。

优先对 A 与 C 做选择。定题前最有价值的验证分别是：A 用两个不同合约完成一个种子增强回合；C 编译两个公开修复对，并检查一个正常补丁与一个明确错误补丁。无需先建设大型平台。
