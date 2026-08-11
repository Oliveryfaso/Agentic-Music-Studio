# Motif Forge API 与事件合同

> 状态：首版 HTTP/SSE 合同
> Base path：`/api/v1`
> 详细领域语义：[DOMAIN_AND_REVISION_MODEL.md](./DOMAIN_AND_REVISION_MODEL.md)

## 1. 通用规则

- JSON 字段使用 `snake_case`，时间使用 UTC ISO 8601。
- 服务端生成实体 ID；客户端写入请求必须带 `Idempotency-Key`。
- 会推进 Branch head、基于当前作品生成候选或启动编辑 Run 的请求必须带 `branch_id + base_revision_id`；响应使用 `ETag` 返回目标 Branch head Revision。创建 Project、从固定 Revision 新建 Branch、切换 active branch 等不推进既有 head 的操作使用各自的显式并发字段。
- 异步操作返回 `202 Accepted + run_id`，不在 HTTP 请求中等待模型、分析或渲染。
- 错误使用 Problem Details 形状，并增加稳定 `error_code`、`retryable`、`trace_id`。
- Artifact 下载使用受控 ID 和短期 URL/流式响应，不接收任意路径。
- 外部 API 只面向 Web；Worker 调度、Graph checkpoint 和 Outbox 不公开为浏览器接口。

## 2. 标准响应

### 2.1 成功 Envelope

资源读取可直接返回资源；命令类统一包含：

```text
request_id
status = succeeded | accepted | waiting | partial
data
warnings[]
trace_id
```

### 2.2 Problem Detail

```text
type
title
status
detail                 # 对用户安全的说明
instance
error_code
retryable
retry_after_ms?
trace_id
current_revision_id?    # active branch head 的读取投影
current_branch_id?
validation_issues[]?
```

不得返回 Secret、服务器路径、原始 DeepSeek reasoning、完整堆栈或素材隐私内容。

## 3. Project 与 Revision

| 方法 | 路径 | 行为 | 成功 |
|---|---|---|---|
| POST | `/projects` | 创建空项目 | 201 |
| GET | `/projects` | 列表/分页 | 200 |
| GET | `/projects/{project_id}` | 项目摘要、active branch 和其 current revision 投影 | 200 |
| GET | `/projects/{project_id}/revisions/{revision_id}` | 完整 IR 或按视图裁剪 | 200 |
| GET | `/projects/{project_id}/revisions` | 版本/分支列表 | 200 |
| GET | `/projects/{project_id}/branches` | 分支与各自 head | 200 |
| POST | `/projects/{project_id}/branches` | 从指定 Revision 创建分支 | 201/409 |
| POST | `/projects/{project_id}/active-branch` | 显式切换工作分支 | 200/409 |
| POST | `/projects/{project_id}/command-batches` | 提交人工命令批次 | 201/409 |
| POST | `/projects/{project_id}/undo` | 创建反向 Revision | 201/409 |

创建 Branch 使用 `source_revision_id + name`；切换 active branch 使用 `target_branch_id + expected_active_branch_id`。两者都必须带 Idempotency Key，但不能伪造一个无语义的 `base_revision_id`。

`POST command-batches` 请求：

- `branch_id`
- `base_revision_id`
- `commands[]`
- `client_sequence`
- `reason`

响应返回 `branch_id`、`revision_id`、`content_hash`、`actual_change_impact`、`render_state` 和 `warnings`。HTTP 409 返回目标 Branch 当前 head 和可重放的客户端命令，不自动合并。

## 4. AI Run

| 方法 | 路径 | 行为 |
|---|---|---|
| POST | `/projects/{project_id}/ai-runs` | 启动 generation/edit/import-followup Run |
| GET | `/runs/{run_id}` | 当前投影状态 |
| GET | `/runs/{run_id}/events` | SSE 事件重放与实时订阅 |
| POST | `/runs/{run_id}/resume` | 回答 interrupt/批准/拒绝 |
| POST | `/runs/{run_id}/cancel` | 请求取消 |
| POST | `/runs/{run_id}/retry` | 对允许的人类可重试失败创建恢复动作 |

启动请求：

- `run_type = generate | edit | import_followup`
- `branch_id`
- `base_revision_id`
- `user_intent`
- 可选 `selection`、`locked_ranges`
- `brief` 或 `edit_constraints`
- `external_sound_search_enabled=false` 默认值
- `budget_profile`

服务端推导 `thread_id`，客户端不能复用其他 Run 的 thread。

### 4.1 Resume

请求必须包含：

- `interrupt_id`
- `expected_checkpoint_id`
- `decision_type`
- `payload`

重复提交相同 Idempotency Key 返回相同结果。checkpoint 已推进时返回 409，不把旧审批应用到新状态。

## 5. Upload 与 Import

| 方法 | 路径 | 行为 |
|---|---|---|
| POST | `/upload-sessions` | 创建分块上传会话 |
| PUT | `/upload-sessions/{id}/parts/{part}` | 上传受限分块 |
| POST | `/upload-sessions/{id}/complete` | 完成 checksum 校验 |
| POST | `/projects/{project_id}/imports` | 用上传 Artifact 启动 Import Run |
| GET | `/imports/{import_id}` | Import 投影 |
| POST | `/imports/{import_id}/confirm-analysis` | 确认低置信度 BPM/key |
| POST | `/imports/{import_id}/time-stretch` | 请求保持音高的 Derived Artifact |

上传创建请求必须包含文件名、字节数、声明格式、rights declaration；服务端仍以 magic bytes 和解码结果为准。

Time-stretch 返回 202。Derived Artifact 就绪前，前端只能播放原始未对齐版本并显示处理中状态，不能使用变调 `playbackRate` 模拟最终结果。

## 6. Preview 与审批

AI Proposal 不作为公共可变资源直接提交。Graph 产生不可变 Candidate Snapshot 和可变生命周期的 PreviewCandidate 后提供：

| 方法 | 路径 | 行为 |
|---|---|---|
| GET | `/previews/{preview_id}` | Candidate hash、Branch/Base、diff、影响范围、依据、试听引用与状态 |
| POST | `/previews/{preview_id}/approve` | 从 Candidate Snapshot 创建新 Revision；Branch head 变化则 409 |
| POST | `/previews/{preview_id}/reject` | 标记拒绝并恢复 Run |
| POST | `/previews/{preview_id}/branch` | 从 Base 创建独立分支并物化新的 Revision；默认不切 active branch |

所有审批同时是 Run resume 动作；API 内部必须保证审批记录、Preview 状态、Branch head 更新和 Graph resume 不会因重复请求产生两个 Revision。Preview 批准后保留原 Candidate Snapshot 和审计记录，不把 Preview ID 复用为 Revision ID。

## 7. Sound Catalog

| 方法 | 路径 | 行为 |
|---|---|---|
| GET | `/sound-catalog` | 搜索本地审核资产/预设 |
| POST | `/sound-searches` | 显式启动外部搜索 |
| GET | `/sound-searches/{id}/results` | 带来源/许可的候选 |
| POST | `/sound-searches/{id}/imports` | 用户确认后进入隔离导入 |
| GET | `/assets/{asset_id}/preview` | 受控试听 |

外部搜索默认关闭。搜索结果不是 Asset；只有通过许可检查、下载隔离、checksum 和审核后才产生本地 Asset。

## 8. Export

| 方法 | 路径 | 行为 |
|---|---|---|
| POST | `/projects/{project_id}/exports` | 启动 finite export Run |
| GET | `/exports/{export_id}` | 导出状态与 Artifact refs |
| POST | `/exports/{export_id}/cancel` | 请求取消 |
| GET | `/artifacts/{artifact_id}` | 元数据 |
| GET | `/artifacts/{artifact_id}/content` | 授权下载/流式读取 |

导出请求包含固定 `revision_id`、格式、是否包含 Stems/MIDI/trace manifest。运行期间 active branch 或 Branch head 可以变化，但导出必须继续渲染请求中固定的 Revision。

## 9. Run Event SSE

### 9.1 传输语义

- 响应类型 `text/event-stream`。
- 每个持久事件包含单调递增 `event_id`。
- SSE `id:` 使用 `event_id`；断线后客户端以 `Last-Event-ID` 重连。
- 服务端先回放该 ID 之后的 PostgreSQL 事件，再切换到实时通知。
- Redis Pub/Sub 可以用于唤醒连接，但不是事件历史。
- 客户端按 `event_id` 去重；收到终态后再 GET `/runs/{id}` 核对最终投影。

### 9.2 RunEventEnvelope

```text
event_id
event_type
occurred_at
run_id
project_id
thread_id
branch_id?
revision_id?
candidate_id?
segment_id?
job_id?
sequence
payload_schema_version
payload
trace_id
```

### 9.3 事件类型

| 事件 | 关键 payload |
|---|---|
| `run.started` | run_type、graph version |
| `run.phase_changed` | from/to、reason |
| `graph.node_started/completed` | node、attempt、summary |
| `model.call_started/completed` | model、mode、usage summary；无 reasoning |
| `job.queued/started/progress/completed/failed` | job type、progress、artifact refs/error |
| `plan.ready` | plan ref、validation summary |
| `approval.required` | interrupt ID、kind、safe summary |
| `preview.ready` | preview ID、ChangeImpact、diff summary |
| `revision.committed` | branch ID、revision ID、content hash |
| `run.partial` | available artifacts、unresolved issues |
| `run.completed/cancelled/failed` | terminal outcome |

进度事件允许合并/降采样，但 terminal、approval、revision、artifact 和 error 事件不得丢弃。

## 10. 内部 Job 合同

浏览器不直接访问 `/render-jobs` 或 `/time-stretch-jobs`。Application/Graph 创建统一 Job：

- `job_type = ingest | analyze | time_stretch | render_preview | render_master | render_stem | transcode | export_manifest`
- `run_id/thread_id/revision_id/candidate_id/segment_id`
- `request_schema_version`
- input Artifact refs
- `idempotency_key`、attempt、deadline、priority
- resource profile

Worker 只按 `job_id` 读取数据库合同。Redis payload 不携带完整 IR、Secret 或服务器路径。

## 11. 前端调用规则

- TanStack Query 负责 Project、Revision、Run、Asset 等服务器状态。
- SSE Event reducer 只更新 Run 投影或触发 Query invalidation，不直接改 committed IR。
- Studio Draft 由 Editor Store 管理；服务器返回 committed Revision 后重新定位到新 Base。
- AI L0/L1 修改在收到 `revision.committed` 后落到 UI；不做假成功的 optimistic AI commit。
- 页面关闭后重新进入，通过 GET Run + SSE replay 恢复，而不是依赖浏览器内存。

## 12. 合同测试

必须覆盖：

- OpenAPI → TypeScript 类型无未提交 diff。
- 所有写 API 的 Idempotency Key 重放。
- command/approve 的 Revision 409。
- SSE 断线重连、重复事件、终态补查。
- Worker 重复完成事件不会重复提交 Revision。
- Upload checksum、格式伪装、超限和取消。
- Problem Detail 不泄露路径、Secret 和 reasoning。
