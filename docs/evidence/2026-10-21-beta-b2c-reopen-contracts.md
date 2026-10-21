# Personal Beta B2c：重开入口、候选发现与模型配置读合同

2026-10-21；覆盖 MF-P06/P13/P18/P21；基线636d4aa。主线唯一集成，原前端继续负责页面消费/真实浏览器，资源线边界不变。main/PROJECT_GUIDE.md不改；Guide最后d68b900，无内容hash。

## 已完成

1. 接入原前端补丁：ProjectCard只把“打开已有head”的门槛由has_playable_revision改为head_revision_id。无MP3的保存版可进入原Studio；媒体标志语义未改。实际源码定向RED1→GREEN1、原首页2回归、TS通过；不是浏览器验收。
2. GET `/api/v1/projects/{project_id}` 增加 `recoverable_piano_preview` 和 `piano_preview_recovery`。只读已有Preview/幂等/Media Job/Run/AIRun身份，再aget_state核验。覆盖baseline阶段、双Job去重、手工AI Run0、early semantic；按当前active branch过滤，原base保留。目录不审批、重做或推进Graph。
3. GET `/api/v1/piano-capability` 增加 `semantic_generation.configuration` 三态。正常API从已加载Settings只注入bool；所有renderer失败分支保留独立配置状态。configured只表示本地有配置，不证明远端身份/余额/可用性；没有模型探针、密钥读写或持久化新增。
4. OpenAPI生成类型更新。只构建/替换本轮自有Beta API，`--no-deps --no-build --pull never`，正常owner/daemon/锁/挂载/loopback/空模型配置预检通过；其余8个自有服务容器身份、镜像、StartedAt、mount、端口均与前一致。没有启停旧项目或Colima，未对主库运行迁移（测试库初始化迁移除外），没有运行render Job或模型。

## 定稿最小合同

Workspace新增：

```json
{
  "recoverable_piano_preview": {
    "thread_id": "piano-<32 hex>", "branch_id": "<active branch UUID>",
    "base_revision_id": "<original base UUID>",
    "phase": "waiting_piano_approval", "updated_at": "<checkpoint time>"
  },
  "piano_preview_recovery": {
    "status": "ready", "pending_count": 1,
    "selection_rule": "newest_created", "reason_code": null
  }
}
```

phase还支持queued/planning/waiting_piano_worker。`ready`才是已确认读取；无合格项为摘要null/count0。多项按业务创建时间降序、thread降序选首条，count明确多项，不替用户决定。最多核验10条、整体3秒；超限返回limit_reached/count=null/摘要null，查询/Graph不可读或身份不一致返回unavailable/count=null/摘要null。reason分别PIANO_RECOVERY_LIMIT_REACHED/PIANO_RECOVERY_UNAVAILABLE。非active branch、Preview终态、TTL到期和Graph终态不进入目录。stale base与TTL不同，stale仍返回原base；前端必须比较head并保持旧候选保留锁，原hash/branch事务门禁继续负责决定。摘要没有授予HITL权限。

capability新增：

```json
{"semantic_generation":{"configuration":"not_configured","reason_code":"MODEL_NOT_CONFIGURED"}}
```

configured/unknown的reason_code为null。缺字段或请求失败由前端视unknown；not_configured只禁语义提交，规则伴奏保持可用，不自动换模式或发请求。渲染available语义保持不变。

## 验证证据与真实边界

- 相关unit/API/SQL编译回归62通过（含既有项目读/钢琴路由），生成TS通过，Mypy6模块通过，Ruff/diff check通过。
- 独立数据库 `motif_b2c_contract_20261021` 在本轮自有PG新建，无新增容器/端口/账号。真实PG边界1通过：先创建手工Preview但未Job返回可见孤儿、baseline-only可发现、双Job不重复、跨项目/分支排除、stale保原base、TTL/终态排除；11表完整行投影重复读前后相同。测试使用合成钢琴谱/Graph fixture，不是渲染/模型/UI E2E。精确测试DB已DROP，正常库从未作为fixture目标。
- 首跑PG测试错误使用不存在的RevisionRow.parent_revision_id，修为真实parent_id后通过，原失败保留。首次运行更新在旧镜像tag步骤失败（No such image），没有到API替换；从已推送636d4aa白名单源码重建回滚镜像后继续。回滚镜像不是旧镜像逐字节副本。初构建后仅import排序更正，最终重构建保证部署六模块字节与审过源码一致。
- fresh独审一次：Critical0/Important0/Minor0，无修复复核；明确静态/fixture/PG与真实浏览器界限。
- 正常API实际5GET均200。原前端候选精确返回 `piano-42bfd5ef55b0fb2e80e3a4aff946c355`、waiting_piano_approval/count1；B2b返回 `piano-4c811c287cb78668c565f0005a269c0f` 同阶段/count1；B2a保存版摘要null/count0。三个head保持原值。音源available=true，模型配置not_configured；原源谱/音频/HITL未改。
- 主库前后完全相同：projects3/revisions7/previews3/runs7/jobs11/ai_runs0/outbox22。没有新增模型调用或估计费用；旧累计估计上界¥0.059998、同一¥10窗口，非账单，未重置。

## 原前端下一步（未由本主线代做）

从workspace消费目录，正常打开保存版本后显示用户可点击的恢复入口；链接指向原base和原thread，再调用既有exact-thread GET拿权威状态/媒体/hash。多个、stale、unavailable、limit需如实提示；显式URL错误继续锁原thread，不能静默替换。消费配置三态，禁用未配置语义按钮，保留规则入口。root Revision撤回按钮/文案是已登记非阻塞前端项，本次不改Toolbar。

首页 `http://127.0.0.1:15173/`，API `http://127.0.0.1:18000`。原前端候选与B2a保存/导出URL保持不变。真实浏览器仍受原生审批阻塞，播放/重读失败/下载/键盘验收未通过；本轮未重触审批或换通道。后台合同已运行，不表示新增前端消费者或完整个人Beta已验收。

边界：手工Preview提交后、首个Job前异常中断尚无可逆thread时只报告unavailable，不承诺自动修复；尚未覆盖大规模历史候选负载/公开多人/任意曲库。stage保持审核曲库内双钢琴。未改变原编曲/混音/EQ或用户认可声音。

## 运行与存储交接

新自有API `ed147665377e966b8105515aa5649fb79bf717507d7755728a25776ee771c5c8`，镜像 `sha256:7dad581e5910c255af1c23e9bd680ba6dc2c8d39f4e39c86e85bef54af08d04d`。回滚应用源码基线标签 `motif-forge-beta-api:b2c-before-636d4aa`（重建镜像a4e4507…）。Beta/Web保持运行，停止沿原owner receipt流程，不操作VM或旧项目。

先冻结保留清单，删除本次独立Mypy缓存和可从Git复现的白名单构建context，精确回收35,986,643逻辑bytes；日志/补丁/独审/合同fixture/运行回执保留。测试DB精确清退；没有删用户卷、作品、音源、原试听或备份。共享builder汇总4.49GB、归属混合，未做全局prune，也不把该待清理事项说成已达2GB目标。清理后复核ready与同一两个候选/三个head。产品代码无机器路径新增。

主任务证据工作区：`research/beta-reopen-contracts-20261021`，包含CONTRACT.zh-CN.md、frontend-contract-fixtures.json、各RED/GREEN/PG/类型/审查日志、live-before/after与source-integrity、主库计数和存储回执。fixture明确是新增字段投影，不冒充完整DTO或真实作品。仓库证据只收不含秘密的小报告与审查。
