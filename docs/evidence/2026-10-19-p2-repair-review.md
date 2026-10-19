# Motif Forge P2.1 — 唯一受限修复复核

What this change does: 本次修复将经典谱导入的 Project/root、原谱 Revision/source head、工作分支/active 指针、audit 与导入 receipt 归入同一事务；成功请求的重放先读取 receipt，不再依赖 renderer 在线。

**Verdict: Ship（本次修复复核范围）。初审第 1 项 Important 已关闭；没有剩余 Critical 或当前路径 Important。** 本次只复核该修复，没有重启完整审查或增加其他产品范围。

## 核对结果

- `services/api/src/motif_forge/application/classical_import.py:82` 现在只有一个 `async with self._projects()`；不再调用会独立提交的 `CreateProject`。`insert_project_root`、source Revision/head、fork、两条 audit 与 `score-import.v1` receipt 均在这一个 UoW 内，沿现有 `PostgresTransaction.__aexit__` 统一 commit/rollback。初审指出的“第一提交已完成、第二事务尚未开始”的可见间隙已消失。
- 第 83–91 行先校验 receipt/fingerprint，命中后直接返回既有 project/branch/revision；第 92 行之后才检查 capability。相同 key 的重放无需 renderer，改变请求内容仍拒绝复用 key。
- 新 PG 回归 `test_classical_failure_after_score_write_rolls_back_project_and_retry_is_exact` 在 source 已写入、fork 发生前注入 RuntimeError，断言 projects/revisions/branches/idempotency/audit 五表 count 全部恢复原值；随后同 key 成功重试并重放，最终只新增一 Project、两 Revision、两 Branch。它直接覆盖初审缺口，没有扩大故障矩阵。

## 证据

读取作者的真实 PG RED 日志 `research/p2-runtime-2026-10-19/1792395881299598000.txt`：旧实现故障后五表从 `(4,18,6,28,31)` 变为 `(5,19,7,29,32)`，测试明确失败。读取 GREEN 日志 `1792395934551183000.txt`：相关 unit/API/PG 组合 **7 passed / 1.00s**。本复核没有连接数据库或读取其凭据。

独立执行两个相关 unit/API 文件：**5 passed / 0.05s**。额外无数据库验证通过：创建只正常退出一个事务；将 capability 替换为一经调用即失败的函数后，相同 key 仍精确重放同一 project/revision；改变 name 的同 key 请求拒绝；没有额外 root/revision/branch。使用安全 `Settings.for_test()` 预导入、`PYTHONDONTWRITEBYTECODE=1`、禁用 pytest cacheprovider、排除 `._*`，没有读取 `.env`。

结束时 `git diff --check` 通过。HEAD 仍为 `d3ff8b0f91670df400de7d814e02a3849b8ea4d7`；`PROJECT_GUIDE.md` clean、无 diff。未修改项目、运行音频链、启动服务、调用模型、连接临时 PG 或改动共享 VM。

本结论关闭初审唯一 blocker，支持父任务继续原定文档/存储关闭门及开发分支 checkpoint/push；不是音质、全 P2、Compose 或主机掉电持久性的新增验收。初审报告保留为原始记录，本报告记录唯一修复复核的最终状态。
