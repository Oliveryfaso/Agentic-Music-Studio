# Motif Forge 代码架构规范

> 状态：首版架构基线
> 依赖决策：[DECISION_LOG.md](./DECISION_LOG.md)
> 本文描述代码应该放在哪里、谁可以调用谁，以及一次操作如何穿过各层。

## 1. 架构目标

首版架构必须同时满足：

- 不依赖 LLM 也能导入、编辑、播放和导出一首完整作品。
- DeepSeek 只做音乐语义和创意决策，所有输出都可验证。
- 一个版本化 Graph 拓扑覆盖导入、生成、编辑、导出、HITL 和异常恢复。
- PostgreSQL Revision 是持久事实，前端状态、Graph checkpoint、Redis 和音频节点都不是项目事实源。
- 浏览器试听与 Worker 导出共用同一个 AudioGraph 编译语义。
- 任意模型、Worker 或网络失败都不会覆盖原始音频或已提交 Revision。
- 采用 Lean Storage Policy：完整保留可重建作品所需的 Revision、Candidate Snapshot、生成配方和来源，音频中间产物按生命周期回收；回收缓存不能让完整成曲和高质量导出变成不可达能力。

## 2. 运行时组件

```mermaid
flowchart TB
    WEB["web：React Studio"]
    API["api：FastAPI"]
    GRAPH["agent runtime：LangGraph"]
    DISPATCH["outbox dispatcher"]
    REDIS["Redis broker"]
    WORKER["Celery worker"]
    CHROME["Chromium render runtime"]
    PG["PostgreSQL"]
    STORE["Content-addressed Artifact Store"]
    DEEPSEEK["DeepSeek V4 Flash"]
    EXTERNAL["Allowlist Sound Provider"]

    WEB <-->|"REST + SSE"| API
    API --> GRAPH
    API --> PG
    GRAPH --> PG
    GRAPH --> DEEPSEEK
    GRAPH -->|"write Job + Outbox"| PG
    PG --> DISPATCH
    DISPATCH --> REDIS
    REDIS --> WORKER
    WORKER --> CHROME
    WORKER --> STORE
    WORKER --> PG
    API --> STORE
    GRAPH -. "explicit external search" .-> EXTERNAL
```

首版 Docker Compose 至少包含 `web`、`api`、`worker`、`dispatcher`、`postgres` 和 `redis`。Chromium 可以运行在 `worker` 镜像中；若性能隔离测试表明需要独立资源限制，再拆为单独 `render-worker` 服务，不改变 Job Contract。

默认部署把 Docker/Colima VM、PostgreSQL Volume、Redis Volume 和运行时元数据留在内置盘；可增长的上传、音色、试听、渲染和导出 Artifact 通过一个受控 `ARTIFACT_ROOT` 挂载到外置盘。Artifact Repository 是唯一解释该配置并解析物理位置的组件；API、Graph、Worker Job、事件、数据库和浏览器只传 Artifact ID/ref，均不得接收或持久化任意客户端路径。

## 3. 建议仓库结构

```text
agentic-music-workbench/
  apps/
    web/
      src/
        app/                 # 路由、Provider、全局错误边界
        features/            # import、plan、studio、compare、export、runs
        entities/            # project、revision、track、clip、run、artifact
        audio/               # 浏览器 AudioEngine 与 Transport adapter
        editor/              # command bus、selection、draft、undo/redo
        shared/              # 生成的 API 类型、UI primitives、tokens
  services/
    api/
      src/motif_forge/
        api/                 # FastAPI routers、DTO、SSE
        application/         # use cases、事务、权限、幂等
        domain/              # 纯领域模型、命令、规则、diff、validator
        agent/               # graph、nodes、subgraphs、state、prompts
        audio/               # Python media operators；不复制 Tone 合成语义
        providers/           # DeepSeek、外部音色、可选 OTel adapter
        infrastructure/      # Postgres、Celery、Artifact、outbox
        worker/              # Dispatcher、Celery entrypoint、Job executor
          tasks.py           # 只接收 Job ID
          execution.py       # claim/heartbeat/handler/完成事件
          outbox.py          # SKIP LOCKED + publish lease
          celery_app.py      # 至少一次投递配置
  packages/
    contracts/               # OpenAPI snapshot、JSON Schema、事件 Schema
    audio-engine/            # TS AudioGraphSpec + compiler + Tone adapters
  resources/
    policies/                # 版本化决策表
    style-packs/             # 四个 Style Pack
    sound-palette/           # manifest、preset、sample license snapshot
    prompts/                 # 版本化 Prompt assets
  tests/
    contract/
    integration/
    failure-injection/
    eval/
  infra/
    compose/
    migrations/
  docs/
```

首版 Worker 与 API 共享同一个 Python distribution，但由独立 Compose process 和独立
`media-worker` 镜像 target 运行；FFmpeg 只存在于 Media Worker target。以后拆成
`services/worker` 时保持相同 Application/Domain imports 和 Job/Event 合同，不能复制业务规则。
镜像分层按变更频率而不是目录顺序设计：Media Worker 的 FFmpeg/toolchain 是稳定基础层，
应用 venv 与 migration 在其后复制，避免普通源码变更复制整套音频工具链。该模式不是所有
未来模块的模板；Chromium、可选 HQ 音色、端到端模型或新的 Worker 必须分别比较隔离收益、
运行体积、冷构建成本、缓存归属、外置可行性和质量影响，再决定复用、拆镜像或按需安装。

目录表达依赖方向，不要求第一天创建全部空目录。实现时只为当前 vertical slice 建立必要路径。

## 4. 依赖方向

```mermaid
flowchart LR
    API["API adapters"] --> APP["Application use cases"]
    GRAPH["Graph nodes"] --> APP
    WORKER["Worker adapters"] --> APP
    APP --> DOMAIN["Pure domain"]
    APP --> PORTS["Ports / protocols"]
    INFRA["Postgres / Celery / Provider adapters"] --> PORTS
    AUDIO["Audio engine adapters"] --> CONTRACT["AudioGraphSpec"]
    DOMAIN --> CONTRACT
```

禁止依赖：

- `domain` 不导入 FastAPI、LangGraph、Celery、SQLAlchemy、Tone.js 或 DeepSeek SDK。
- Graph Node 不直接执行 SQL、写文件、调用 Celery API 或创建 Web Audio 节点。
- API Router 不包含音乐规则、Graph 路由或事务拼装。
- React Component 不直接拼 HTTP DTO、不直接修改 `ArrangementIR`、不持有服务器路径。
- Worker 不提交项目 Revision；它只写 Artifact、Job 状态和持久事件。
- Model Provider 不拥有重试预算、ChangeImpact 或 HITL 决策。

## 5. 层级职责与核心入口

| 层 | 核心入口 | 输入 | 输出/副作用 |
|---|---|---|---|
| API | Router | HTTP/SSE | DTO、状态码、事件流 |
| Application | Use Case | 已验证 DTO + ActorContext | 事务、Graph 启动、Job/Outbox |
| Domain | Command Handler/Validator | IR、命令、规则事实 | 新 IR、diff、issue；无外部副作用 |
| Agent | Graph Node | compact state + refs | state update、proposal、Job 请求 |
| Provider | DeepSeek Adapter | versioned prompt/schema | validated structured result + usage |
| Worker | Celery Task | Job ID | Artifact + JobEvent；不改 Revision |
| Audio | AudioGraphCompiler | ArrangementIR/范围 | AudioGraphSpec / Tone graph |
| Persistence | Repository/UoW | domain objects | PostgreSQL transaction |

### 5.1 关键函数的唯一存放位置

| 函数/合同 | 建议模块 | 禁止重复实现的位置 |
|---|---|---|
| `validate_command/apply_command` | `domain/commands` | React、Router、Graph Node |
| `simulate_edit_patch` | `domain/revisions` | Provider、Worker、Repository |
| `compute_change_impact` | `domain/policies` | Prompt、前端判断、Celery Task |
| `commit_revision` | `application/revisions` | Agent Tool、Worker、API Router |
| `persist_candidate_snapshot` | `application/candidates` | Agent Tool、React、Worker |
| `create_preview_candidate` | `application/previews` | Agent Tool、React |
| `materialize_candidate_revision`（处理 system command `materialize_candidate`） | `application/revisions` | Agent Tool、Worker、浏览器公共命令 |
| `enqueue_job` | `application/jobs` | Graph Node 内直接调用 Celery |
| `search_sound_catalog` | `application/catalog` + read-only port | Prompt 内自由检索、浏览器直连 DB |
| `validate_synth_patch` | `domain/audio_specs` | Tone Node、Provider 私有逻辑 |
| `compile_pattern/generate_motif` | `domain/composer` | LLM Provider、前端 |
| `build_audio_graph_spec` | `packages/audio-engine` | Python Worker 的第二套合成语义 |
| `request_preview_render` | `application/renders` | Agent Tool |
| `evaluate_storage_pressure` | `domain/policies/storage_policy` | Graph、Router、Worker 各自估算 |
| `read/list_feature_artifact` | `application/features` | React、API Router |
| `rehydrate_artifact` | `application/media_jobs` | React、Graph Node、Worker Task |
| `resolve_artifact_location` | `infrastructure/artifacts` | API DTO、Graph State、Job payload |
| `classify_error` | `domain/policies/error_policy` | LLM、Celery 自动猜测 |
| `resume_run_from_event` | `application/runs` | Worker Task |

Router 只做 DTO/HTTP 映射，Graph Node 只编排这些入口；同一规则不能在前端、Graph、Worker 各复制一份。

Feature 数据流固定为 `AudioArtifact → deterministic extractor → content-addressed JSON → FeatureArtifact metadata → API view`。PostgreSQL 只保存 metadata/recipe，不保存完整 peaks；前端先按 source Audio Artifact 列 metadata，再按需读取单个 available Feature。驱逐/恢复仍走统一 StoragePressureGate 和 Parent Graph，不由页面直接重算。

## 6. 用户动作到函数调用的映射

### 6.1 人工简单编辑

```text
Timeline gesture
→ EditorCommandBus.dispatch(command)
→ Local Draft reducer + AudioEngine preview
→ POST /projects/{id}/command-batches
→ CommitCommandBatchUseCase
→ Domain.validate_commands
→ Domain.apply_commands
→ Domain.compute_change_impact
→ RevisionRepository.commit_revision
→ project.revision.committed SSE
```

人工编辑只能提交已知命令。服务器返回 409 时，前端保留本地命令并进入冲突解决，不覆盖当前 Revision。

### 6.2 AI 局部编辑

```text
POST /projects/{id}/ai-runs
→ StartRunUseCase
→ MotifForgeGraph(edit)
→ EditPlanner(DeepSeek)
→ simulate_edit_patch
→ validate_patch + compute_actual_change_impact
→ L0/L1: CommitRevisionUseCase
→ L2/L3: PersistCandidateSnapshot → CreatePreviewCandidateUseCase → HITL
```

`simulate_edit_patch` 返回候选 IR 引用和 diff，不提交 Revision。`commit_revision` 从不出现在 Model Tool Schema 中。

### 6.3 完整生成

```text
Brief
→ finite generation Run
→ knowledge/style routing
→ CompositionPlan
→ plan approval
→ two candidate subgraph branches
→ PatternSpec/SynthPatchSpec
→ deterministic compile
→ persist complete Candidate IR + recipe
→ full-length compressed Preview Render Jobs
→ analysis/critic/repair
→ A/B approval
→ materialize_candidate(candidate snapshot hash)
→ committed Revision + Branch head advance
→ on-demand lossless Master/Stem export
```

候选阶段永久保存完整 Candidate Snapshot/IR、seed、资产 checksum 和渲染配方；A/B 各生成完整时长的压缩试听，但不预生成 12 条无损 Stem。用户选择后仍能物化完整 Revision，并在导出时按需生成 48 kHz/24-bit Master WAV、所选 Stem、MIDI 和 manifest，因此 Lean Profile 降低的是缓存占用与旧版本即时打开速度，不降低 Graph 完整性或最终导出规格。

### 6.4 导入与 Time-stretch

```text
Upload Session
→ Quarantine Artifact
→ finite import Run
→ Import Policy
→ Celery ingest/analyze Job
→ user confirmation when confidence is low
→ optional TimeStretch Job
→ Import Revision
```

拉伸完成前可以播放原始未对齐音频，但不能用会改变音高的 `playbackRate` 冒充保持音高预览。

### 6.5 导出

```text
POST /projects/{id}/exports
→ finite export Run
→ license/asset/revision validation
→ StoragePressureGate
→ rehydrate evicted dependencies when required
→ canonical Chromium Render Job
→ analysis gate
→ FFmpeg transcode
→ Master/Stems/MIDI/Manifests
```

## 7. 前后端契约生成

Pydantic v2 是 HTTP DTO、事件和领域公共 Schema 的权威定义。构建流程输出：

1. OpenAPI 文档。
2. `ArrangementIR`、`EditorCommand`、`RunEventEnvelope` 等 JSON Schema。
3. 自动生成的 TypeScript 类型。

前端不得维护第二套手写同名 DTO。开发 CI 对生成文件执行 diff；Schema 改变必须增加 `schema_version` 并提供迁移或兼容说明。

## 8. AudioGraph 标准渲染

`packages/audio-engine` 包含：

- `AudioGraphSpec`：纯 JSON、无 Tone/Web Audio 对象。
- `compileArrangementRange`：IR + range → AudioGraphSpec。
- `buildToneGraph`：AudioGraphSpec → Tone nodes。
- `scheduleTransport`：tick → AudioContext time。
- `renderOffline`：在 Chromium OfflineAudioContext 中渲染。

Python Celery Worker 通过唯一的 `ChromiumRenderAdapter` 驱动 Playwright Chromium：加载固定 loopback `render.html` 和 pinned bundle，以 JSON `RenderBridgeRequest` 调用页面；页面把 WAV 二进制流式写入一次性、仅 loopback 可访问的输出 sink，Python 再校验 checksum、媒体属性并注册 Artifact。禁止通过 base64/Redis/Graph State 传递完整音频，也禁止在 Python 中复制第二套 AudioGraph 语义。

浏览器和 Worker 必须使用相同版本的 `audio_engine_version`、相同资产 checksum、采样率、seed 和图参数。Master/Stem manifest 记录这些版本。

### 8.1 性能 Spike 门槛

实现标准渲染前必须测试：

- 1、3、5 分钟工程。
- 4、8、12 轨。
- Synth、Sampler、长混响和 automation 的代表组合。
- 冷启动与 Chromium 复用后的 P50/P95。
- 峰值内存、CPU 时间、Artifact 大小、取消延迟。
- 浏览器 Preview 与 Worker Render 的特征差和人工 A/B；目标是语义/听感容差一致，不是跨平台逐字节一致。

首版默认 Worker 并发为 1；候选 fan-out 可以并行生成结构，但完整音频渲染默认排队，避免两个 Chromium Render 同时耗尽本地资源。具体资源阈值由 Spike 写入版本化 Render Policy。

### 8.2 Lean Storage 与 Artifact 生命周期

Artifact 元数据、内容 hash、来源/许可证、生成配方、依赖 refs 和生命周期状态保存在 PostgreSQL；二进制内容保存在 content-addressed Artifact Store。标准状态为：

- `available`：内容存在、checksum 通过且可读。
- `evicted`：内容按策略回收，但依赖和确定性重建配方齐全。
- `missing`：内容不可读且不存在可验证的重建路径，或其不可替代来源已丢失。
- `rehydrating`：显式重建 Job 正在恢复内容。

只有 `available → evicted → rehydrating → available` 是正常缓存生命周期；校验失败、外置盘断开或不可重建依赖不能伪装成 `evicted`。原始用户上传、当前 Revision 引用的不可替代素材、许可证快照、Candidate Snapshot/IR、最终选中 Master 和 manifest 不得由自动 GC 删除。可回收项包括 waveform peaks、分析缓存、time-stretch 衍生文件、旧 Preview、未选中候选试听和按需 Stem；删除二进制前必须先以事务写入生命周期状态与审计事件。

`StoragePressureGate` 是共享 Domain Policy 产生的确定性决策，不调用模型。它读取经 Repository 验证的事实：Artifact Root 健康状态、文件系统可用字节、预计输出字节、全局/项目配额、当前临时占用、目标 Revision 的受保护 Artifact refs 和版本化 Storage Policy。它只能路由到：

1. `proceed`：容量和挂载健康满足原始请求。
2. `gc_then_retry`：仅回收 Allowlist 中可重建且未受保护的内容，再以同一 operation ID 重算一次。
3. `rehydrate_then_resume`：请求依赖处于 `evicted`，显式启动重建后从当前 checkpoint 恢复。
4. `wait_for_storage`：外置 Artifact Root 断开或空间仍不足，进入可恢复人工 Interrupt；不得静默写入内置盘作为替代。
5. `fail`：依赖为 `missing`、配额/安全约束不可满足或重算后仍超限。

错误至少区分 `ARTIFACT_ROOT_UNAVAILABLE`、`STORAGE_QUOTA_EXCEEDED`、`ARTIFACT_EVICTED`、`ARTIFACT_REHYDRATING`、`ARTIFACT_MISSING` 和 `ARTIFACT_REHYDRATION_FAILED`。Trace/事件记录 policy version、root health 枚举、free/estimated/reclaimed bytes、quota scope、受保护/回收 Artifact 数量和 route，不记录物理路径。Eval 覆盖路由正确率、误删率（目标 0）、重建成功率、断盘恢复率、回收后完整导出成功率、额外 P95 延迟与写放大。

所有输出落到同一 Artifact Root 下由 Repository 管理的 content-addressed namespace 和 per-job 临时区。临时区任务成功、失败或取消后均进入有界清理；Worker 不接受 output path，Chromium 的一次性 loopback sink 也只能由基础设施层创建。

## 9. 配置与 Secret

- `DEEPSEEK_API_KEY` 只进入 API/Agent 运行环境，不进入 Web、事件、trace 或 Artifact manifest。
- 外部音色 Provider Token 只在服务端 Connector 中可见。
- PostgreSQL、Redis、Artifact Root 和 Chromium 参数通过环境配置，仓库只提供 `.env.example`。
- 本地 Lean Profile 必须显式配置 `ARTIFACT_ROOT` 为外置盘上的项目专用目录；启动时验证挂载标识、可写性和最小空间，不可用时不得回退到系统临时目录或内置盘。代码中的相对 `var/*` 只作为 CI/test/portable fallback，必须由对应 profile 显式启用，不是本地开发首选；仓库不得硬编码任何个人绝对路径。
- Prompt、Policy、Style Pack、Schema、Graph 和 Audio Engine 都有独立版本；Run 与 Revision 保存实际使用版本。

## 10. 代码阶段验收顺序

每个 vertical slice 必须同时定义成功、错误、取消、重试、恢复、Trace 和 Eval。`langchain-core`、`langgraph` 与 PostgreSQL checkpointer 可以在初始工程脚手架中安装并完成 smoke test；首个业务切片仍是纯领域的 `ArrangementIR + EditorCommand + Revision`，不把无需 Agent 的人工编辑强行路由进 Graph。

第一条 AI 业务切片直接使用最小 `MotifForgeGraph`（ValidateBrief → CompositionPlanner → ValidatePlan → PlanApproval Interrupt），同时保留一个原生 DeepSeek SDK 的手写 Loop 作为协议/Baseline 测试。生产路径不经历“先写一套自研编排、再整体迁移”的返工，但框架适配层也不能取代 Domain、Application、Provider 和 Job 边界。

当前代码已完成 Import/Analysis/Alignment/Web Preview，但最小 CompositionPlan Graph 仍是尚未挂入 API 的先行纵切。后续不再建立平行编排器：先用确定性 Pattern/Render Walking Skeleton验证 `CompositionPlan/模板 → PatternSpec → ArrangementIR → AudioGraphSpec → Artifact` 边界，再把计划节点作为唯一 Parent Graph 的 `generate` 子图接入。大文件拆分、公开 DTO 生成、SSE 和 Trace 等优化只随触达它们的纵切实施；当前断点和精确依赖顺序见 `IMPLEMENTATION_STATUS.md` 与 `NEXT_DEVELOPMENT_ROADMAP.md`。
