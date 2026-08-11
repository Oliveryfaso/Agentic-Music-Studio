# Motif Forge 架构决策日志

> 状态：已批准
> 决策日期：2026-08-11
> 适用范围：首版代码、数据、Agent、音频与 Web Studio 设计

本文件只记录会改变系统边界、数据兼容性或运行成本的决定。实现细节可以在不破坏这些决定的前提下演化。

## ADR-001：统一 Graph 拓扑，任务级有限 Run

**决定**：系统只有一个版本化的 `MotifForgeGraph` 拓扑。每次导入、完整生成、AI 编辑、导出或恢复操作分别创建有限的 `run_id + thread_id`。所有 Run 通过 `project_id` 访问同一个项目，通过可选 `parent_run_id` 表达因果关系。

**不采用**：一个项目从创建到最终导出永久复用一个 LangGraph thread。

**原因**：任务级 thread 更容易控制 checkpoint 体积、并发修改、取消、归档、Graph 升级和故障恢复。它仍满足“正常流程和异常流程都位于一个完整 Graph 中”，只是完整性以一次用户任务为边界，而不是以项目生命周期为边界。

**约束**：

- 一个 Run 内的策略子图、候选、Segment、Worker 等待、HITL 和 Error Router 必须回到同一个 Parent Graph State。
- 项目事实不依赖 thread history；Run 结束后仍可从 PostgreSQL Revision 恢复项目。
- Run 固定记录 `graph_topology_version` 和 `state_schema_version`；不兼容的旧 checkpoint 必须迁移或终止，不能静默用新节点解释旧状态。

## ADR-002：PostgreSQL 是唯一业务数据库

**决定**：首版不实现 SQLite 业务存储档位。Docker Compose、开发集成测试和作品集演示均使用 PostgreSQL。

每个不可变 Revision 保存完整的 canonical `ArrangementIR` JSONB、内容哈希和摘要；命令、审批、Run、Job、事件、素材许可和 Artifact 元数据使用规范化表。WAV、MP3、MIDI、波形峰值和大分析结果保存在内容寻址 Artifact Store。

**原因**：双数据库会让 JSONB、事务锁、迁移、并发冲突和测试语义分叉。首版 1–5 分钟、最多 12 轨的 IR 足以采用完整 Revision 快照换取简单可靠的读取、分支和回滚。

**演化条件**：只有 Revision 数据量评测证明完整 JSONB 快照成为瓶颈时，才引入周期快照 + delta；对外 Revision Contract 不变。

## ADR-003：共享 AudioGraphCompiler 与 Chromium 标准渲染

**决定**：浏览器试听和最终导出共用 TypeScript `AudioGraphCompiler` 与相同的 `AudioGraphSpec`。浏览器用 Tone.js/Web Audio 实时播放；Render Worker 在受控 Chromium `OfflineAudioContext` 中执行同一编译结果并生成 canonical WAV。FFmpeg 负责 pitch-preserving time-stretch 基线、格式规范化与 MP3 转码，不承担首版合成器语义。

SoundFont 若进入 Core Sound Palette，先在受控资产构建流程中转换为许可清晰的 multisample pack；运行时不允许浏览器 Tone Sampler 与 Worker FluidSynth 各自解释同一乐器。

**性能影响**：

- 比原生 FFmpeg/FluidSynth Worker 占用更多镜像空间、启动时间、内存和 CPU。
- 换来 Preview、Stem 和 Master 的音色、包络、效果、自动化与路由一致性。
- Worker 必须复用浏览器进程、限制并发、分候选顺序渲染，并对 5 分钟/12 轨场景做性能 Spike。

**降级原则**：Chromium 渲染失败时可以返回可播放的最近成功 Artifact 或明确失败；不得静默切换到听感不同的渲染器并标记为 canonical。

**桥接协议**：Python Celery Task 只通过 `ChromiumRenderAdapter` 驱动 Playwright Chromium；固定 loopback render page 接收 JSON `RenderBridgeRequest`，WAV 经一次性本机 output sink 流式落入 Job 临时区，再由 Python 校验并注册 Artifact。不得用 base64、Redis 或 Graph State 搬运完整音频。pinned Chromium Worker 是 canonical；浏览器 Preview 使用特征/听感容差校验，不要求跨平台逐字节一致。

## ADR-004：Celery + Redis 投递，PostgreSQL Outbox 保证恢复

**决定**：使用 Celery 执行 CPU/IO 长任务，Redis 作为 Broker；PostgreSQL `jobs`、`job_events` 和 `outbox_events` 才是权威状态。

**约束**：

- API 在同一事务中写入业务状态、Job 与 Outbox，提交后由 Dispatcher 发布到 Redis。
- Worker 使用 `idempotency_key` 和数据库状态防止重复副作用。
- Redis 消息按至少一次投递设计；Celery result backend 不是产品事实源。
- 每类失败只有一个重试所有者：Provider Client、Celery、Graph 或用户，不能叠加重试。

## ADR-005：本地音色优先，外部搜索必须显式启用

**决定**：`search_sound_catalog` 默认只检索本地审核 Catalog。用户明确选择“搜索外部素材”后，系统才能调用 Freesound 等 Allowlist Provider；结果只作为候选，显示来源、作者和许可证，用户确认后才进入隔离导入流程。

**约束**：模型不能下载 URL，不能绕过许可证 Allowlist，不能把搜索结果直接写入项目。

## ADR-006：克制的科幻工作台视觉语言

**决定**：以专业深色 DAW 的可读性和信息密度为主体；科幻感用于 AI 选区、频谱、能量曲线、生成状态、运行轨迹和空间层级，不使用大面积霓虹光晕遮盖时间线。

**核心色板**：

| Token | 值 | 用途 |
|---|---:|---|
| `surface.canvas` | `#0B0E14` | 应用背景 |
| `surface.panel` | `#121722` | 主面板 |
| `surface.elevated` | `#182130` | 浮层/选中面板 |
| `border.default` | `#293346` | 分隔与网格 |
| `text.primary` | `#E8EEF7` | 主文字 |
| `text.secondary` | `#93A1B3` | 次级文字 |
| `accent.primary` | `#62E6FF` | 主操作/播放头 |
| `accent.agent` | `#9B7CFF` | AI 与 Graph |
| `accent.creative` | `#FF65C3` | 创作选区/候选差异 |
| `semantic.warning` | `#FFB45E` | 警告 |
| `semantic.success` | `#55DDA4` | 成功 |
| `semantic.danger` | `#FF6B7A` | 错误/危险操作 |

状态不能只靠颜色表达，必须同时使用图标、文字或形状。

## ADR-007：Canvas 时间线 + DOM 控件

**决定**：Timeline、Clip、网格、波形降采样投影和 Piano Roll 主画布使用 Canvas；Track Header、Transport、Inspector、按钮、表单、菜单和无障碍焦点代理使用 DOM。WaveSurfer 只显示选中 Audio Clip 或 Import Review，不是多轨渲染器。

**原因**：保证长时间线、缩放、12 轨和大量 NoteEvent 的性能，同时保留表单、键盘导航与屏幕阅读器语义。

**边界**：首版不引入 WebGL；只有 Canvas 性能 Profiling 未达门槛时再升级。

## ADR-008：副作用函数与 Agent 工具分离

**决定**：采用以下名称和所有权：

| 原名称 | 新合同 | 所有者 |
|---|---|---|
| `apply_timeline_edits` | `simulate_edit_patch` | 只读领域服务/Agent Tool |
| `preview_synth_patch` | `validate_synth_patch`；试听由 Graph 请求 | 纯领域工具 + Graph |
| `commit_revision` | 保留，但仅 Application Service 可调用 | 后端事务层 |
| `render_preview` | `request_preview_render`，只能由 Graph 调度 | Graph/Application Service |
| `search_sound_library` + `search_timbre_catalog` | `search_sound_catalog` | 只读 Catalog Tool |
| `MusicRenderProvider` | `ArrangementRenderer` | 确定性渲染层 |
| 未来音频模型能力 | `InstrumentalAudioProvider` | 隔离生成 Provider |
| `generate_motif` | 保留为带 seed 的确定性算法 | Theory/Composer Tool |

模型输出统一称为 `EditPatchProposal`。只有服务端计算实际 diff 与 ChangeImpact 后，Graph 才能自动提交 L0/L1 或为 L2/L3 创建 PreviewCandidate。

## ADR-009：Revision、PreviewCandidate 与 Branch 指针分离

**决定**：Revision 只表示不可变、已提交的项目历史。待审批内容保存为不可变 Candidate Snapshot + 可变生命周期的 `PreviewCandidate`；批准时创建一个新的 Revision，不把 Preview 原地改成 committed。每个 `ProjectBranch.head_revision_id` 是该分支当前版本的唯一权威指针，`projects.active_branch_id` 只选择当前工作分支；API 的 `current_revision_id` 是读取投影。

**约束**：

- 所有推进 Branch head 或从其派生候选的写入携带 `branch_id + base_revision_id`，并锁定目标 Branch 校验 head；新建 Project/Branch 和 active branch 切换使用各自显式并发字段。
- 完整候选通过 Graph/Application 专用 `materialize_candidate` 提交，只引用不可变 Candidate Snapshot ID + hash；浏览器与模型不能自由调用。
- `set_sections`、`set_markers`、`set_project_key` 是显式系统命令，不能用隐藏的整份 JSON 替换绕过 diff、审批与审计。
- Preview 拒绝、过期或 superseded 不改变 Revision 历史；Branch head 冲突不自动 rebase 创意 Patch。

## ADR-010：框架从初始脚手架引入，领域内核保持框架无关

**决定**：初始工程脚手架即包含 `langchain-core`、`langgraph` 与 PostgreSQL checkpointer；第一条生产 AI 链路直接使用最小 `MotifForgeGraph`。同时保留原生 DeepSeek SDK 的手写 Loop 作为协议与效果 Baseline，不开发一套随后整体迁移的自研生产编排器。

**边界**：首个业务纵切仍是纯领域 `ArrangementIR + EditorCommand + Revision`，人工编辑不经过 Graph。只使用 LangChain 的 Model/Message/Tool/Structured Output 边界与 LangGraph 显式 Graph API；Domain、事务、Job、渲染、重试 Policy 和权限不交给 `create_agent()` 黑盒。

## 可逆的工程默认值

以下选择不会改变核心合同，代码阶段可通过小型 Spike 调整：

- Python 依赖与工作区：`uv`。
- Web 工作区：`pnpm`。
- Python 迁移：Alembic。
- 前端服务端状态：TanStack Query。
- 前端编辑器草稿：Zustand + command reducer。
- API 类型：Pydantic/OpenAPI 生成 TypeScript 类型；前端不手写重复 DTO。
