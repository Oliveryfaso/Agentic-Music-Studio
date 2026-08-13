# Motif Forge 架构决策日志

> 状态：已批准
> 初始决策日期：2026-08-11；最新增补：2026-08-13
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

## ADR-011：Lean Storage Profile 与可重建 Artifact

**决定**：首版默认使用 `Lean Storage Profile`。项目与 Graph 保存可复现的领域状态、生成配方和 lineage；大型派生音频按需渲染、有界保留并可以安全驱逐。这不改变 DeepSeek V4 Flash、四个音乐策略子图、Revision/HITL 或“1–5 分钟完整成曲”的产品目标。

**存储边界**：

- Artifact Root 是可配置的宿主机路径；项目相对 `var/artifacts` 只是 portable/CI/test 的代码级回退。本地 Lean Profile 首次配置默认引导用户选择可写外置卷并写入显式配置；如用户选内置盘也必须显式确认。文档、镜像和代码不硬编码个人绝对路径。
- PostgreSQL 与容器 VM/必需镜像仍位于内置盘；音色包、导入、预览、渲染、导出和可重建缓存优先位于 Artifact Root。
- 外置卷必须通过可写性、剩余空间、同文件系统原子 rename、checksum 和 symlink 边界探测。卷不可用时不得静默回落到内置盘，也不得把所有 Artifact 批量标记为 `missing`。

**Artifact 生命周期**：Artifact metadata 分别保存 `lifecycle_class = durable | protected | rebuildable | ephemeral` 和 `availability = available | evicted | missing | rehydrating`。`evicted` 是按策略删除 bytes 但保留 metadata/配方的预期状态；`rehydrating` 是重建 Job 已受理但 bytes 尚不可用；`missing` 是未预期丢失或校验失败，必须进入错误和修复路由。

- `protected`：用户原始导入、当前 Revision 引用、待审批候选必需的不可重建输入；自动清理禁止删除。
- `durable`：最终选中 Master、manifest、license/provenance 以及长期保留的非可重建素材；只能通过显式用户操作或安全归档流程移除。
- `rebuildable`：waveform peaks、分析、标准化/拉伸派生文件、旧 Revision 渲染缓存和未请求的 Stem；必须有完整 recipe、输入 hash、引擎/策略版本与 lineage 才能驱逐。
- `ephemeral`：Job 临时文件、被拒绝/未选候选的压缩试听和中断残留；由 TTL 与 Job 终态清理。

**渲染策略**：A/B 中两个候选都保留完整不可变 `CandidateSnapshot/ArrangementIR`，但默认只产生完整时长的 `candidate-preview.v1`（MP3 160 kbps）试听；局部 Repair/素材 audition 使用最多 15 秒的 `audition-lite.v1`（MP3 128 kbps）。选中候选后按需生成 `canonical-master.v1`（48 kHz stereo、PCM24 WAV），只在用户请求 Stem 导出时生成同规格逐轨 WAV。“支持完整产出”是导出能力合同，不是预先永久保存每个候选的全部 Stem。

**音色分层**：四个 Style Pack 保持同时交付，但以紧凑的知识卡、符号示例、Synth Preset 和少量经审核 one-shot 为主。默认 `Core Sound Palette Lite` 目标 0.5–1 GiB；高采样层 multisample 作为可选 `HQ Instrument Pack` 安装到 Artifact Root，不进入首版必装与默认容器镜像。

**预算与治理**：内置盘干净安装目标为 6–10 GiB，构建/升级临时峰值为 12–15 GiB，Build Cache 目标上限 2 GiB。Artifact Root 默认全局硬配额 10 GiB、单项目软配额 2 GiB、临时区硬配额 2 GiB，均可配置；压缩试听默认 TTL 24 小时，可重建派生缓存和终态 checkpoint 默认 TTL 7 天。`StoragePressureGate v1` 在 Upload/Render/Fan-out/Export 前使用确定性规则估算容量、清理已过期且可安全驱逐的内容，然后输出 `proceed | gc_then_retry | rehydrate_then_resume | wait_for_storage | fail`；模型不参与存储删除决策。

## ADR-012：版本化音频质量档位与外置优先开发数据

**决定**：所有派生音频通过版本化 `MediaQualityProfile` 生成，首版固定为 `source-original.v1`、`audition-lite.v1`、`candidate-preview.v1`、`working-pcm.v1`、`canonical-master.v1` 和 `canonical-stem.v1`。质量档位与精确媒体参数进入 Artifact metadata、recipe、cache key 和 trace；低质量试听不能覆盖原件或替代最终交付。

**外置优先**：checkout、Web dependencies、音色包、导入、试听、波形/分析、派生音频、导出、音频 Eval fixture 与可迁移工具 cache 放在外置盘。只有 Colima/Docker VM、PostgreSQL/Redis 活跃 Volume、当前必需镜像和因文件系统兼容性必须本地保存的最小环境留在内置盘。外置 Root 不可用时停止新写入，不静默回落。

**原因**：128/160 kbps 试听显著减少 A/B 与迭代缓存，而结构化 IR、Graph、HITL、可恢复 Worker 和最终 PCM24 导出合同不受影响。工作 PCM 保持 48 kHz/PCM16，以免连续编辑、time-stretch 与分析因有损重编码累计退化。

## ADR-013：按变更频率分层镜像，资源模式逐模块评估

**决定**：Media Worker 把 FFmpeg/toolchain 放在稳定基础层，再复制高频变化的 Python venv 与 migration；日常构建必须选择实际变化的 target，不默认重建 API、Media Worker 和 Chromium Worker 全集。未来模块不得机械照搬“一模块一镜像”或同一缓存策略，必须用运行隔离、稳定层复用、冷构建、缓存归属、外置可行性和质量影响作出单独决策。

**本机验证边界**：曾以带 1.5 GB GC 上限的 `docker-container` builder 做可逆试验，但当前 Colima 代理路径无法让容器化 BuildKit 访问 Docker Hub；失败发生在拉取 base metadata 前，没有生成有效构建缓存。该 builder、容器和专用 BuildKit 镜像已移除，不为“形式上的隔离”保留额外常驻组件。本机继续使用已有 Colima builder；只有缓存记录能证明属于本项目时才执行容量 prune。

**音频质量结论**：降低当前试听码率不会缩小 Docker。5 分钟 stereo PCM16 约 57.6 MB、PCM24 约 86.4 MB；同长度 MP3 160 kbps 约 6 MB、128 kbps 约 4.8 MB、96 kbps 约 3.6 MB。两个完整候选从 160 降至 128 kbps 仅再省约 2.4 MB，从 160 降至 96 kbps 约省 4.8 MB，却更容易损伤高频、瞬态和空间效果。首版因此维持 128/160 kbps 试听、PCM16 工作文件和 PCM24 最终文件，把收益重点放在 TTL、按需 Stem、外置 Root 和可重建缓存驱逐，而不是继续降低质量。

## ADR-014：热路径白名单与封版零投机缓存

**决定**：开发期 BuildKit 缓存使用显式热路径白名单，而不是“可能以后有用”的宽松保留。每个阶段结束前只从 API、Media Worker 与 Chromium Render Worker 中刷新下一阶段确定使用的 target；当前 tagged image、运行中 service image 和 lockfile 属于 keep set，旧 build context、失败构建、被替代的源码/依赖层属于 cold set。共享 Colima builder 的目标为约 1.5 GiB、硬上限 2 GiB；先按最后使用时间移除 cold records，再按 LRU 容量收口。若必要热集仍超过上限，优先保留可运行镜像并接受下一次冷构建，不为构建速度继续扩大预算。

**封版规则**：项目功能完备、发布封版或长期停开发时，BuildKit cache 不属于交付物。保留当前发布镜像、数据库/Artifact 合同、lockfile、Dockerfile 和可复现说明，清空项目拥有的构建缓存。共享 builder 只有在所有权已证明时才能做全量清理；否则先迁移到可用的项目 builder，不能以封版为由删除其他项目数据。

**实现约束**：最新 tagged image 写入 inline cache metadata，供受支持的 registry/publish 恢复路径使用；本机 shared builder 不假定能从 local tag 导入 cache。清理脚本必须显式 opt-in、拒绝可见活动构建、先后输出 inventory，不执行 volume prune、image prune 或数据库/Artifact 删除。

## ADR-015：短前置收口门与纵切内优化

**决定**：从已完成的 Import/Analysis/Alignment/Web Preview 纵切进入创作主链路前，只设置一次短的开发前收口门：同步“目标”与“当前事实”文档、复验基线、冻结单一 Parent Graph 演化方向，并把已验收工作形成可恢复的 Git checkpoint。通过后不设置独立的全仓重构阶段；Graph 合并、Router/Repository 拆分、OpenAPI DTO 生成、SSE 和 Trace 接线必须随使用它们的业务纵切完成。

**原因**：当前底层可靠性工程领先于音乐创作能力。全面先重构会继续推迟完整作品，完全不收口又会把大量未提交状态、文档漂移和暂时双 Graph 放大到新链路。短门禁控制回退风险，纵切内优化则让边界由真实用例和测试驱动。

**下一产品断点**：开发前收口后，优先完成不依赖 LLM 的 60–90 秒、4 轨、单候选 Synth Ambient Walking Skeleton：固定 Brief/模板 → PatternSpec → ArrangementIR → 正式 Chromium Render Job → Master WAV/MIDI/Project Manifest。这是内部验收里程碑，不降低首版 1–5 分钟、最多 12 轨、最多 2 候选和四个 Style Pack 同时交付的合同。

**约束**：

- 现有 `motif-forge-plan.v3` 必须作为 `generate` 子图并入唯一 Parent Graph；禁止新增第三个生产 Graph。
- 除新增 Artifact 类型所必需的接线外，完整成曲 Walking Skeleton 通过前不继续扩建通用存储/恢复平台。
- 不因文件行数单独发起重构；只有纵切触达且模块职责继续增长时，才在测试保护下提取该职责。
- 自下一创作纵切起同步增加 Eval，不把评测推迟到产品功能全部完成之后。
- 当前事实、下一路线和历史记录分别维护在 `IMPLEMENTATION_STATUS.md`、`NEXT_DEVELOPMENT_ROADMAP.md` 与 `TECH_EVOLUTION.md`，不得把目标合同误写成完成状态。

## ADR-016：作品集工程模式与后置重点硬化

**决定**：从 S2 Task 6 起采用“作品集工程模式”。当前优先级是尽快形成一条真实、完整、可演示、可解释的 Agent 音乐创作闭环，而不是在每个中间 Task 都达到多租户生产平台的穷举可靠性标准。最终产品架构和用户价值合同不降低；准生产硬化改为风险驱动并集中到产品主功能接近完成后的 S7/封版门。

**当前不可降低的作品集门槛**：

- 只有一个版本化 Parent Graph；Generate 的计划、HITL、确定性编译、Worker 等待、恢复与结束状态都回到同一有限 thread。
- DeepSeek 只输出受 Schema 约束的 CompositionPlan；确定性 Fallback 可用，所有从零生成都经过真实 PlanApproval。
- ArrangementIR/Revision 是项目事实源；模型不能直接写 Revision、调度任意 Job、操作文件路径或绕过预算与权限。
- PostgreSQL 持久化 Run/checkpoint/event/usage，至少证明一次跨进程恢复不会重复付费调用、Revision 或导出副作用。
- 复用 S1 的 Master、四 Stem、MP3、MIDI、Project 与 manifests 完整导出链，并完成一次无付费 Compose smoke 和一次预算受控的真实 DeepSeek 验收。
- 每个创作阶段保留代表性 Eval、结构化 Trace/usage、明确失败标签；S7 再汇总到最终作品集数据集和量化报告。

**当前不作为每个 Task 的阻塞项**：

- 每个 checkpoint 的崩溃注入、所有取消时点、所有重复投递排列和极端并发交错。
- 对所有历史数据库版本做 populated downgrade；新增持久化仍须有前向迁移、当前版本读写证明和不可安全降级时的 fail-closed guard。
- 每个 Task 都重建全套 Docker、运行全仓/全浏览器/全 Worker 测试，或清空并重建所有缓存。
- 为尚未出现的多租户、水平扩缩、长时间负载、全量 OTel 看板、P95 容量和灾备需求预建平台能力。
- 为把所有非核心 Important/Minor 清零而进行无上限复审；不影响当前用户主路径、数据完整性、Secrets、模型费用、HITL 或可恢复性的事项进入后置硬化清单。

**审查与验证节奏**：每个 Task 仍先 RED 后 GREEN，运行窄单元测试和一个真实边界集成；每 2–3 个 Task 或跨服务接线点运行一次组合回归，S2 结束运行一次完整阶段门。每个 Task 默认一次独立审查和最多一次修复复审；若届时仍有阻塞项则停止并升级给用户，不继续无限循环。Critical 永远阻塞；Important 只有在影响当前主路径、不可逆数据、Secrets/权限、重复付费、副作用幂等、HITL 或恢复时才阻塞，其余必须记录到路线的后置硬化清单，不能静默遗忘。S2 剩余每个 Task 使用一个新 Session，从 clean checkpoint 和精简 handoff 开始，避免重复加载历史审查上下文。

**重新升级硬化优先级的触发器**：真实数据损坏/越权/Secret 泄露、重复付费或重复 Revision/Artifact、用户主路径无法恢复、同一缺陷出现两次、准备公开发布/多人使用/长时间运行，或测量数据证明性能/容量已成为瓶颈。触发后只补对应风险的测试和实现，不恢复机械式全矩阵证明。

## 可逆的工程默认值

以下选择不会改变核心合同，代码阶段可通过小型 Spike 调整：

- Python 依赖与工作区：`uv`。
- Web 工作区：`pnpm`。
- Python 迁移：Alembic。
- 前端服务端状态：TanStack Query。
- 前端编辑器草稿：Zustand + command reducer。
- API 类型：Pydantic/OpenAPI 生成 TypeScript 类型；前端不手写重复 DTO。
