# P2.3 真实模型验收：最小 Undo 修复独立审查

What this change does: 将 `AgentAppendPianoTrackCommand` 加入已有的钢琴精确父版本恢复白名单，恢复人工批准语义加轨后的 Undo。新增三曲确定性回归覆盖 approved preview → Undo → 原导入 IR/content hash 与当前分支 head，并检查同 key 重放。

审查结论：指定两文件差异未发现已确认的 Critical、Important 或 Minor；本最小修复可继续进入现有真实 PostgreSQL 数据上的边界验收。本结论不表示 P2.3 真实模型或音乐质量验收完成。

- **Critical：无。**
- **Important：无。**
- **Minor：无。**

审查范围与基线：2026-10-20，分支 `codex/motif-p0-piano-preparation`，HEAD `a841c1189780006c795f4d4efc6ee28d1d24889e`。生产差异仅 `services/api/src/motif_forge/application/undo.py:388` 一行；另审 `services/api/tests/unit/application/test_undo.py` 的三曲回归及一处格式变化。阶段为 P2.3 真实模型验收期间的精确 Undo 缺陷修复；直接覆盖 MF-P05/P06/P11/P16/P18/P21 的加轨、HITL、编辑恢复、持久化边界、回归与审批保护。未扩展功能范围。

独立静态核查：

1. `undo.py:161` 原已将人工和 Agent 加轨编译为同一 `RemoveAddedPianoTrackCommand` 逆命令；`policies.py:42` 仍将相关命令判为 L2。缺陷是后续精确父恢复白名单遗漏 Agent 命令类，并非逆命令未实现。
2. `undo.py:297–317` 仍先用原命令重放并要求与已提交 Revision 完全相等，再要求逆命令精确恢复父 IR。`undo.py:354–395` 仍锁定分支、核对当前 head 与 base、检查项目/父版本、要求 target 等于 base，并再次比较完整候选 IR 与父 IR。其他 L2 逆操作仍在 `undo.py:397` 被拒绝。新增一类命令没有放宽这些条件。
3. `commands.py:735–763,820–832` 对 Agent/人工 append 共享受审核来源、单原轨与原轨锁保护；移除逆命令只能移除未锁定新增轨。完整 IR 相等检查同时覆盖原轨、音符、来源与渲染配置，恢复版本引用仍采用父版本。
4. `previews.py:295–315` 的拒绝路径不创建 Revision、不推进 head，因此 Q4 被拒绝后不改变 Q1 的当前 head 地位。批准路径仍验证不可变候选身份并创建新 Revision；本补丁未修改这些分支或 HITL。
5. 新三曲回归确实经过 `CreateCommandPreview` 与人工 `DecidePreview(APPROVE)`。`fakes.py:132–143` 现有 Fake materialization 不写 `command_batches`，所以测试显式补齐查找；这与 `database.py:415–449` 将 `snapshot.commands` 存为真实 RevisionCommand、以及 `database.py:271–293` 读取原命令的生产实现一致，不是伪造另一套逆命令。

证据及其界限：

- 已独立读取 [undo-red.log](undo-red.log)：三曲均在 Undo 调用处报 `UNDO_NOT_AVAILABLE: inverse impact is not auto-committable`，结果为 `3 failed, 2 deselected`。该日志的失败到达生产 Undo 的同一影响等级拒绝路径；未把早期夹具构造错误计为 RED。
- 已独立读取 [undo-green.log](undo-green.log)：`14 passed in 0.78s`。这是主线已有窄测试运行的日志，本审查按父任务要求未重复执行测试；没有将其描述为审查者独立重跑。
- 静态核查了 Undo 全路径、相关 command/policy、审批与拒绝路径、Fake 和 PostgreSQL 命令存取实现，以及仓库必读文档中本切片相关章节、`motif-forge-development` Skill 与 change checklist、P2 语义钢琴合同。
- `docs/PROJECT_GUIDE.md` 最新提交为 `d68b900bd8dce6c5786dd0b6c6b531429c9d38a2`；本次任务开始和交付前的 Git status/diff 均为空。未修改 Guide，未计算内容 hash。

Not checked: 未操作实际 PostgreSQL、API、Worker、模型、网络或容器，也未重发 Q1/Q4。已有持久化 Q1/Q4 数据上的 Undo、重开及当前项目精确恢复仍须由主线完成；确定性单测不能代替该真实边界。

执行与资源状态：审查端只读命令均已正常退出，曾返回的 shell session `91876` 已确认 exit 0；没有创建后台服务、容器、凭据或付费任务。审查端随后只新增本报告，未改生产代码或测试。父端先前报告的挂起 exec/apply_patch 与父端资源清理状态未由本审查独立验证，不能据此声称已经解除或完成清理。

Verdict: 本两文件最小修复无已确认的审查阻塞；继续完成上述真实边界后，再决定本轮验收结论。
