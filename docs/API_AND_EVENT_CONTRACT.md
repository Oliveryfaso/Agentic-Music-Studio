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
- Artifact 上传、下载、重建和导出只使用受控 ID/ref 和短期 URL/流式响应；API 请求、响应、Worker Job 和事件都不接收或返回任意服务器/客户端路径。
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
artifact_id?
artifact_state?         # available | evicted | missing | rehydrating
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
| GET | `/imports/{thread_id}` | 只读投影同一 Import Graph checkpoint，供刷新恢复与有界轮询 |
| POST | `/api/v1/imports/{thread_id}/confirm-analysis` | 确认/覆盖/跳过低置信度 BPM/key 分析 |

上传创建请求必须包含文件名、字节数、声明格式、rights declaration；服务端仍以 magic bytes 和解码结果为准。

当前已落地的首个纵切使用 `/api/v1` 前缀：创建 Upload Session 必须携带
`Idempotency-Key` 与 `project_id/filename/byte_size/declared_format/rights_declaration/
expected_sha256`；PUT body 是原始 bytes，不使用 multipart，也不接受路径。Part 从 1 开始且必须顺序上传；重放已接收 Part 时服务端重新计算该 Part 的 bytes/SHA-256，一致才返回 `replayed=true`，不一致返回 `UPLOAD_PART_CONFLICT`。默认单文件上限 256 MiB、Part 4 MiB、Session TTL 24 小时，均为服务端配置。

`complete` 只通过 checksum 与 magic-byte gate，登记 `source-original.v1 + quarantined` Artifact；采样率、声道、duration、codec 在此时保持未知，不得猜测。`POST /api/v1/projects/{project_id}/imports` 接受 `branch_id + base_revision_id + source_artifact_id`，启动同一 Parent Graph 的 `import_audio` 分支；独立 Worker 经 FFprobe/FFmpeg 解码后，原件转 `validated`、生成带 `import-analysis.v1` BPM/key/置信度 metadata 的 `working-pcm.v1`。高可信分析由规则自动决定是否按项目 BPM 创建保持音高的 Derived Artifact；低可信时响应 phase 为 `analysis_confirmation_required`，客户端再向 `/api/v1/imports/{thread_id}/confirm-analysis` 发送 `action=confirm|override|skip_alignment|cancel`，override 必须提供 `source_bpm`。确认后仍从同一 checkpoint/Run 继续，最终才由确定性 `import_audio` 命令提交 L1 Revision。首版没有独立公开 time-stretch 端点；它是 Parent Graph 的 Application/Worker 命令，避免浏览器绕过分析与 lineage 合同。

`GET /api/v1/imports/{thread_id}` 是只读投影，不恢复或重跑 Graph Node；返回 source、normalized、最终 selected Artifact ID、analysis、安全 phase 与 materialized Revision ID，供 URL 刷新恢复和 `waiting_worker` 有界轮询。Thread ID 必须匹配服务端生成的 `import-{32位小写hex}`，不接受路径字符或任意用户命名。浏览器可以对 `available + validated` Audio Artifact 使用 `GET /api/v1/audio-artifacts/{artifact_id}/content`；响应支持 Range，但始终由服务端 ID 解析受控 storage key，拒绝路径逃逸、符号链接和未验证/四态不可用 Artifact。

Time-stretch 返回 202。Derived Artifact 就绪前，前端只能播放原始未对齐版本并显示处理中状态，不能使用变调 `playbackRate` 模拟最终结果。

## 6. Preview 与审批

AI Proposal 不作为公共可变资源直接提交。Graph 产生不可变 Candidate Snapshot 和可变生命周期的 PreviewCandidate 后提供：

| 方法 | 路径 | 行为 |
|---|---|---|
| GET | `/previews/{preview_id}` | Candidate hash、完整 Candidate Snapshot/IR ref、Branch/Base、diff、影响范围、依据、完整时长压缩试听引用与状态 |
| POST | `/previews/{preview_id}/approve` | 从 Candidate Snapshot 创建新 Revision；Branch head 变化则 409 |
| POST | `/previews/{preview_id}/reject` | 标记拒绝并恢复 Run |
| POST | `/previews/{preview_id}/branch` | 从 Base 创建独立分支并物化新的 Revision；默认不切 active branch |

所有审批同时是 Run resume 动作；API 内部必须保证审批记录、Preview 状态、Branch head 更新和 Graph resume 不会因重复请求产生两个 Revision。Preview 批准后保留原 Candidate Snapshot 和审计记录，不把 Preview ID 复用为 Revision ID。

A/B 阶段两个候选均持久化完整 Candidate Snapshot/IR 和重建配方，并各自产生完整时长的压缩试听；不得为了节省空间只保存截断片段，也不预生成每个候选的无损 Master/Stem。试听被回收后仍能显式 rehydrate，不影响从 Snapshot 物化 Revision。

## 7. Sound Catalog

| 方法 | 路径 | 行为 |
|---|---|---|
| GET | `/sound-catalog` | 搜索本地审核资产/预设 |
| POST | `/sound-searches` | 显式启动外部搜索 |
| GET | `/sound-searches/{id}/results` | 带来源/许可的候选 |
| POST | `/sound-searches/{id}/imports` | 用户确认后进入隔离导入 |
| GET | `/assets/{asset_id}/preview` | 受控试听 |

外部搜索默认关闭。搜索结果不是 Asset；只有通过许可检查、下载隔离、checksum 和审核后才产生本地 Asset。

## 8. Export 与 Artifact

| 方法 | 路径 | 行为 |
|---|---|---|
| POST | `/projects/{project_id}/exports` | 启动 finite export Run |
| GET | `/exports/{export_id}` | 导出状态与 Artifact refs |
| POST | `/exports/{export_id}/cancel` | 请求取消 |
| GET | `/artifacts/{artifact_id}` | 元数据 |
| GET | `/artifacts/{artifact_id}/content` | 授权下载/流式读取 |
| POST | `/artifacts/{artifact_id}/rehydrate` | 对 `evicted` Artifact 显式启动同一 MotifForgeGraph 的有限重建 Run；返回 202 + run_id |
| GET | `/api/v1/audio-artifacts/{artifact_id}/features` | 按源 Audio Artifact 列出 waveform/analysis Feature Artifact metadata；不内联 payload |
| GET | `/api/v1/audio-artifacts/{artifact_id}/content` | 仅流式读取 available + validated Audio Artifact；支持浏览器 Range 试听 |
| GET | `/api/v1/feature-artifacts/{artifact_id}` | `available` 时返回紧凑 JSON payload；`evicted/rehydrating` 只返回 metadata |
| GET | `/storage` | Artifact Root 安全标签、profile、健康状态、剩余空间、配额和 policy version；不返回路径 |

导出请求包含固定 `revision_id`、Master 格式、明确选择的 Stem、是否包含 MIDI/trace manifest。Master WAV 和 Stem 都在用户请求时按需渲染；运行期间 active branch 或 Branch head 可以变化，但导出必须继续渲染请求中固定的 Revision。最终 Master 仍按渲染合同支持 48 kHz/24-bit WAV，Lean Storage Policy 不降低导出质量。

Artifact 资源公开 `state = available | evicted | missing | rehydrating`、`rehydratable`、大小/checksum、`quality_profile_id` 与 codec/sample-rate/channels/bit-depth 或 bitrate/encoder-version 媒体摘要、保留原因和安全的存储位置标签（如“External Artifact Store”），但不公开物理路径：

- `GET content` 对 `available` 返回内容；对 `evicted` 返回 409 `ARTIFACT_EVICTED` 和 rehydrate 动作；对 `rehydrating` 返回 409 `ARTIFACT_REHYDRATING`；对 `missing` 返回 410 `ARTIFACT_MISSING`。
- `POST rehydrate` 只接受 Artifact ID 和 Idempotency Key，不接受路径、输出目录或任意 recipe；服务端从已持久化 recipe/dependency refs 创建 Job。
- 重复 rehydrate 返回同一进行中或已完成结果。不可重建、依赖缺失、外置盘断开分别返回稳定 Problem Detail。

Feature Artifact 与 Audio Artifact 使用不同 Schema/table，但共用 Artifact ID、四态可用性、生命周期、受控 storage key、checksum、recipe 和显式 rehydrate 语义。首版 Feature Profile 为 `waveform-peaks.v1`（最多 4096 个 min/max bucket）与 `imported-audio-analysis.v1`。列表端点只返回 metadata；单项读取在 `available` 时才读取并校验 JSON bytes。客户端不能把 Import 响应内的兼容 analysis 投影当作长期事实源。

本地 Lean Profile 的服务端必须在启动前获得显式外置 Artifact Root 配置；API 不能把请求路径用作临时配置，也不能在 Root 不可用时切换到代码中的 `var/*` portable fallback。`var/*` 只允许 CI/test/portable profile 显式启用。

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
| `storage.pressure_detected` | policy version、quota scope、free/estimated bytes、route；无路径 |
| `storage.root_unavailable` | root label、可恢复状态；无路径 |
| `storage.root_restored` | root label、health；无路径 |
| `artifact.evicted` | artifact ID、reason、rehydratable |
| `artifact.rehydrating` | artifact ID、run/job ref |
| `artifact.available` | artifact ID、checksum/媒体摘要 |
| `artifact.missing` | artifact ID、安全 failure summary |
| `plan.ready` | plan ref、validation summary |
| `approval.required` | interrupt ID、kind、safe summary |
| `preview.ready` | preview ID、ChangeImpact、diff summary |
| `revision.committed` | branch ID、revision ID、content hash |
| `run.partial` | available artifacts、unresolved issues |
| `run.completed/cancelled/failed` | terminal outcome |

进度事件允许合并/降采样，但 terminal、approval、revision、artifact 和 error 事件不得丢弃。

## 10. 内部 Job 合同

浏览器不直接访问 `/render-jobs` 或 `/time-stretch-jobs`。Application/Graph 创建统一 Job：

- `job_type = ingest | analyze | time_stretch | render_preview | render_master | render_stem | transcode | export_manifest | rehydrate`
- `run_id/thread_id/revision_id/candidate_id/segment_id`
- `request_schema_version`
- input Artifact refs
- estimated output bytes、storage policy/profile ref；不含 root/output/temp path
- `idempotency_key`、attempt、deadline、priority
- resource profile

Worker 只按 `job_id` 读取数据库合同。Redis payload 不携带完整 IR、Secret 或服务器路径。

Worker 从 Artifact Repository 获得受控输入流和一次性输出 sink；即使任务来自内部调用，也不能接受任意文件路径。外置盘在任务中断开时，Worker 终止写入、保留可审计 Job 状态并发出 `ARTIFACT_ROOT_UNAVAILABLE`，不得回落到内置盘或把部分文件登记为 `available`。

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
- Artifact 四态转换、幂等 rehydrate、不可重建 410 和重建失败回滚。
- StoragePressureGate 的 proceed/GC/rehydrate/wait/fail 路由及外置盘断开恢复。
- Candidate 保留完整 IR + 完整时长压缩试听，并能在回收后恢复和完成按需无损 Master/Stem 导出。
