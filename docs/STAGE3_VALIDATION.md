# Stage 3 Validation Record

本记录与 [Stage 3 技术计划](STAGE3_TECH_PLAN.md) 同步维护。只有已有实现和实际证据支持的项目才标记完成。Stage 3 的 320 个正式槽位、独立审计和离线档案均已通过。

## P0：封存历史基线与补齐遗留导出

**状态：完成。**

- Stage 2 正式样例只统计 mutation parent selection，仍为 170 次；机制样例使用同一过滤语义，从错误的 111 修正为 110 次，85 个不同且实际执行的子代不变。
- 删除了证据生成器中“必须恰好 170 次”的通用断言。导出只要求样例存在真实 mutation selection。
- 证据生成器不再删除整个 `evidence/stage2`，校验和只覆盖官方文件。现有带“ 2”“ 3”后缀的 34 个未跟踪副本均保留并排除在正式清单之外。
- Stage 3 起始源码、锁文件、配置、patch、fixture、Stage 2 原始记录和副本摘要保存于 `evidence/stage3/baseline.json`。Stage 2 的 60 条正式 campaign 与机制原始记录保持只读。

验收证据：

```text
formal-symbolic-sample selected_as_parent_count = 170, first kind = mutation
mechanism imported_seed_parent_selections = 110, different_executed_children = 85
Stage 2 audit = passed; accepted seeds used = 36/36
Stage 2 official evidence checksums = passed
```

## P1：版本化 StudySpec 和数据驱动矩阵

**状态：完成。**

- `configs/stage3-study.json` 展开为 320 个不同槽位和 40 个公共块：总预算族 240 个槽位，goal invocation limit 对比 120 个槽位，其中 40 个复用、80 个新增。
- `StudySpec` 检查 fixture 白名单、重复／缺失 profile、repeat、seed、顺序、预算和实验族；`study-plan` 可在不运行工具时输出完整矩阵。
- `configs/stage3-smoke.json` 使用相同 schema 运行三组协议 smoke；旧 Stage 2 配置和 60 槽位入口的单元回归保持通过。

## P2：真实时间边界、停止原因与缓存公平性

**状态：完成。**

- Go completion marker 分开记录 search start/stop、last observed event、event stream finish 和 evidence flush finish；Python 将相对时点映射到包含公共成本的逻辑账本，并以最后一条预算内完整事件作为指标观察终点。
- 三组真实 smoke 均以 `time_limit` 停止并有效；受控增加 0.5 秒 flush delay 时，搜索停止和最后观察均早于延迟，延迟只反映在事件写完与计费结束。
- 真实 sequence-limit smoke 被分类为 `sequence_limit`，正式 runner 会将其判为协议证据错误；工具错误优先于 timeout、无前缀、无候选、部分记录和写盘失败有边界测试。
- 每个 profile 从同一公共 cache/corpus 摘要取得独立副本，复制、增强、seed import、启动、搜索和在线证据校验进入账本；prefix check 与 goal invocation 保存 requested/effective limit。

## P3：紧凑原始证据与存储预检

**状态：完成。**

- compact event format v2 每个完整序列只保存一次，携带原生 payload、逐步观察、lineage 和所有已执行前缀的 hash/identity 引用；读取器检查 EOF、字节数、校验和、重复 ID、字典、父代先于子代和 payload 摘要。
- 冻结 Stage 2 正式记录的 60 个 campaign 已全部转换并重算一致：29,259 条完整序列，20,382 mutation；旧报告 5,589,753,302 bytes 对应的 compact 流为 129,776,533 bytes。
- 对三组 smoke 的 mutation payload 用固定 Go codec 独立解码，Medusa hash 全部相同。
- 最终协议 smoke 为 3/3 valid；保守地把整个三组目录按 320 个 profile 放大并再乘 4，最终复核投影为 17,497,258,032 bytes，低于配置的 50 GiB 上限，正式运行前的磁盘预检通过。

验收索引：`evidence/stage3/protocol-audit.json`。

## P4：冻结配置并运行 320 个槽位

**状态：完成。**

- `runs/stage3-formal-02` 使用冻结的 `stage3-formal-v1` 配置、源码快照和 adapter。40/40 个共同区组完整提交，320/320 个槽位为 `evaluation_valid=true`，正式清单中没有失败区组。
- 物理运行一次完成，清单记录 6,675.234 秒。正式记录包含 791,282 条完整序列与 553,708 条 mutation；正常未命中、无候选、无前缀和增强超时均保留。
- `runs/stage3-formal-01` 保留为被替代尝试：完成 10 个 PhaseCounter 区组后，BoundedLedger 第一个区组的 `b32-symbolic-q150` 在增强超时时留下一个未提交的 fresh native candidate，adapter 因 entry/corpus 数量不一致将该 profile 判为 `tool_error`，因此整组不计入正式结果。
- 修复只清理本次 codec 输出中没有提交到 accepted entries 的 orphan，并新增定向回归。由于修复改变执行代码，没有恢复或混用第一轮 80 条记录，而是从新冻结快照完整重跑 320 个槽位。

正式清单：`runs/stage3-formal-02/manifest.json`。路径清理后的副本：`evidence/stage3/formal-manifest.json`。被替代记录说明：`evidence/stage3/superseded-run.json`。

## P5：独立离线审计、统计与完整证据包

**状态：完成。**

- `study-audit` 使用独立标准库解析器读取 320 份 gzip JSONL，不调用生产 `segmented_metrics`。它检查矩阵、fixture 范围、actor/value、状态边界、覆盖 marker、native payload digest、prefix 引用、parent-before-child、不同子代、预算/截尾、公共 cache/corpus 以及 accepted seed 的重放与使用。
- 审计结果为 `passed`：320 个槽位、40 个共同区组、243 个目标命中、791,282 条完整序列、553,708 条 mutation。
- `study-report` 生成 `summary.json`、`observations.csv`、Markdown 和三张 SVG。相同运行目录的第二次独立输出中，以上报告产物逐字节一致；`audit.json` 仅因 `elapsed_seconds` 不同而不同。
- 完整档案 `artifacts/stage3-formal-v1.tar.gz` 为 3,358,084,381 bytes，SHA-256 为 `91bf6e5063a4d7644e0f84a1c8187480a35c66185e4f929d275384db6ad2ad25`。档案清单包含 43,482 个 study 文件和 5,333,122,321 bytes 解压数据。
- `study-verify-archive` 在新目录安全解包、逐文件核对，并只使用归档内标准库脚本连续重建两次。两次 `summary.md`、`observations.csv` 和 `summary.json` 哈希一致；不需要 EVM 工具、solver 或网络。
- 小型、路径清理后的公开包位于 `evidence/stage3/`，包含完整 320 行 observations、结构化汇总、独立 audit、配置、manifest、图表、协议审计、首轮失败记录、档案元数据和固定文件清单校验和。

实际命令：

```sh
./seedbridge study-audit runs/stage3-formal-02 --output runs/stage3-formal-02/derived/audit.json
./seedbridge study-report runs/stage3-formal-02 --output runs/stage3-formal-02/derived
./seedbridge study-export runs/stage3-formal-02 --output artifacts/stage3-formal-v1.tar.gz
./seedbridge study-verify-archive artifacts/stage3-formal-v1.tar.gz \
  --output runs/stage3-formal-offline-verify-01
./scripts/build-stage3-evidence.py
(cd evidence/stage3 && shasum -a 256 -c checksums.sha256)
```

## P6：课程项目报告与验收记录

**状态：完成。**

- [Stage 3 结果](STAGE3_RESULTS.md) 逐项回答 RQ1–RQ3，报告逐 fixture/profile 的 10 次结果、配对预算差值、调用限额比较、成本分解和负结果原因。
- WorkflowGate 的解释保留 `no_eligible_prefix`、`no_candidate`、`augmentation_timeout` 和 native continuation miss，不把所有负结果归因于求解开销，并明确披露独立随机轨迹。
- [英文项目报告](PROJECT_REPORT.md) 覆盖问题、相关工具定位、设计、协议、真实结果、失败历史、局限和复现；不声称新漏洞、一般性优越或第三方合约适用性。
- README 记录 Stage 1/2/3 的边界、Stage 3 CLI、证据入口和归档复核方式。技术计划的工作包、验收和产出已同步为实际完成状态，没有开发工时估算。
- 最终回归结果和公开仓库提交信息在本节下方的“最终核查”中记录。

## 最终核查

以下项目在正式数据冻结后执行；测试数量以命令实际输出为准：

```text
./scripts/bootstrap.sh                                      passed; four fixtures rebuilt
./seedbridge doctor                                        passed; all pinned tools OK
uv run --frozen pytest tests/unit -q                       156 passed
SEEDBRIDGE_INTEGRATION=1 uv run --frozen pytest -q         163 passed (156 unit + 7 integration)
GOTOOLCHAIN=local go test -mod=readonly ./...               passed
./seedbridge study-plan --config configs/stage3-study.json  320 slots / 40 blocks
scripts/audit-stage2.py runs/stage2-formal-02               passed; 60 campaigns, 29,259 sequences,
                                                            20,382 mutations, 36/36 accepted seeds used
./scripts/audit-stage3-protocol.py                          passed; 3 smoke profiles, 60 converted campaigns
./seedbridge study-audit runs/stage3-formal-02              passed; 320 slots
./seedbridge study-verify-archive ...                       passed; 43,482 archived study files
Stage 2 and Stage 3 shasum -c                               all official files OK
git diff --check                                            passed
```
