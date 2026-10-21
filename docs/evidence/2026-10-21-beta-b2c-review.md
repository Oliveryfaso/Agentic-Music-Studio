# B2c fresh 独立审查

审查对象：`/Volumes/KINGSTON/idea/agentic-music-workbench` 当前完整工作树（包含未跟踪的新协调器、persistence store、测试和计划）；基线与审查时 HEAD 均为 `636d4aa9e9884980931b6fe777ad4eeea73a9dff`。当前阶段为个人 Beta B2c 重开入口与两个只读状态合同，覆盖 MF-P06/P13/P18/P21。按定稿 `CONTRACT.zh-CN.md` 判断，负载假设为现行本地单用户产品。

结论：**无确认的 Critical、Important 或 Minor；没有发现当前路径阻塞，可进入作者已限定的后续运行态验证。** 本结论是静态代码审查结论，不是浏览器 UAT 或 Beta 全链通过声明。没有修复复审，本轮仍保留至多一次窄复核额度。

## Critical

0 项。

## Important

0 项。未发现会改变 head、授予 HITL 权限、重复付费、制造写入副作用或把不可核验目录伪装成空目录的改动。

## Minor

0 项。审查期间作者仅调整 store import 排序；最后静态读取确认该处已按排序整理，无语义变化。

## 已核对的调用链与边界

- `ProjectCard.tsx:43` 现在以 `head_revision_id` 展示“打开作品”；既有导航仍使用 project/head。无可播放 MP3 的保存作品也可打开，按钮不提交写请求。定向测试覆盖这一入口；未据此声明实际浏览器通过。
- `infrastructure/persistence/piano_recovery.py:31` 起的两个 SELECT 先限定 project/active branch。Preview 查询在 SQL 中先排除非 pending 与 TTL 到期行，再 DISTINCT/排序/limit；手工候选通过 `preview.create-from-commands.v1` 的 `piano-preview:` 幂等记录，同时关联 `:baseline` 与 `:piano` Job，再取得专用 MediaRun 的 thread。因此只有首个 baseline Job 的窗口不会漏掉，两个同 thread Job 不重复计数。
- Preview 的外连接保留已知钢琴候选但没有可逆 thread 的孤儿；semantic Preview 可通过原 AIRun 身份取 thread。early semantic 只接受同 project/branch、edit、queued/planning、含对象形态 piano_request 且尚无任何 Preview 的 AIRun；终态/到期 Preview 不会又被当成 early AIRun 捞回。按业务 created_at、thread 排序，合并后有界返回。
- `application/piano_recovery.py:65` 起只调用 store SELECT 与 `graph.aget_state`，没有 invoke、补写、创建 Job/Run、模型或音频读取。最多核验 10 条；第 11 条返回 limit_reached/count=null/摘要null。查询、Graph、孤儿、格式和 project/branch/base/Preview/hash 身份失败均返回 unavailable/count=null/摘要null，普通 workspace 可继续返回。3 秒总边界失败也不会泄露异常文本。
- `application/piano_recovery.py:109` 的空 checkpoint 回退只用于已有 early semantic AIRun。材料化竞争中缺少一致 Preview 身份时返回 unavailable。Graph 终态与过期候选被排除；多个候选只选最新摘要，不审批、拒绝或丢弃其余候选。
- 恢复摘要保留业务记录的原 `base_revision_id`，没有用 workspace head 重写。恢复目录不含批准凭据或候选 hash；实际原 thread GET/decision、候选精确 hash、Preview TTL 与 branch/base 事务检查仍由既有链路负责。explicit URL 错误未被新增目录逻辑替换成另一 thread。
- `piano_capability.py` 新字段默认 unknown；构造时只接已加载 Settings 的 bool/null。正常两个 router 以及 lifespan 内 PianoPreviewWorkflow 三处均传 `deepseek_configured`。既有 renderer 成功、缺资源、HTTP/JSON/transport 失败分支都携带独立 semantic_generation；响应未新增 key、endpoint、余额或内部诊断字段，也未新增 Provider 探活。configured 只表示本地配置。
- `ReadProjectWorkspace` 与 router 新依赖是可选的，未接线 fake 默认明确 unavailable；旧 `PianoCapability(available=...)` 构造保留默认兼容。生成的 OpenAPI TypeScript 增量与 Pydantic 字段一致；新公开字段的可选性允许旧 fixture/客户端逐步兼容，没有扩大手写 DTO。

## 证据与未覆盖

审查按 AGENTS 顺序读取 Decision Log、Project Guide、Implementation Status、Roadmap、repo skill 和相关 checklist，并使用 ponytail-review 沿调用链核对。Project Guide 起始和收尾最近提交均为 `d68b900bd8dce6c5786dd0b6c6b531429c9d38a2`；两次状态/diff 均为空，未计算内容 hash。未修改共享仓库；本报告是唯一写入。

只读取作者已有回执，没有重跑测试：相关 unit/API/SQL 形状门 `61 passed`；Mypy `6 source files` 通过；修正后的真实独立 PostgreSQL 边界 `1 passed`。首跑使用不存在的 Revision 列名失败原回执继续保留。PG 测试使用合成乐谱与只读 Graph fixture，验证 baseline 关联、双 Job 去重、scope、旧 base、expiry/status 与业务表读前后不变；它不是真实用户生成、保存/Undo或浏览器恢复 E2E。OpenAPI/TS 通过由作者回执说明，生成 DTO 已静态核对。

本次未运行数据库、Docker、HTTP、浏览器、模型或 renderer，未读 `.env` 或凭据。early semantic 的真实 PG 数据生命周期、实际 PostgreSQL checkpointer 的在线恢复、lifespan 第三处的运行态接线、正常 Beta 新镜像 GET，以及前端目录提示/明确点击/配置禁用的真实浏览器表现，均没有被本次审查实测；其中目录与配置消费属于原前端后续工作。作者接下来的自有 API 更新和限定 GET 应作为独立追加证据。未把尚待这一验证或文档更新误列为代码阻塞，也未扩大为平台硬化要求。
