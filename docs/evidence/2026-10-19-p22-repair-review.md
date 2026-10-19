# P2.2 唯一限定修复复核

日期：2026-10-19。原审查报告：[p22-independent-review.md](2026-10-19-p22-review.md)。只复核原 Important I1/I2 及其必要调用接线，不重启完整审查、不新增验收矩阵。审查 BASE/HEAD 仍为 `5dbbc6aabf08b9a6e2d4fbfece810afc23fe5564`，当前为作者修复后的未提交 diff；开始和结束 `docs/PROJECT_GUIDE.md` 无修改。

## 结论

**I1、I2 均关闭；本次限定复核无剩余 Critical/Important 阻塞。** 原 Minor“响应缺少 model 时回退请求别名”按主控明确裁定记录 deferred；本次不重新展开。该项不影响有实际 reported model 的已发生 live 调用。

本结论是独立代码和限定离线复核的结论；主控仍负责修复后 prompt.v2 的真实调用验收、阶段检查、文档、清理和分支同步。原 prompt.v1 的真实反例必须保留，不能被新通过结果覆盖或抹去。原两次模型提交继续计入本轮累计预算。

## I1 — 关闭：局部修改保留和声已有确定性约束

已检查 `application/piano_harmony.py`、`application/piano_semantic.py`、`providers/piano.py`、API/Dispatcher 的必要依赖接线及相关测试。

- 当前 modify 明确收窄为保留选中小节和弦，模型只能决定节奏网格、音区、gate、力度；不再承诺任意选区内重新配和声。
- 在构造付费 Planner 之前沿当前 Revision 及祖先（最多64层）查找每个目标 bar 的可信记录。AI 源必须来自该历史 Revision 的 `source_run_id` 对应持久 Plan；当前选中音符的完整 NoteEvents 与该历史 Revision、track ID 必须一致。连续修改不同范围、以及精确 Undo 后，可继续沿祖先逐bar查找来源。
- 人工 P2.1 兼容路径只认已记录 `AppendPianoTrackCommand` 的原 Track，以及严格 roots/broken 音符起点/时值/音高 recipe；不从一般首音或音高集合猜和弦。
- 无法验证时 `PIANO_HARMONY_UNVERIFIED` 在付费前停止。模型 prompt.v2 收到明确 `fixed_harmony`，保存前和读取已保存结果后均执行 `require_preserved_harmony`。不一致返回 `PIANO_HARMONY_CHANGED`，没有静默换回和弦、额外模型 repair 或隐藏重试。
- API 与生产 Dispatcher 都向 service 注入项目 UoW，修复不局限于测试构造。

独立重跑6条和声窄测覆盖：跨不同选区/Undo祖先来源、修改过的音符不可验证、错误模型和弦拒绝、两种人工规则兼容、service 在 save/候选前拒绝改和声。另含原 service replay 和 Provider 合同2条，共 **9 passed / 0.59s**。

## I2 — 关闭：待回执用量统一为 unknown

已检查 `infrastructure/persistence/ai_runs.py`、`infrastructure/persistence/run_inspection.py`、3条新PG测试和作者 RED/GREEN 原始日志。

- `read_ai_run_with_pending_usage` 在同一次 SQL snapshot 中读取最新 AIRunRow 和 RESERVED reservation 是否存在；`populate_existing=True` 防止同session identity map保留旧 totals。不会出现“先读旧0，回执提交，再查不到pending”而误报known0的两次查询组合。
- ByID、ByThread、普通 projection 与 Run Inspector 复用同一逻辑。存在未 observed 的 reservation 时，完整累计 token 字段为 None、usage/cost为unknown，请求计数仍保留真实值。没有用“tokens等于0”猜测未知。
- 底层累计值继续保存已 observed 的真实总和，不把 None 写回或污染聚合器。因此真实全0回执仍可恢复known0；已有partial再出现待回执时先显示unknown，全部回执到齐后恢复正确partial总和。
- 已reserved无result时，持久 BudgetLedger 读取unknown并拒绝后续提交；原每Run1请求硬限也保留。

只读核对作者真实 PostgreSQL 测试与日志：

- 新3条 RED 日志：`research/p22-runtime-2026-10-19/1792402415364853000.txt`。
- 新3条及原 Inspector2条 GREEN：`research/p22-runtime-2026-10-19/1792402481594856000.txt`，末尾 **5 passed / 1.24s**。
- 覆盖实际 DeepSeekJsonClient + MockTransport 超时、重建reader后的ByID/ByThread/projection/Inspector一致unknown、再次调用仍仅1次HTTP；合法observed0恢复known0；partial10+后续16恢复26/partial，未知cache/reasoning仍None。

旧 `p22-independent-probe.py` 的 FakeUow 人工构造known0并绕开Postgres，属于原反例留档；修复后不以该假对象的旧结果判断真实 reader 是否修复。

## 独立执行及边界

```text
DEEPSEEK_API_KEY='' .venv/bin/python -m pytest \
  services/api/tests/unit/application/test_piano_harmony.py \
  services/api/tests/unit/application/test_piano_semantic.py \
  services/api/tests/unit/providers/test_piano_semantic.py \
  -q -p no:cacheprovider
```

结果 **9 passed / 0.59s**。`git diff --check`通过；Guide仍无diff。

本复核未读取.env/凭据，未调用外网或真实模型，未启动或连接PG/其他服务，未修改产品。PG5项属于作者真实运行证据，本审查独立阅读代码及原始结果，没有冒充独立重跑。无需为此次限定复核追加付费请求。
