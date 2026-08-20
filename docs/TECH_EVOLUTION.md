# Motif Forge 技术演进记录

## 2026-08-11：阶段 1 实施启动

- 用户明确授权开始编写产品代码。
- 首个实现切片为“领域脊柱 + 框架化最小 Agent 纵切”。
- Python 目标版本为 3.12，使用 uv 管理依赖。
- 从脚手架引入 LangChain Core、LangGraph 和 PostgreSQL checkpointer；不使用黑盒 `create_agent()`。
- 原生 DeepSeek V4 Flash Loop 只作为协议/Baseline，测试默认使用 Fake Provider，不消耗外部 API。
- Docker Compose 当前只包含 API、PostgreSQL、Redis；Celery、Worker、Chromium 和 Web 在对应真实切片中加入，不预建空服务。

### 已落地的第一批代码

- 建立 Python 3.12 + uv 工程、FastAPI 工厂、secret-safe 配置、live/ready 健康接口和 API 镜像。
- 建立严格冻结的 `ArrangementIR v1`、PPQ 时间换算、canonical JSON/SHA-256、typed EditorCommand 纯函数以及不可变 Revision/Branch/Candidate/Preview 值对象。
- 建立首条显式 LangGraph：`ValidateBrief → CompositionPlanner → ValidatePlan → PlanApproval Interrupt → terminal`；测试使用 `InMemorySaver` 验证 interrupt/resume。
- 建立 PostgreSQL Async Checkpointer 生命周期工厂：独立 `motif_forge_graph` schema、受控 schema identifier、LangGraph 自有幂等 setup；本轮只做无数据库副作用的单元契约测试，真实容器恢复测试留在持久化切片。
- 建立原生 DeepSeek V4 Flash JSON Adapter：thinking mode、顶层 `reasoning_effort=high`、严格响应 Schema、usage、finish reason、超时/网络/429/5xx 有界指数退避与安全错误映射；测试不访问真实 API。
- 建立有限手写 planning baseline、版本化 planner prompt 和首条 eval fixture。

### 本轮验证

- `pytest`：39 passed。
- 覆盖率：82%（branch coverage enabled）。
- Ruff：通过；Mypy strict：通过；uv lock：通过。
- `compose.yaml` 已完成 YAML 解析；当前机器没有 Docker CLI，因此尚未执行真实 PostgreSQL/Redis 容器 smoke test。

### 明确未完成

- 阶段 1 仍缺真实 PostgreSQL restart/resume 集成测试、一次 Schema repair、完整 Error Router/预算/Trace，以及 thinking tool-call 的 `reasoning_content` 续传契约。
- 尚未实现 Revision Repository/UoW/API、音频编译/渲染、Celery Worker、四个知识包内容和 Web Studio；这些不会被健康脚手架伪装成完成状态。

## 2026-08-11：阶段 1 PostgreSQL 事务纵切

- 引入 SQLAlchemy 2 async 与 Alembic，业务表使用独立 `app` Schema；LangGraph checkpoint 继续使用独立 `motif_forge_graph` Schema，二者职责分离。
- 创建 Project 时在一个事务中创建空 Arrangement、Root Revision、`main` Branch、active branch、审计事件和幂等结果。
- 人工 L0/L1 Command Batch 使用 `SELECT FOR UPDATE + base_revision_id + CAS` 推进 Branch head；生成不可变 Revision、命令日志、审计记录和幂等结果。
- 变更等级只由服务端 `compute_change_impact` 计算；L2/L3 不直接写入 Revision，统一升级到 Candidate Preview 与人工审批流程。
- 建立 `/api/v1/projects` 与 `/api/v1/projects/{project_id}/command-batches`，补齐成功 Envelope、Problem Details、请求/Trace ID、幂等 Header 和身份边界。
- Docker Compose 新增一次性 `migrate` 服务；API 仅在 Alembic migration 成功且 Redis 健康后启动。
- 增加真实 PostgreSQL 集成测试合同：Project 原子创建/幂等、L1 提交、stale conflict、L2 rollback，以及 LangGraph 断连后 restart/resume 与 Schema 隔离。

### 本轮验证

- 不依赖外部服务的测试：`60 passed, 3 skipped`；3 项明确跳过的测试都要求真实 PostgreSQL DSN，不使用 SQLite 冒充。
- Ruff、Ruff format、Mypy strict、uv lock 均通过。
- Alembic upgrade/downgrade 离线 SQL 编译通过。
- 当前机器尚无 Docker CLI 与 Linux 容器 daemon，因此真实 PostgreSQL/Redis Compose 验收仍待运行。

### 下一实现边界

- 真实容器验收通过后，进入 Candidate Snapshot / Preview / Approval 事务闭环，让 L2/L3 AI 修改在批准后原子落为 Revision。
- 随后再接 Redis Worker、Outbox/Event 与首条渲染 Job；不让 FastAPI 请求承担长音频任务。

## 2026-08-11：Lean Storage 合同与开发环境收缩

- 保留 DeepSeek V4 Flash、LangGraph/HITL、四个 Style Pack、两个完整候选 IR、1–5 分钟完整成曲和 48 kHz/24-bit 最终 WAV；缩减的是默认音色体积、派生文件保留时间和候选无损预渲染，不是 Agent 工作流能力。
- 本地 Lean Profile 将 Artifact、临时音频、uv/pnpm/Playwright 可移动缓存显式放到外置 Root；相对 `var/*` 仅为 portable/CI/test fallback。Docker VM、PostgreSQL、Redis 和 Python venv 保留在内置 APFS，禁止外置盘失联后静默回落。
- 采用四级 lifecycle、四态 availability、RebuildRecipe、10 GiB 全局/2 GiB 项目/2 GiB 临时额度，以及 24 小时试听、7 天派生缓存/终态 checkpoint TTL。
- `StoragePressureGate` 固定为 `proceed | gc_then_retry | rehydrate_then_resume | wait_for_storage | fail` 五路由；它是确定性 Policy，不调用模型。
- 当前代码只加入 secret-safe 配置、Lean Profile 绝对路径校验、额度校验、精简 API runtime 镜像、Docker build context 排除项和非破坏性外置盘引导脚本。Artifact Repository、挂载/可写性探测、配额执行、GC、重建 Job 与 UI 状态尚未实现，不在本轮伪装为可用。
- Artifact metadata/recipe 尚未出现在当前业务迁移中；对应 Worker/Artifact 纵切必须新增可回滚 Alembic 迁移，并通过 bytes/checksum 探测 backfill 旧记录。

## 2026-08-11：阶段 1 真实容器验收完成

- 安装并验证原生 arm64 Docker CLI 29.7.2、Compose 5.4.0、Buildx 0.36.1 与 Colima 0.10.3；不安装 Docker Desktop、Kubernetes、QEMU、Rosetta 或 Chromium。
- Colima 采用 4 CPU、4 GiB RAM、15 GiB sparse data disk、8 GiB sparse root disk；PostgreSQL/Redis 活数据和必要镜像留在 VM，Artifact/普通资源缓存继续使用外置 Root。
- PostgreSQL 17 Alpine、Redis 7.4 Alpine、一次性 Alembic migrate 与精简 API runtime 通过 BuildKit 构建和 Compose 启动；API runtime 不包含 uv，构建上下文约 0.4 MiB。
- 验证 PostgreSQL 重启后 migration version 仍为 `20260811_0001`，Redis PING、API live/ready、真实 API Project 创建与幂等重放、PostgreSQL 持久化均通过；烟测数据已按稳定 key 精确清理。
- 真实 PostgreSQL 测试暴露并修复 JSONB → strict Pydantic 反序列化问题：持久化边界改用严格 JSON mode，领域模型本身不放宽；新增回归测试。
- 本地 `.env` 暴露单元测试环境泄漏，未配置持久化测试现在显式传 `postgres_dsn=None`，不再依赖开发机环境。
- `SQLAlchemy[asyncio]` 显式声明 greenlet 支持；全新 APFS 临时 venv 验证 greenlet 3.5.5 正常。故障根因是 exFAT 上的 uv wheel/cache 产生 AppleDouble metadata，不保留虚假的版本降级。
- 外置引导脚本不再把 uv package cache 放到外置 exFAT；uv venv/cache 改放 `/private/tmp`，可随时重建。Artifact、pnpm store 和可执行时再验证的 Playwright 浏览器仍优先外置。
- 新增 `scripts/build_compose_images.sh`，将最小构建输入无 xattrs 地暂存到 APFS `/private/tmp`，规避外置 exFAT AppleDouble/BuildKit 冲突，镜像加载后立即清理受控临时上下文；它不删除 checkout 内容。
- 新增非破坏性 `scripts/check_compose_runtime.sh`，统一检查 Compose 配置、服务状态、migration、Redis、API、无 uv runtime 镜像和真实 PostgreSQL 集成合同；发现 AppleDouble 时只提示使用受控构建脚本。

### 本轮验证

- 全量测试：`68 passed`，其中 4 项使用真实 PostgreSQL；branch coverage 84%。
- Ruff lint、Ruff format、Mypy strict、uv lock 全部通过。
- BuildKit 双阶段镜像、Compose migrate、PostgreSQL restart persistence、Redis PING、API health 和 runtime import/Alembic 合同通过。

### 阶段结论与下一实现边界

- 阶段 1 的领域、最小 LangGraph、DeepSeek Adapter、PostgreSQL Revision/UoW/API 与真实 checkpoint/resume 基线已具备继续开发条件。
- `/health/ready` 当前仍只表达配置存在，连接探针保持 `not_checked`；在 Worker/生命周期接入前补成真实 startup/readiness probe。
- 下一切片按主指南进入 Candidate Snapshot / Preview / Approval 事务闭环，先让 AI L2/L3 变更可预览、批准、拒绝和原子 materialize，再进入音频 Worker。

## 2026-08-11：Candidate Preview / Approval 事务闭环

- 新增可逆 Alembic `20260811_0002`：`candidate_snapshots`、`preview_candidates` 与 `approvals`；Candidate IR/hash/版本不可变，Preview 仅更新生命周期与审批引用。
- `CreateCommandPreview` 只接收 agent EditorCommand，服务端重新应用命令并计算真实 ChangeImpact；L0/L1 被拒绝进入 Preview 路径，L2/L3 持久化 Snapshot + pending Preview，Branch head 不变化。
- `DecidePreview` 对 approve/reject 幂等：approve 再次锁定并验证 Branch/Base、Snapshot identity/hash，记录受控 `materialize_candidate` service-command，原子写 Revision、推进 head、更新 Preview、写 Approval/审计；reject 不创建 Revision。
- 等待期间 Branch head 变化时 Preview 持久转为 `superseded` 后返回 `REVISION_CONFLICT`；过期转为 `expired`，二者都不物化候选。
- 新增 5 项 use-case 单测与真实 PostgreSQL 事务测试，覆盖不提前推进、approve 重放、reject、stale、expiry、materialization command 与单一 Approval。
- 当前仍不公开 `/previews/*` HTTP 端点：阶段 2 尚未产生可试听 Artifact，提前公开批准会绕过“L2/L3 试听后人工确认”产品合同。音频 Preview 与 Graph resume 接入后再开放 API。

## 2026-08-11：计划 Graph v2 与一次 Schema Repair

- 最小计划 Graph 升级为 `motif-forge-plan.v2 / motif-forge-plan-state.v2`，显式加入 `RepairPlan` Node/Edge；确定性校验只输出最多 12 个 `field.path:error_type` 安全 issue code，不把原始异常、reasoning 或 Secret 写入 State。
- DeepSeek JSON Adapter 对“合法 JSON 但不符合 CompositionPlan Schema”执行最多一次完整对象 repair；仅在 Graph 剩余 model-call budget 至少为 2 时启用，第二次仍失败即返回稳定 `DEEPSEEK_SCHEMA_INVALID`，没有超预算或无限自修正。
- Adapter 合并 repair 前后的 prompt/completion/cache/reasoning token 与 model-call 数；Graph 使用 `max_model_calls`、`max_total_tokens` 和累计 counters 做 planning-only 硬停止，预算不足时返回 `SCHEMA_REPAIR_BUDGET_EXHAUSTED` 或 `MODEL_BUDGET_EXHAUSTED`。
- Graph-level repair 负责 provider-independent Planner 的领域 Schema 失败；DeepSeek Adapter 内部 repair 成功后只向 Graph 返回合法 Plan，两层不会对同一坏 payload 叠加多轮调用。
- State counter 不是最终成本事实源；完整 Parent Graph 仍按合同使用 PostgreSQL Usage Ledger + 稳定 operation ID，避免 checkpoint replay 重复计费。
- 阶段 1 仍未完成的 AI 协议项缩减为：thinking tool-call 轮次的 `reasoning_content` 续传合同、持久 Trace/Span/Usage Ledger 与完整 Error Router/fallback。当前 CompositionPlanner 是明确 tool-free 的 JSON 调用，遇到 `tool_calls` 会安全拒绝。

### 当前阶段验收快照

- 全量 `77 passed`，其中 5 项使用真实 PostgreSQL；branch coverage 85%。
- Ruff lint/format、Mypy strict、uv lock、Compose config 与 `git diff --check` 通过。
- 最终运行态为 `motif-forge-plan.v2 / motif-forge-plan-state.v2`、Alembic `20260811_0002`；API、PostgreSQL、Redis 与 migrate 服务通过重复 Compose 检查和 PostgreSQL restart。
- 当前主机系统盘约 49 GiB 可用；Colima 实际目录约 4–5 GiB，BuildKit cache 约 1.8 GiB（低于 2 GiB 目标），PostgreSQL volume 约 66 MiB。未安装 Docker Desktop、Kubernetes、QEMU、Rosetta、Chromium 或 HQ 音色包。

## 2026-08-11：阶段 1 v3 收口与阶段 2 音频 Spike

### Agent/协议收口

- 最小计划 Graph 升级为 `motif-forge-plan.v3 / motif-forge-plan-state.v3`，所有失败出口进入确定性 `ErrorRouter`；Schema repair、provider fallback、人工决定和终止都有显式 Edge 与上限。
- DeepSeek thinking tool-call 续轮按官方协议在单次 Adapter 局部缓冲中回传 assistant `reasoning_content`；该字段不会进入 Graph State、Trace、日志或公共结果。工具名、参数 Schema 和轮次均受 allowlist 与预算约束。
- 新增低置信度确定性 `CompositionPlan` fallback；它只能生成可审核的完整计划，不能绕过 `PlanApproval`。
- 新增 Alembic `20260811_0003` 的 PostgreSQL Trace/Span/Usage Ledger；provider operation ID 唯一去重，重复 checkpoint/model result 不重复计费。Telemetry 写失败时 Graph fail closed，不伪装成成功。
- `/health/ready` 改为有界 PostgreSQL `SELECT 1` 与 Redis `PING`，依赖未配置、超时或失败均返回 `503 not_ready`，不输出 DSN/Secret。

### 30 秒 Chromium Audio Worker

- 新增共享 TypeScript `AudioGraphSpec v1`、严格运行时校验、Tone Offline 编译器、PCM16 WAV 编码器和三个内置 Synth Preset；Spike 工程包含 Synth、内置无版权 click sample、EQ、gain/pan、固定种子 convolution reverb。
- 固定 `playwright=1.62.1` 与其安装的 Chromium revision；同一 Chromium 进程顺序渲染 30 秒 Master、pluck Stem、pad Stem 和重复 Master。二进制只经一次性 loopback sink 落到显式外置 Artifact Root，不进入 Redis、Graph State 或 base64。为避免官方 Playwright 全浏览器镜像保留本项目不用的 Firefox/WebKit，Worker 使用 pinned `node:24.18.1-bookworm-slim`，先安装 Chromium 系统依赖，再执行 `playwright install --only-shell chromium`；只保留 headless Chromium 与 Playwright 必需组件，不安装完整 GUI Chrome。精简后具名 Worker 镜像为 1.48 GB，原官方全浏览器镜像为 4.04 GB。
- 容器限制为 2 CPU、1 GiB、256 processes、无外网。最新验收运行中 Master/Stem 均为 48 kHz stereo、5,760,044 bytes；单次约 1.51–2.45 秒，聚合 RSS 峰值 863,219,712 bytes。
- 重复 Master 在 2,880,000 个 PCM16 样本中仅 49 个相差 1 LSB，最大偏差 1 LSB、比例约 0.0017014%。因此验收记录两个 checksum，并用显式 1 LSB/0.01% 容差，不把浮点 DSP 的量化边界误报成完全相同字节。
- 首版固定种子 reverb 的选择来自一次失败证据：`Tone.Reverb` 构建随机 impulse，导致重复渲染大面积不一致；替换成版本化固定 impulse 的 `Tone.Convolver` 后通过。该决策只作用于 canonical 可复现预设，不禁止以后增加明确标记为 stochastic 的创作效果。

### 保持音高的 time-stretch

- 新增 `time-stretch-recipe.v1`：受控 Workspace 通过 Artifact/Job ID 解析路径，FFmpeg 以 argv/no-shell 调用 `atempo`，支持 0.5x–2.0x，并输出 48 kHz stereo PCM16 Derived WAV；源文件不可变，临时输出校验后内容寻址原子提升。
- 质量门检查预期时长、RMS/peak、silence、最大跳变和有足够置信度时的 ±25 cents 音高偏差。真实 440 Hz 合成 WAV 的 120→96 BPM、相同 recipe 复现和越界不写入均已测试。
- 当前完成的是音频内核与 Chromium 执行 Spike，不是正式 Worker 交付：Celery Job/Outbox、Artifact metadata/配额、缓存命中、Graph wait/resume、1/3/5 分钟与 4/8/12 轨性能矩阵仍待实现。

### 当前验收快照

- Python 全量测试（含真实 PostgreSQL）：`91 passed`；其中 Usage Ledger 幂等、checkpoint restart/resume 和事务隔离均使用容器数据库。
- TypeScript 构建、类型检查和音频单元测试在 Worker 镜像构建中通过：`6 passed`；覆盖三种内置 Preset、Schema 越界、内置 sample 可复现、超时取消和一次性 sink token，最终 30 秒 Master + 两 Stem + repeat 容器 Spike 通过。
- Compose runtime contract 通过：Alembic `20260811_0003`、API、真实 readiness、PostgreSQL、Redis、Graph v3/runtime import 与 6 项 PostgreSQL 集成测试。
- Artifact/Spike WAV 与 npm 普通缓存位于外置 Root；Docker VM、必要镜像、PostgreSQL/Redis 和可重建 `/private/tmp` Python 环境留在内置 APFS。未引入 HQ 音色包、端到端音乐模型、Docker Desktop、Kubernetes、QEMU 或 Rosetta。
- Stage-end Storage Hygiene Gate 是后续每个小阶段的固定验收项，而非本次专项操作：冻结保留集合、精确盘点、清理可重建旧项、无重建 smoke、记录前后 bytes。首轮已清除 7.01 GB 未使用 BuildKit cache、619 MB 误建仓库 `.venv`、旧 Spike 运行和可重建 npm cache；本轮在精简镜像和最新 Spike 验收后又清除 2.099 GB BuildKit cache，并以 `fstrim` 让 VM 释放块。门禁后 Build Cache 为 0 B、Docker image content 为 2.316 GB、系统盘约 51 GiB 可用；仅保留 `run-5113c989-bb64-4667-9d80-13840d964979` 的 Master + 两 Stem + repeat（约 22 MB）、6 个最新具名运行/构建镜像、下阶段依赖和 PostgreSQL/Redis 数据卷。无重建 Compose smoke 与 6 项真实 PostgreSQL 集成测试通过；未删除其他项目具名镜像或业务数据。

## 2026-08-11：Media Quality 与持久化 Worker 事件纵切

- 冻结 `MediaQualityProfile v1`：局部试听 `audition-lite.v1` 为最多 15 秒 MP3 128 kbps，完整候选 `candidate-preview.v1` 为 48 kHz stereo MP3 160 kbps；编辑/分析/time-stretch 使用 PCM16，选中 Master/显式 Stem 使用 48 kHz stereo PCM24。原始导入按 bytes/checksum 不可变，低质量试听不得覆盖原件或最终导出。
- 外置优先范围扩展到 checkout、Web dependencies、音色、导入、Preview、waveform/analysis、派生音频、导出、音频 Eval fixture 及 uv/npm/pnpm/Playwright 可迁移 cache；Python venv 因 exFAT 安装兼容性保留在 APFS 临时目录，uv 下载 cache 已实测可放外置 Root。
- 新增可逆 Alembic `20260811_0004`：`runs/jobs/run_events/job_events/outbox_events/inbox_receipts/artifacts`。API/Application 创建 Run + queued Job + dispatch Outbox 同事务；Worker 完成写 Artifact metadata + Inbox receipt + Job/Run event + Graph resume Outbox 同事务。
- Artifact metadata 保存 profile、codec、采样率、声道、bit depth/bitrate、encoder/version、生命周期/可用性和 recipe hash；storage key 必须是受控相对 key。内容去重键包含 `project_id`，避免跨项目/租户复用逻辑 Artifact。
- 新增确定性 `persisted_worker_event_update` 合同：只有 Inbox 已接受的事件才能映射到 `validate_artifact | retry_job | route_error`，State 只保存 Artifact ref，不含路径或音频 bytes；它是下一步 Parent Graph Node 的复用函数，不创建第二套 Graph。
- 验证：Python `96 passed / 6 skipped`；真实 PostgreSQL 集成 `7 passed`；Ruff、Mypy strict、Alembic downgrade/upgrade、API/Redis/PostgreSQL Compose runtime 均通过。最新 API runtime 已重建并重启；Render Worker 无代码变化，重建时 Debian 镜像源连续 502，停止无意义重下并保留上一阶段已验收的具名 Worker 镜像。
- Stage-end Storage Hygiene：先确认 0004 新表无残留测试行并保留 6 个具名运行/基础镜像、PostgreSQL/Redis Volume、最新外置 Spike Artifact 和 Python venv；随后清理本轮 151.8 MB 可回收 BuildKit cache、179 MB 已由外置 cache 替代的 `/private/tmp/motif-forge-uv-cache`，以及本轮新文件的 AppleDouble sidecar。门禁后 Docker Build Cache 为 568 MB 且 `reclaimable=0 B`（均被当前最新镜像引用），Docker image content 2.76 GB，系统盘约 50 GiB 可用、外置盘约 289 GiB 可用；未删除数据库 Volume、最新镜像、其他项目镜像或业务 Artifact。

## 2026-08-11：Outbox、Celery 与 Time-stretch Worker 纵切

- 新增 Celery 5.6 transport adapter；Redis 只做至少一次投递且 result backend 关闭，Task 只接收 `job_id`。Worker 固定 `acks_late=true`、`task_reject_on_worker_lost=true`、prefetch=1、concurrency=1，并以 PostgreSQL Job/Inbox/Artifact 事务消化重复投递。
- 新增可逆 Alembic `20260811_0005`：Job 增加 deadline、max attempts、lease owner/expiry、heartbeat、progress；Outbox 增加 available-at、publish lease 和安全 error code。Dispatcher 通过 `FOR UPDATE SKIP LOCKED` 批量领取，发布失败采用有限指数退避，发布后数据库更新失败允许同一 Outbox task ID 重投。
- 新增非 root Media Worker 镜像 target；FFmpeg 只进入该镜像，不进入 API 或 Chromium Worker。容器 `/artifacts` 绑定 KINGSTON 外置 Root；输入 storage key 必须先由 PostgreSQL Artifact metadata 解析并通过相对路径/边界校验，Redis、Graph State 和客户端都不能提供任意服务器路径。
- 持久 `time_stretch` Job 已真实跑通：120→96 BPM 的 48 kHz stereo PCM16 输入经 FFmpeg `atempo` 输出保持音高 Derived WAV，Artifact/Job/Run/Inbox/Resume Outbox 同事务写回；再次投递同一 Job 返回既有 Artifact，attempt 保持 1。完成后测试 Project 的 Job/Artifact/pending media Outbox 均为 0。
- `WaitForJobEvent` 已作为可复用 Node 合同实现，并用 Memory checkpoint + `Command(resume=worker-resume.v1)` 验证断点恢复；它没有被编译成第二套生产 Graph。现有生产 Graph 仍只负责 CompositionPlan，因此下一切片必须随 Import/Arrangement 分支挂入唯一 Parent Graph，并实现读取 `graph.resume.requested` 的 Resume Dispatcher。
- 验证：Python 全量 `108 passed`（包含真实 PostgreSQL、真实 Redis/Celery、容器 Media Worker 与重复投递）；Ruff、Mypy strict 通过；TypeScript build 与音频测试 `6 passed`；Compose runtime contract 覆盖 API、migration 0005、PostgreSQL、Redis、Dispatcher、非 root Media Worker 和 FFmpeg。
- Stage-end Storage Hygiene：删除仓库 6,655 个和外置 uv cache 2,115 个 AppleDouble sidecar、31 MB 临时 Mypy cache，并将外置 uv cache 从 547 MB prune 到 275 MB；Artifact Root 保持约 24 MB。Docker 保留 7 个当前具名运行/基础镜像、PostgreSQL/Redis Volume 与已验收 Chromium 镜像；新增 Media Worker 镜像约 1.07 GB（其中 FFmpeg 运行层约 708 MB）。源码一致性重建后 Docker image content 为 5.502 GB，BuildKit 为 3.05 GB、其中 1.75 GB 标记可回收；对已枚举的旧 FFmpeg cache record 做两次精确 ID prune 均实际释放 0 B。由于该 Colima builder 可能包含其他项目记录，没有用全局 prune 强行压回 2 GiB；该次门禁将 3.05 GB 记为显式偏差，而不是误报达标。后续继续使用单目标构建，只有能证明归属或用户批准共享 builder 清理时才收回这部分空间。系统盘约 47 GiB 可用、外置盘约 290 GiB 可用。

## 2026-08-11：Docker 稳定层与模块级资源决策

- Media Worker Dockerfile 改为 `media-worker-base(FFmpeg/toolchain) → media-worker(copy venv/migrations)`；高频变化的应用内容不再位于 FFmpeg 安装层之前。重复构建已观察到 FFmpeg 步骤明确 `CACHED`，没有再次下载 121 MB Debian 包；依赖层也把 `README.md` 移到锁文件依赖安装之后，文档变化不会重建全部第三方依赖。
- `scripts/build_compose_images.sh` 保持单 target 入口；README 不再默认构建 API、Media Worker、Render Worker 全集，Render Worker 只在音频切片需要时构建。该做法降低未来增长和冷构建频率，不改变运行时音频合同。
- 曾创建带 1.5 GB GC 上限的 `docker-container` 专属 builder；实测当前 Colima 代理无法让该 BuildKit 访问 Docker Hub。失败均发生在 base metadata 前，随后删除该 builder、状态 Volume 和新增的 348 MB BuildKit 镜像。依据“具体模块具体分析”原则，不保留无法工作的常驻隔离组件；项目 Skill/指南已改为先评估隔离、稳定层、冷构建、缓存归属、外置可行性和质量影响。
- 新镜像切换后 Compose runtime contract 为 `8 passed / 1 opt-in skipped`，真实 Redis/Celery/FFmpeg E2E 为 `1 passed`；API、Dispatcher、非 root Media Worker、PostgreSQL 与 Redis 正常运行。测试生成的仓库 Python/AppleDouble cache 与外置 uv AppleDouble 已再次清零。
- 本轮冷迁移构建使共享 Colima BuildKit 暂时达到 4.948 GB，其中 3.117 GB 标记可回收；当前镜像逻辑统计 7.239 GB，但按 Docker `UNIQUE SIZE` 求和约 2.65 GB。将共享 builder 压至 1.5 GB 的操作因可能影响其他项目缓存而未执行，等待用户在明确知晓风险后批准；当前 Colima 宿主目录约 10 GB、系统盘约 44 GiB 可用、外置盘约 290 GiB 可用。这是未完成清理的迁移峰值，不作为 Lean Profile 达标数字。
- 不继续降低音频质量：5 分钟 stereo PCM16/PCM24 分别约 57.6/86.4 MB，而 MP3 160/128/96 kbps 分别约 6/4.8/3.6 MB。两个候选从 160 降到 128 kbps 只再省约 2.4 MB，降到 96 kbps 也只再省约 4.8 MB；这些 Artifact 已在外置 Root 且受 TTL/按需 Stem 管理，继续降码率不能缩小 Docker，收益小于潜在听感损失。

## 2026-08-12：Parent Graph 首分支与热缓存高门槛

### Parent Graph / 恢复纵切

- 新增唯一生产 Parent Graph `motif-forge-parent.v1 / motif-forge-parent-state.v1` 的首个确定性分支：`ValidateTimeStretchRequest → EnqueueTimeStretchJob → WaitForJobEvent → ValidatePersistedArtifactRef → terminal`。State 只保存 UUID/ref、控制状态与版本，不保存路径或音频 bytes；time-stretch 请求继续强制 `preserve_pitch=true`、0.5x–2.0x。
- 新增独立 Resume Dispatcher。Job Dispatcher 仍只领取媒体 dispatch/retry topic；Resume Dispatcher 只领取 `graph.resume.requested` 且 payload `run_type=parent.*` 的记录，避免把早期直连 Worker 测试或计划审批 interrupt 接入错误 Graph。
- Worker resume payload 增加 `run_type` 与 `resume_event_id`；`WaitForJobEvent` 同时校验 `run_id + thread_id + job_id`。成功恢复后 `last_resume_event_id` 进入同一 PostgreSQL checkpoint；Outbox 重放相同事件时直接确认，不重复推进终态 Graph。连接关闭后重建 saver/Graph 的真实 PostgreSQL 测试证明不会再次执行 Enqueue Node。
- 当前 Artifact gate 只验证 Worker 完成事务已持久化的单一 UUID ref；上传/quarantine、bytes/checksum、codec/duration/pitch/lineage 全量复核和 Arrangement 物化仍是下一纵切，不把它描述为完整 Import 闭环。

### 验证

- 新增/相关单元检查覆盖成功 resume、终态失败、非法请求、非 Parent Run 隔离和相同 resume event 重放；针对性 `12 passed`，真实 PostgreSQL checkpoint restart/resume `4 passed`。
- Python 全量 `105 passed / 9 opt-in skipped`；Compose 合同 `9 passed / 1 Redis+Artifact E2E opt-in skipped`。API、Job Dispatcher、Resume Dispatcher、非 root Media Worker、PostgreSQL 与 Redis 均正常运行；Ruff、format、Mypy strict 与 `git diff --check` 通过。

### Storage Hygiene 与显式偏差

- 缓存政策升级为热 target 白名单：开发期目标约 1.5 GiB、硬上限 2 GiB；当前 runnable image 优先，下一阶段不需要的 Chromium cache 不强保。项目功能完备、发布封版或长期停开发时，项目拥有的 BuildKit cache 默认清空，只保留发布镜像、lockfile 与可复现构建输入。
- 本轮 BuildKit 从 4.948 GB 因 API/Media 热刷新和一次已中止的 Chromium 冷构建上升到 5.278 GB，最终 API 与 Media Worker 运行镜像对齐后为 5.774 GB（3.939 GB private/reclaimable）。Media Worker 最后一次构建的 FFmpeg/依赖步骤全部命中 `CACHED`，没有重新下载；13 个已核对的旧 FFmpeg/venv/dependency cache ID 精确 prune 均释放 0 B，因为仍被 DAG 后继引用。全局 LRU 被停止，因为当前 Colima builder 是跨项目共享资源，无法证明不会让其他项目失去可重建缓存。
- 当前 7 个具名镜像逻辑统计 7.908 GB，但按 unique layer 约 2.65 GB；PostgreSQL Volume 约 68 MB，外置 Artifact Root 约 24 MB。系统盘约 41 GiB、外置盘约 290 GiB 可用。BuildKit 5.774 GB 是未达 2 GiB 合同的显式偏差；获得“允许清理整个 shared builder、其他项目可能冷构建”的明确授权后，才执行 LRU 收口，不用模糊命令绕过安全边界。
- 阶段结束先删除 157 个 AppleDouble sidecar、约 38 MB 的 pytest/Ruff/Mypy cache、24 个 `__pycache__` 目录，并对外置 uv cache 执行 native prune；最终 Media Worker 对齐与 Compose 复验又产生 72 个 sidecar 和约 1.6 MB pytest cache，交付前再次清零。这些均为不可恢复但可重建的缓存/metadata 旁车，不涉及源码、数据库、镜像或 Artifact。清理后以无重建 Compose readiness 验证运行态。

## 2026-08-12：受控 Upload、Import Worker 与 Arrangement 物化

- 新增可逆 Alembic `20260812_0006`：`upload_sessions/upload_parts`、上传 idempotency/request hash、Artifact `source_job_id | source_upload_id` XOR provenance、nullable 未解码媒体字段与 `validation_status=quarantined|validated|rejected`。Migration downgrade 在存在 Upload 数据时主动拒绝，避免静默删除 durable source-original。
- API 新增 `/api/v1/upload-sessions`、顺序 raw-byte Part PUT、`complete` 与 `/api/v1/projects/{project_id}/imports`。上传固定最大 256 MiB、默认 4 MiB Part/24 小时 TTL；创建幂等，Part 重放以每块 SHA-256 验证；只接受 WAV/MP3/FLAC magic bytes，不接受任意路径，也不在解码前伪造采样率/声道/duration。
- source-original 写入外置 Artifact Root 的 `quarantine/` 内容寻址区并保持不可变。Media Worker 在独立 FFmpeg 镜像内先复核原件 checksum，再用 FFprobe 确认唯一音频流和 30 分钟/媒体上限，生成 48 kHz stereo PCM16 `working-pcm.v1`；同一 Worker 完成事务原子更新原件 validation metadata、登记派生 Artifact、Job/Run/Inbox/Resume Outbox。
- 唯一 Parent Graph 新增 `import_audio` 分支，与 time-stretch 共用 checkpoint/wait/resume/error route。Worker 成功后确定性 `import_audio` system 命令把 Working PCM 物化为 AudioTrack/AudioClip L1 Revision；空工程 Section 向上对齐完整小节，Branch head 仍以 base Revision 乐观锁推进。BPM/key 分析、低置信度 Interrupt 与按 BPM 自动 time-stretch 尚未实现，保留在同一 ImportSubgraph 后续节点。
- Compose 实测首次暴露 bind mount 在 Linux VM 内归 root 所有，非 root Media Worker 无法创建 Job scratch；新增一次性 `storage-init`，只为受控 `tmp/jobs`、`quarantine/source-original`、`protected/working-pcm` 与 `derived/time-stretch` 命名空间授予写权限，Worker 仍以 UID/GID 10001 运行。未知 Worker 异常继续返回稳定公开码，但现在写入含 job_id/job_type 的服务端 exception log，不向客户端泄漏路径。
- 当前无外部服务全量 `114 passed / 11 opt-in skipped`；真实 PostgreSQL + FFmpeg 上传/归一化与 checkpoint 组合 `6 passed`；Compose runtime `11 passed / 1 Redis+Artifact opt-in skipped`。真实 HTTP → Upload → Parent Graph → Redis/Celery → FFmpeg → PostgreSQL → Resume Dispatcher 闭环额外验收：Job `succeeded`，Working PCM 为 48 kHz/stereo/16-bit，Branch head 推进且 IR 含 1 条 AudioTrack/AudioClip。两次 smoke Project/DB rows、4 个测试音频、Job scratch 和 3 个临时目录均按精确 ID/path 清除。
- Stage-end Storage Hygiene 后 AppleDouble、pytest/Ruff/Mypy/Python cache 清零；API、Dispatcher、Resume Dispatcher、非 root Media Worker、PostgreSQL、Redis 均运行。系统盘约 39 GiB 可用、外置盘约 290 GiB 可用；checkout 约 948 MB，外置项目数据约 302 MB。共享 BuildKit 因本轮两 target 刷新为 6.271 GB（4.434 GB reclaimable），按用户最新决定暂不压缩；未运行 builder/global prune，也未删除下一阶段明确会复用的 API/Media Worker 镜像和依赖层。

## 2026-08-12：Import 分析、置信度 HITL 与自动保持音高对齐

- 新增无大型数值依赖的 `import-analysis.v1` 基线：只读取标准化 PCM 的前 120 秒，用 onset-envelope autocorrelation 给出 BPM、用有界 pitch-class/profile 基线给出 major/minor key；结果与置信度持久化在 Artifact JSONB metadata，Graph checkpoint 只保存小体积投影。该实现优先保守升级到 HITL，不把复杂复调分析准确率伪报成专业 MIR 水平。
- 新增 `import-analysis-policy.v1`：BPM 置信度阈值 0.65、key 0.25，任一不足进入 `AnalysisConfirmationInterrupt`；key 阈值按当前轻量分析器的分数尺度设定，后续必须用真实 Eval 校准，不能跨引擎照搬。用户可以确认、覆盖 BPM/key、跳过对齐或取消。高可信且与项目 BPM 差异超过 1% 时自动进入保持音高 time-stretch，超出 0.5x–2.0x 仍转人工。
- 新增同 Run 后续 Job 事务：Ingest 成功后通过 `EnqueueFollowupMediaJob` 在原 PostgreSQL Run 内追加 time-stretch Job、更新 waiting pointer 并写 Job/Run/Outbox；重放使用相同 idempotency key，不创建第二个 Run 或隐藏 Graph。最终 AudioClip 的 `TimeStretchRef` 保存原 normalized Artifact、Derived Artifact、source/target BPM、ratio、`preserve_pitch=true` 和 engine version。
- 公共 API 新增 `/api/v1/imports/{thread_id}/confirm-analysis`；Import 投影可返回 `analysis_confirmation_required` 与安全分析摘要。DeepSeek API 仍不参与本纵切，数值、阈值、重试和 Worker 错误均由确定性规则处理。
- 验证：无服务全量 `125 passed / 11 opt-in skipped`；真实 PostgreSQL + FFmpeg integration `11 passed / 1 Redis+Artifact opt-in skipped`；Compose runtime contract 同样 `11 passed / 1 opt-in skipped`，API readiness、Dispatcher、Resume Dispatcher、非 root Media Worker 和迁移 head `20260812_0007` 正常；Ruff、format、Mypy strict 与 `git diff --check` 通过。新增 Artifact `analysis JSONB` 可逆列。
- 阶段末保留集为当前 API/Media Worker/Render Worker 具名镜像、运行中的 PostgreSQL/Redis Volume、外置 Artifact Root、lockfiles 和 `/private/tmp/motif-forge-venv` 下一切片测试环境。项目位于 exFAT 外置盘时，uv 安装会生成/读取 AppleDouble metadata 并导致 wheel 脚本错误，因此误建的 197 MB 仓库 `.venv` 已删除；仓库 AppleDouble、pytest/Ruff/Mypy/Python cache 清零，服务保持 ready。最终镜像刷新后共享 BuildKit 约 7.27 GB（约 5.42 GB private/reclaimable），按用户决定不全局 prune；该数字是跨项目 shared builder 的显式偏差，不误报为项目必需空间。

## 2026-08-12：StoragePressureGate 与 time-stretch Artifact 重建纵切

- 新增 `storage-pressure-policy.v1` 确定性规则与持久 `storage_events`：外置 Root/identity、全局/项目/temp 配额、作业预计增量、输入 Artifact 四态、保护引用和 LRU 候选统一映射为 `proceed | gc_then_retry | rehydrate_then_resume | wait_for_storage | fail`。每个 operation 最多执行一次 GC 并以同一 operation ID 重算，模型不参与容量或删除决策。
- Alembic `20260812_0008` 为 Artifact 增加完整 `RebuildRecipe`、保护原因、last-access/expiry/eviction/rehydration 字段；历史 rebuildable 数据保守迁移为 protected，禁止无完整配方的自动删除。驱逐只接受数据库 Artifact ID，锁定后再次检查当前 Revision/待审 Preview/recipe 输入，先在同一 Root 原子 rename 到受控 pending，再提交 `evicted` metadata，事务失败则恢复原路径。
- 唯一 Parent Graph 新增 `LoadArtifactMetadata → StoragePressureGate → EnqueueRehydrateJob → WaitForJobEvent → Complete` 有限分支。公共 `POST /api/v1/artifacts/{artifact_id}/rehydrate` 不接受路径或 recipe；创建 Job 与 `evicted → rehydrating` 原子提交，Worker 复用固定 FFmpeg time-stretch recipe，checksum 与 recipe hash 同时匹配后恢复原 Artifact ID，终态不可恢复错误转 `missing`。本纵切只启用 time-stretch recipe，render/analysis/transcode 不伪装成可重建。
- `/health/ready` 新增 `artifact_root` 探测；Compose 的 API、Media Worker 与 Resume Dispatcher 均明确 bind mount 同一 KINGSTON Artifact Root，禁止断盘时静默落到 Docker VM。真实 Celery E2E 已覆盖生成 → 精确驱逐 → 同 ID 重建，且重复投递/重建保持幂等。
- 验证快照：Python unit `140 passed`；真实 PostgreSQL storage round-trip `1 passed`；真实 Redis/Celery/FFmpeg 生成—驱逐—重建 `1 passed`；Compose runtime `12 passed / 1 opt-in skipped`；Ruff、Mypy strict、Alembic 0008 downgrade/upgrade 和外置挂载核验通过。DeepSeek API 不参与本纵切。
- Stage-end Storage Hygiene 已删除项目 checkout 内 199 个 AppleDouble sidecar 和 27 个 pytest/Ruff/Mypy/Python 可重建缓存目录；当前具名 API、Media Worker、Render Worker、PostgreSQL/Redis 镜像和数据卷、26 MB 外置 Artifact 均保留。共享 BuildKit 当前为 7.929 GB（6.084 GB private、全部标为 reclaimable）；按此前“暂时不压缩”决定且本轮自动审批拒绝跨项目 LRU，没有以规避方式继续清理。系统盘约 41 GiB、外置盘约 288 GiB 可用；待用户明确接受其他项目可能冷构建时再执行受控 shared-builder prune。

## 2026-08-12：独立 FeatureArtifact 与 Studio 读取纵切

- 新增可逆 Alembic `20260812_0009`：`feature_artifacts` 独立保存 source Audio ref/hash、Profile/Schema、JSON checksum、recipe/hash、四态可用性和恢复信息；Media Job 的 feature output 与 audio quality output 严格 XOR。
- Ingest Worker 用轻量确定性算法生成最多 4096 bucket 的 `waveform-peaks.v1` 与 `imported-audio-analysis.v1`，文件内容寻址写入外置 `rebuildable/features`；Audio、两个 Feature、Job/Run/Inbox/Outbox 在同一完成事务登记。
- API 新增按源 Audio Artifact 列 Feature metadata、按 Feature ID 校验 checksum 并读取 payload；evicted/rehydrating 仍可发现但不返回 payload。Parent Graph 复用现有有限恢复拓扑，analysis recipe 可恢复同 Artifact ID/hash，不创建 Feature 专用 Graph。
- StoragePressureGate 用量、候选、精确驱逐与依赖读取覆盖 Audio/Feature 两表；Import Graph 读取 analysis 前要求独立 Feature 处于 available，AudioArtifact analysis JSONB 仅作为当前兼容投影。
- 验证：单元 `145 passed`；真实 PostgreSQL/Redis/Celery/FFmpeg 集成 `14 passed`；Compose runtime、迁移 head `20260812_0009`、Ruff 与 Mypy strict 通过。DeepSeek API 不参与本纵切。
- 迁移可逆性检查发现 naming convention 将 Job XOR 约束规范化为 `ck_jobs_jobs_exactly_one_output_profile`；downgrade 已改用实际名称并完成 `0009 → 0008 → 0009` 容器验证，ORM metadata 同步声明该约束。两条早期失败中断、名称为 `Feature recovery integration` 的测试 Project/Job/Feature 及其精确 feature 文件已事务清理，未触及用户作品。
- Stage-end Storage Hygiene 删除了已证明会被 exFAT AppleDouble 污染的仓库 `.venv`（约 1.0 GiB）、本轮临时验证环境（约 197 MiB）、约 38 MiB pytest/Ruff/Mypy/Python cache 和 3,896 个 `._*` 旁车；checkout 从约 2.1 GiB 降至 950 MiB，Artifact Root 保持约 28 MiB，清理后旁车/测试缓存计数均为 0，Compose readiness 仍为 ready。两个外置 uv cache 执行 native prune 仅释放约 384 KiB；旧 `/Volumes/KINGSTON/idea/.cache/uv` 可能跨项目共享，未整目录删除。Docker 无 dangling image；保留 7 个具名镜像、PostgreSQL/Redis Volume 和当前 Artifact。共享 BuildKit 为 8.76 GB、其中 6.91 GB reclaimable，但归属仍无法证明，未执行全局 prune；系统盘约 40 GiB、外置盘约 287 GiB 可用。

## 2026-08-12：BuildKit 归属收口与 Import Review 首个 Web 纵切

- 对唯一运行的 Colima `default` 实例做只读归属核验：Buildx history 从最早到最新均为 Motif Forge/本仓库构建上下文，7 个具名镜像仅为 API、Media Worker、Render Worker 及当前 PostgreSQL/Redis/Python/Node 基础镜像，容器和 Volume 也只属于本 Compose 工程；未发现其他项目镜像、容器、Volume 或构建历史。在归属可证明后使用受控脚本按 45 分钟冷阈值、1.5 GB target/2 GB hard limit 清理，BuildKit 从约 8.76 GB 降至 3.054 GB，其中 1.85 GB 为当前镜像仍引用的共享层、1.204 GB 为 private/reclaimable cache。7 个具名镜像、两个数据卷和所有运行服务均保留；清理后未重建镜像，Compose 六个服务保持运行，`/health/ready` 的 PostgreSQL、Redis、Artifact Root 均为 connected。
- Docker 开发规则进一步收紧为 host-first：Web/Vite、TypeScript 音频包、纯领域/应用逻辑和单元测试默认在宿主机运行；源码变化本身不触发镜像。只有 Dockerfile/系统依赖、影响容器的 lockfile、迁移/运行时接线或明确跨服务/阶段门，才刷新受影响的单个 target，并记录原因。当前 Web 纵切没有执行任何 Docker build。
- 新增 `apps/web` React + TypeScript + Vite 应用，使用 TanStack Query 读取既有 `GET /audio-artifacts/{id}/features` 与 `GET /feature-artifacts/{id}`，严格解析 Success Envelope、UUID、Feature Profile 和 `available | evicted | missing | rehydrating`。波形由 Canvas 绘制最多 4096 个持久 peaks，BPM/key 卡片显示置信度并按当前确定性阈值标记需确认；`evicted` 仅通过显式 `POST /artifacts/{id}/rehydrate` 进入持久恢复，不把播放动作伪装成恢复，也不接收任意路径。
- UI 使用已冻结的深色石墨、青色/紫色/洋红视觉 token，覆盖空、加载、API 错误、Feature 部分失败、未知 Profile、四态 Artifact、窄屏与 reduced-motion；Canvas 提供文本摘要和 ARIA label。真实 Chromium 检查通过桌面空态、无效 UUID 拦截和 390×844 窄屏布局，无横向溢出。当前数据库没有可复用的 Feature fixture，因此真实 payload 浏览器 E2E 未伪造；available analysis/profile 路径由严格 DTO 测试覆盖，后续受控 Upload UI 纵切将补完整浏览器 E2E。
- 前端验证为 `10 passed`，TypeScript strict + Vite production build 通过，产物约 246 KB JS / 10.7 KB CSS（gzip 约 76.9 KB / 3.2 KB）；既有音频包 `6 passed`，Python 单元 `145 passed`，Ruff 与 Mypy strict 通过。npm 依赖与 cache 均位于外置盘，未修复或扩张内置用户 npm cache。阶段末删除 Vite build、Playwright 会话、AppleDouble 以及 pytest/Ruff/Mypy/Python/Vite cache，复查计数均为 0；BuildKit 仍为 3.054 GB（1.204 GB private/reclaimable），没有因本 Web 纵切增加，Compose readiness 保持 ready。

## 2026-08-12：受控上传到保持音高预览的完整 Web 闭环

- Import Review 现在直接创建 Project，浏览器对最大 256 MiB 的 WAV/MP3/FLAC 计算 SHA-256，使用稳定 Idempotency Key 创建 Upload Session、按服务端分块上传并启动唯一 Parent Graph。权利类型和确认复选框是必填事实，取消只中止未完成浏览器请求，孤立 Session 由既有 24 小时 TTL 回收。
- API 新增只读 `GET /api/v1/imports/{thread_id}`：严格接受 `import-{32 hex}`，从 PostgreSQL checkpointer 投影 phase、source/normalized/final Artifact、analysis 与 Revision，不调用 `ainvoke`。页面把 thread 写入 URL，只在 `waiting_worker` 有界轮询，刷新后恢复而不重复 Project、Job 或 Revision。
- API 新增 `GET /api/v1/audio-artifacts/{artifact_id}/content`：只允许 `available + validated` Audio Artifact，服务端解析受控 storage key 并拒绝逃逸、任一路径组件的符号链接、大小不符和不可播放格式；FileResponse 提供 Range 试听。页面在稳定边界才挂载原始/最终 audio，避免 Worker 未验证阶段的虚假播放与控制台 422。
- HITL 页展示检测 BPM/key、置信度和项目 BPM；confirm、override、skip_alignment、cancel 均恢复同一 thread。修正了“分析完全未知 BPM 时 skip_alignment 仍被错误要求 BPM”的 Graph 边界：跳过对齐可直接物化 normalized Artifact，且不会编造 BPM。
- 真实 Chromium 用既有 30 秒 WAV 完成页面上传，得到 `import-7de65fb14faf48d9093bf225e6dfacea`、normalized `9822c82e-6cc3-419c-8e18-928ae841d31a`、保持音高对齐 Artifact `fdf6e45d-6269-4b7e-a2b8-b467824a083a` 与 Revision `49d0624c-28ce-4e97-b7bd-c423730d2fb3`；刷新恢复、原始/对齐控件、波形、80→120 BPM 与 A 大调证据均在真实页面呈现。
- 验证：Web `15 passed`、TypeScript strict/Vite build；Python `151 passed`、Ruff、Mypy strict；Compose runtime `13 passed / 1 opt-in skipped`。仅因新增 API 运行时接线重建 `api` target，并刷新共享该镜像的 API/Dispatcher/Resume Dispatcher；Media Worker、Render Worker、PostgreSQL、Redis 均未重建。
- Stage-end Storage Hygiene：保留当前 7 个具名镜像、PostgreSQL/Redis Volume、外置作品 Artifact、源码 lockfile、API/Media/Resume 运行服务和外置 Python/npm 依赖；删除本阶段约 42 MiB 的 Vite dist、Playwright 会话、pytest/Ruff/Mypy/Python cache 与全部 AppleDouble 旁车。已证明归属后按 45 分钟冷阈值执行项目 BuildKit 门，BuildKit 从 3.701 GB（1.535 GB private）降至 2.497 GB（330.5 MB private），低于 2 GB private hard limit；当前镜像引用的约 2.167 GB shared layers 保留。清理后 Range 试听返回 206/1024 bytes，390×844 为 `scrollWidth=innerWidth=390`，Compose runtime 已在无再次重建下通过。

## 2026-08-12：实施状态审计与创作主链路路线收口

- 对 `PROJECT_GUIDE` 的首版合同和当前代码逐项核对，确认 Import/Analysis/Alignment/Web Preview 已形成可靠纵切，但阶段 2 要求的完整成曲、阶段 3 的 Studio、四个 Style Pack、完整 Generate/Edit/Export Graph 和 96 条 Eval 尚未完成。CompositionPlan Graph 已有代码和 checkpoint 测试，但生产 API 只编译 Import/Recovery Parent Graph，记录为必须在 Generate 纵切消除的临时双 Graph 技术债。
- 新增 `IMPLEMENTATION_STATUS.md`，以“可运行/内部完成/部分完成/未开始”区分目标合同和真实能力，记录验证基线、技术债、版本治理风险和当前唯一开发断点。新增 `NEXT_DEVELOPMENT_ROADMAP.md`，采用 `G0 短收口门 → S1 确定性完整成曲 → S2 统一 Generate Graph/DeepSeek → S3 Web Brief/Plan → S4 四风格知识/规则 → S5 候选/修复 → S6 DAW/AI 编辑 → S7 导出/Eval/发布` 的依赖顺序。
- 路线采用“先短收口、后纵切内优化”，不进行独立全仓重构。G0 只处理文档事实、基线复验、单一 Graph 方向和已验收代码的 Git checkpoint；Router/Repository 拆分、OpenAPI DTO 生成、SSE、Trace 接线和大文件职责提取必须随使用它们的用户价值纵切完成。
- 为避免原始产品方向随多轮开发丢失，路线新增 `MF-P01`–`MF-P21` 需求追踪矩阵，把网页工作台、完整生成、导入、DeepSeek、局部 AI、HITL、四包、音色、DAW、time-stretch、统一 Graph、策略子图、完整导出、Compose、Lean Storage、Eval、未来 Adapter、既定视觉语言和安全/版权逐项绑定到首次实现/最终验收阶段。每个具体计划和验收报告必须声明覆盖的需求 ID。
- 本次文档审计验证：Python `152 passed / 13 opt-in skipped`；真实 PostgreSQL `13 passed / 1 Redis+Artifact opt-in skipped`；Audio `6 passed`；Web `15 passed`；TypeScript/Vite、Ruff、Mypy strict 与 Compose readiness 通过。未修改业务代码、数据库、Artifact、Docker 镜像或运行服务。

## 2026-08-12：G0 开发基线门关闭

- G0 重新盘点 48 个修改项和 65 个未跟踪项；它们属于同一已验收的 Domain/Agent/Persistence、Media/Storage/Import、Web/Audio 和 Docs/Ops/Lockfile 纵切。由于 API、迁移、Worker、Graph 和 Web 存在真实跨文件依赖，没有人为拆成不能独立通过测试的历史提交。
- Secret/产物审查确认 `.env`、node_modules、dist、`.venv`、Artifact Root、pytest/Ruff/Mypy/Python cache 和 AppleDouble sidecar 均由 ignore 规则排除；新增内容没有真实 DeepSeek key，DSN 仅为本地开发/测试默认值。历史外置绝对路径只存在于明确标记的本机验证记录和 G0 执行命令，产品代码/配置不硬编码个人路径。
- 关闭门禁前复验 Python `152 passed / 13 opt-in skipped`、真实 PostgreSQL `13 passed / 1 Redis+Artifact opt-in skipped`、Audio `6 passed`、Web `15 passed`、Ruff、Mypy strict、TypeScript/Vite build、Compose runtime contract 和 readiness。运行态复验未重建任何 Docker 镜像。
- 157 个源码、迁移、测试、文档、脚本与锁文件形成里程碑 `6bf21f5`（`feat: complete durable audio import web slice`）并推送到 `origin/main`；推送后工作区 clean。活动门切换为 S1 确定性完整成曲，S2 DeepSeek/Generate Graph 在 S1 完整导出、Eval 和恢复门通过前保持关闭。

## 2026-08-12：S1 确定性完整成曲与正式导出链

- 冻结 S1 `PatternSpec v1` 与固定作品合同：24 bars、80 BPM、4/4、C major、四轨 Synth Ambient、72 秒、seed `20260812`。确定性 Composer 把 section/role/chord/rhythm/register/density 编译为 PPQ tick NoteEvent/Clip，并通过现有 CandidateSnapshot、PreviewCandidate 和人工批准事务物化不可变 Revision；L3 创作没有审批旁路。
- 新增唯一 `ArrangementIR → AudioGraphSpec` 投影、稳定 canonical hash 和 48 kHz stereo PCM24 编码。浏览器音频对象不进入 Project truth；Master/Stem 继续使用同一 Tone.js AudioGraphCompiler 和三个版本化内置预设。最终收口要求 Worker 从 PostgreSQL Revision 重新编译 Graph，严格比对 Revision/Arrangement/Graph hash 与完整 Graph，拒绝调用方提供的另一份自洽 Graph。
- 30 秒 Spike 泛化为常驻受控 Chromium Render Service（concurrency=1）。正式 `render_canonical`、`transcode_export`、`export_bundle` Job 复用 PostgreSQL Run/Job/Outbox/Inbox、Redis/Celery、lease/deadline/attempt、显式 cancellation 和幂等 completion 合同；WAV/IR bytes 不进入 Redis、Graph State 或数据库 JSON。Alembic `20260812_0010` 持久化独立 ExportBundleArtifact，`0011` 把 Candidate 原始生成命令持久化为批准 Revision 的审计事实，head `20260812_0012` 升级 `audio-artifact.v2`，结构化保存 Revision/Arrangement/render scope 并回填既有最终音频。
- 完整导出含 PCM24 Master、四条 PCM24 Stem、256 kbps MP3、标准 MIDI type 1、canonical Project JSON、credits/license/provenance/trace/export manifests。Master/Stem/MP3 使用内容寻址 Protected 路径，存在不同 bytes 时拒绝覆盖；MP3 完成后用 FFprobe 与 volumedetect 验证 48 kHz、双声道、预期时长、实际 bitrate 与非静音。Export Bundle 是只含 manifest/MIDI/Project 与六个 Audio Artifact 引用的逻辑包，不再复制音频 bytes；全部输入 Artifact/profile/checksum/revision lineage 做 fail-closed 校验。
- 最终使用定向重建后的 API/Media/Render 镜像和显式 `/temp` 挂载，经 `PostgreSQL Outbox → Redis → Celery Media Worker → Chromium Render Worker` 复验完成，Project `af988445-9123-40f6-81bf-7a6bcc037099`、Revision `f49b820e-0e56-4038-9108-a72cdc3affa5`、Run `c713a239-d169-4c02-836f-ec20ad657c3e`、Bundle `86d18388-1159-4c76-83ed-ffc317948007`。Master 为 20,736,044 bytes/72 秒；逻辑 Bundle 为 13 项、59,396 bytes，checksum 与 lineage 全部通过。运行中取消会轮询 PostgreSQL 权威状态，中断 HTTP/FFmpeg/Bundle 并清理新建孤儿；promote/completion 竞态及分歧重复 completion 由 PostgreSQL 权威 Artifact fail-closed；StoragePressureGate 统计同一显式 temp root，并阻止带有效租约或被活动 Job payload 引用的 Artifact 被驱逐。Render/MP3 即使跨 bind mount，也会先流式复制到最终目录唯一 partial、校验并 fsync，再在 Artifact 文件系统内原子 rename；MP3 的时长/格式/码率检查之外，`max_volume <= -80 dBFS` 作为近静音拒绝门。
- 队列验收真实发现容器继承宿主 `HTTP_PROXY` 后，把 `http://render-worker:8090` 错误代理到外部并返回 502。内部 Chromium Render Client 现对 Compose peer 显式 `trust_env=false`，不依赖每台机器的 `NO_PROXY`；断连/timeout/429/5xx 仍为有限 retryable，checksum/profile/lineage 错误保持 terminal。Render Service 进一步把 timeout/not-ready/internal failure 分别映射为 504/503/500，避免页面执行失败被错误降成不可重试 400。持久失败记录和随后修复重跑保留为失败分类证据。
- S1 Eval 为 20 条固定成功/失败案例；最终基线为非 integration Python `205 passed / 21 integration-only skipped`、真实 PostgreSQL `21 passed / 1 Redis+Artifact opt-in skipped`（S1 专项 `6 passed`）；Audio/Render `13 passed`、Web `15 passed`、Mypy strict 73 files、Ruff、TypeScript 与 Vite build 通过。下一门切换为 S2：把 Plan v3 并入唯一 Parent Graph并接通 DeepSeek/Fallback，不开发第三个生产 Graph。
- Stage-end Storage Hygiene 先后删除了误建的 checkout `.venv`、内部临时环境/工具缓存、测试/类型/Vite/Render 编译输出和 exFAT AppleDouble 旁车；最终定向冷建一度把 BuildKit 推到 `7.443 GB`（`3.455 GB private + 3.988 GB shared`）。受控共享 Builder 清理保留 7 个当前镜像、PostgreSQL/Redis Volume、最新 Chromium/FFmpeg 热路径和全部业务 Artifact，把 BuildKit 收敛到 `4.697 GB`，其中 private 仅 `708.5 MB`，低于 1.5 GiB 目标；`3.988 GB` shared layer 由当前镜像引用，不用 image/system/volume prune 破坏运行集。最新 S1 Bundle、Master/Stem/MP3 和历史导入均保留，清理后 API/Render/PostgreSQL/Redis readiness 与 `/temp`/`/artifacts` mount 继续通过，无重建。

## 2026-08-13：S2 Tasks 1–5 内部生成事实链

- Task 1 建立 PostgreSQL AI Run、不可变 CompositionPlan、事件、审批、请求预留和真实 provider usage 事实；审批绑定服务器权威 pending Plan/interrupt，重试创建 child Run，所有迁移与回滚都有真实 PostgreSQL 证据。
- Task 2 将 Plan v3 的规划逻辑提取为无审批、无持久化副作用的 Planning Subgraph；旧 v3 wrapper 的节点、边、checkpoint 和 interrupt/resume 语义继续作为回归合同。
- Task 3 将每次 DeepSeek HTTP POST（含 transport retry/repair）绑定到持久 Run 预算；保存 nullable provider total/cache/reasoning usage 与 known/partial/unknown 状态，unknown 阻止后续付费请求。Prompt 使用统一 canonical JSON envelope，endpoint 锁定官方 `https://api.deepseek.com`。全部验收使用 MockTransport，没有真实付费调用。
- Task 4 增加 Synth Ambient Plan 兼容策略和确定性 Plan→ArrangementIR 编译；覆盖 12 音级、7 modes、entry/exit、128 bars/300 秒边界、稳定规则/UUID/seed provenance。Plan hash 采用版本化 `rounded-v1`/`lossless-v2`，旧 Plan 可读，新 Plan 不丢执行精度，含 v2 数据时降级 fail closed。S1 固定函数、hash 和 bytes 保持冻结。
- Task 5 将严格 Plan 持久化、权威 pending/approval、Candidate/Preview、Revision、Branch CAS、receipt 与 Run event 收进一个 PostgreSQL 复合事务；Run→Branch 锁顺序处理取消竞态，不同 caller key 共享同一逻辑物化结果，失败和 Branch 冲突均无部分写入。公开 Preview 与复合事务复用同一 transaction core，没有直接 Revision 旁路。
- Tasks 1–5 每项均经过独立审查和有界修复；Task 5 最终为 `Spec ✅ / Quality Approved / C0 I0 M0`。最新证据为 full unit+eval `389 passed`、Task 1+5+Project PostgreSQL `36 passed / 1 optional Celery E2E skipped`、Task 5 real PostgreSQL `12 passed`、Ruff/Mypy/diff clean，业务 migration head `20260813_0016`。
- 按用户要求在 Task 5 后暂停。Task 6（复用 S1 Render/Transcode/Bundle）、Parent Graph、Dispatcher/API/SSE、恢复/取消、Eval/Compose smoke 和一次预算受控的真实 DeepSeek 付费验收均未开始或未完成；S2 仍是活动门，不能标记完成。开发全程未重建 Docker 镜像，也未读取、打印或提交 API key。
- 暂停门仅清理本仓库可重建开发缓存：约 39 MiB 的 pytest/Ruff/Mypy cache、319 个源码/测试 `__pycache__` 目录和 304 个非 `.git`/非 `.venv` AppleDouble sidecar；保留 Docker 镜像/BuildKit、PostgreSQL/Redis 数据、外置 Artifact、项目依赖与测试 venv，避免影响 Task 6 的热启动。

## 2026-08-13：S2 剩余路线切换为作品集工程模式

- 对 Task 1–5 的执行成本做复盘：核心边界获得了高置信度，但每个 Task 反复扩展到历史迁移、极端并发和全部失败排列，造成多轮实现/审查回路，推迟了真正可演示的 Generate Parent Graph。结论不是删除可靠性，而是把“主路径正确性”和“准生产证明广度”分开排期。
- ADR-016 冻结不可降低门槛：单一 Parent Graph、受控 DeepSeek/确定性 Fallback、真实 PlanApproval、不可变 Revision、PostgreSQL checkpoint/event/usage、一次重启不重复费用或副作用、S1 完整导出、代表性 Eval/Trace、无付费 Compose smoke 与一次预算受控的真实 DeepSeek 验收。
- Task 6–12 改为作品集工程模式：每项执行 focused TDD、一个真实边界、一次独立审查和最多一次修复复审；Task 10 做组合回归，Task 12 做全阶段门。Critical 和影响当前主路径、数据/Artifact、Secrets/权限、模型费用、HITL、幂等或恢复的 Important 继续阻塞。
- S2 Eval 从 24 条调整为至少 16 条代表性 Generate 案例，并保留两条主要 Baseline；最终四风格、AI 编辑和发布报告仍扩展到 `PROJECT_GUIDE.md` 规定的 96 条，不降低终局作品集指标。
- 全 checkpoint 崩溃/取消/重复投递排列、所有历史 populated downgrade、长时间负载/P95、多租户、灾备与完整 OTel 平台进入 S7 后置硬化登记。真实数据损坏/越权/Secret 泄露、重复付费/副作用、不可恢复或相同缺陷第二次出现时，必须提前升级为阻塞项。
- 本次只修改决策、状态、路线、S2 Tasks 6–12、Agent 指令和 README；没有修改业务代码、迁移、数据库、Artifact、Docker 或 DeepSeek 配置，`PROJECT_GUIDE.md` 最终产品合同保持不变。

## 2026-08-13：S2 Task 6 共享完整成曲导出编排

- 新增 checkpoint-safe `CompleteExportCursor`、`EnqueueNextCompleteExportJob`、`CollectCompleteExportArtifact` 与 `build_export_bundle_payload`，严格按 Master → pad/melody/bass/rhythm Stem → MP3 → logical Bundle 七步执行。Master 创建唯一 `MediaRun`，后续六步全部用既有 `EnqueueFollowupMediaJob` 复用同一 Run；应用层只构建 payload 和写 Job/Outbox，不执行 Worker。
- `build_canonical_render_payload` 只从数据库重新加载的不可变 Revision 编译 AudioGraph。每次 enqueue/collect 都重新校验 Revision content hash，以及已完成 Artifact 的 project/revision/Arrangement、quality、scope、track、availability 与 source Job；cursor 模型拒绝跳步、乱序、重复 identity、计数或 pending/Run 不一致的 checkpoint。重复 completion 直接返回相同 cursor，不产生第二个 Job 或 Artifact ref。
- Export Bundle payload 只含六个 `BundleAudioInput` Artifact/hash/profile/filename 引用，不含 storage path 或 audio bytes。Bundle completion 同样绑定 pending Job、Revision、Arrangement、seed 与精确输入 Artifact 集。S1 deterministic smoke 已移除自己的 Render/Transcode/Bundle payload 构造，改为循环调用共享服务；固定 S1 用户流程与 Worker/Artifact/取消合同未变。
- TDD 先以缺失接口得到预期 RED，后补 source-job、cursor 恢复与前序 Artifact 重验证 RED/GREEN。最终 focused unit `12 passed`；真实 Compose PostgreSQL 边界 `1 passed`，证明权威 Revision payload、单 Run/Job/Outbox 与重复 enqueue；Ruff、目标 Mypy、S1 script compile、`git diff --check` 和 `PROJECT_GUIDE.md` SHA-256 `21345f64304338777a9dd2603d34ad54448b6c4b82902bc743204ba1026c9f58` 通过。
- 唯一独立审查先发现 Bundle source Job 未绑定、cursor 可伪造跳步两个当前路径 Important；唯一修复轮补齐后，范围复审为 `Spec PASS / Quality APPROVED`，无剩余 blocker。本 Task 未重跑完整 S1 故障矩阵、未重建 Docker、未调用 DeepSeek，也未读取或输出 API Key。下一断点为 Task 7 Parent Graph v2 generate 挂载。
- 范围化存储清理确认 PostgreSQL 中 Task 6 测试 Project 残留为 `0`，并删除了可重建的独立审查 scratch；本 Task 未生成业务 Artifact 或 Docker 数据。

## 2026-08-14：S2 Tasks 7–11 与 Task 12 预付费门

- Task 7 把 Generate 挂入唯一 `motif-forge-parent.v2`：共享 Planning Subgraph 后依次执行 PlanApproval、原子 Revision 物化和共享七步导出；旧 Plan v3 只保留 checkpoint 回归。真实 PostgreSQL checkpoint 证明 restart/resume，且 storage wait/failure、state schema 不匹配会稳定终止而不误 enqueue。
- Task 8 统一 `graph-action.v1` start/resume/cancel contract，Producer 在原事务写权威 outbox，Dispatcher 先读 AI Run 再恢复 Parent Graph并按 delivery 去重。审批原文只在同事务 resume outbox 中短暂承载，审批表只保存 assertion hash；已存在的 legacy pending payload 保持 strict-fail，不伪造不可恢复字段。
- Task 9 新增 Project AI Run create、Run GET/resume/cancel/retry 与持久 SSE。`Last-Event-ID` 可跨 API recreation 有序回放，terminal cursor 在空 poll 后立即关闭；GET 只从 PostgreSQL 权威 facts 投影 Revision/Bundle/Plan/error。Resume 先查持久幂等命中再验证当前 pending state，同 key/同 body 可回放，任一审批字段变化均冲突。
- Task 10 用真实 Project/AI Run/Plan/Candidate/Revision/receipt/Job/Artifact/Bundle UoW 跑完整链：成功 SQL 计数精确为 `1/1/1/1/7/6/1`，重复 start 与 Master completion 不变化；等待审批取消无 Revision/Job；错误 lineage 进入稳定终态并保留安全已完成引用、排除恶意 Artifact、停止后续 enqueue。
- Task 11 建立 16 条 Generate Eval（6 valid、3 unsupported、3 malformed、2 approval、2 recovery），如实分开 S1 fixed sample 与 Parent baseline；只把可由实际 IR 证明的 forbidden behavior 纳入 measured 分母，其余标 runtime-only。无 Key Compose smoke 通过公共 HTTP/SSE、真实队列和 PostgreSQL lineage 得到一条 `7 Jobs / 6 audio / 1 Bundle / 0 model calls / 0 tokens` 的完整 Synth Ambient 导出。
- 阶段预付费门通过：集中 Python `436 passed / 56 integration-only skipped`，Compose runtime 真实 PostgreSQL `57 passed / 1 Redis+Artifact opt-in skipped`，Audio `13 passed`、Web `15 passed`、Ruff、Mypy 82 source、Audio/Web build、OpenAPI deterministic generation 和 diff checks 均通过。Tasks 7–11 checkpoints 最终为 `5438dc0`、`3d2f3c7`、`47fb5b3`、`b2f1f0b`、`79b113f`。
- 第一次尝试 runtime smoke 时容器意外继承本机 Key，产生一个有效 Provider response（Run `a8366f60-9a36-4d90-b9ac-12a4cf8e433a`，1 request，4,119 tokens），随后因当时 fallback/compiler 接线缺陷未完成物化；该调用不计作 Task 12 acceptance，Key 未读取、打印或写入。之后 Resume Dispatcher 已恢复显式 no-Key override，并在每次运行态门后验证容器 Key 为空。
- Task 12 live guard 使用固定且不可由环境覆盖的 Project/Run/resume 数据库幂等身份；跨进程重跑只取回同一 durable Run，失败或成功终态不会新建第二个付费 Run。脚本在任何 HTTP 前要求显式 opt-in、Key、reviewed model、审批 actor/assertion 和 live container attestation；严格解析 Plan、重算 lossless-v2 content hash、独立核验持久审批，并把三次请求/12,000 tokens、known usage、无 fallback、七 Jobs/六 audio/单 Media Run、lineage 与六个物理 checksum 收进小于 4 KiB 的 secret-safe summary。
- Guard tests `11 passed`、无 Key fail-closed 实跑和独立预付费复审 `SAFE / Spec PASS / Quality APPROVED` 后形成 checkpoint `1e57bba`。由于上面的有效 Provider response，计划禁止模型自行推断第二次付费权限；该预付费断点当时等待用户明确授权一次新的预算受控验收，尚未取得 live success，S2 因而保持活动门。后续结果记录在下一节。

## 2026-08-14：S2 Task 12 真实 DeepSeek 验收与阶段关闭

- 用户明确授权后，第一次固定验收 Run 在单请求 2,400 output cap 下消耗 4,135 tokens，输出被 reasoning 占满而没有形成有效结构化 Plan。系统正确记录 `MODEL_OUTPUT_UNUSABLE` 并进入需审批 fallback；没有 Revision、Job 或 Artifact，因此不计 live acceptance 成功。
- 通过 TDD 把 live v2 收紧为固定数据库幂等身份、`max_model_requests=1`、`max_total_tokens=12000`、`max_attempts=1` 和 4,096 output tokens。Host guard 与 live container 在任何 HTTP 前独立验证 opt-in、模型、单次尝试、输出上限和 Key；第二次 transport/schema repair 必须先过持久账本，不能静默重复付费。
- 固定 v2 Run `3de2a947-6118-45d8-ae7a-f829ef7bc0a0` 用唯一一次 `deepseek-v4-flash` 请求得到严格 Plan，持久 usage 为 4,911 known tokens，`cost_status=unknown`，无 fallback。审批由 `local-user` 记录并绑定权威 Plan/interrupt。
- 真实 Plan 暴露 section function 可长于 ArrangementIR 80 字符边界；确定性编译器现只在 Plan→IR 投影时截断该描述，不修改持久 Plan。随后 approval outbox 首次投递已把 checkpoint 推到 `approved` 才失败，重投原先会误判为 no-op；Dispatcher 现对 `approved`/`revision_materialized` checkpoint 以 `ainvoke(None)` 继续同一 thread。两项均先有 RED，再有单元 GREEN。
- Key 撤下后，只重投同一权威 approval outbox；同一 v2 Run 未新增模型调用并恢复到 `succeeded`。最终权威事实为 1 Plan、1 Revision、7 succeeded Jobs、6 Audio Artifacts、1 Export Bundle，全部 Job 属于单一 `complete_song_export.v1` Media Run；六个实体文件 checksum 与数据库内容和 Revision/Arrangement/source Job lineage 一致。
- 最终回归为 Python `440 passed / 56 integration-only skipped`，修复聚焦 `152 passed / 7 skipped`，真实 PostgreSQL `8 passed`，Audio `13 passed`，Web `15 passed`；Ruff、Mypy 82 source、Audio/Web build 和 OpenAPI 确定性重生成通过。S2 关闭，活动门切换到 S3 网页 Brief/Plan 与只读 Studio。

## 2026-08-20：S3 浏览器 Brief/Plan 与只读 Studio 闭环

- 新增 Project Home 与版本化 Project/Run/Studio Read Model：浏览器从当前 Branch head 提交严格 Brief，使用同一 Parent Graph v2 查看 Fallback/DeepSeek Plan、人工审批或创建 immutable child Replan，并通过权威 GET + 持久 SSE 恢复进度。PlanAdjustment 不覆盖父 Plan，批准仍绑定当前 Plan hash、version、actor 与 16 字符以上断言。
- 新增只读 Arrangement Studio：从 PostgreSQL Revision 读取权威 ArrangementIR 与 delivery Asset，Canvas 只画时间线主体、DOM Track Header 保持可访问；Transport 只经 validated Audio Artifact content route 播放 MP3。available/evicted/rehydrating/missing、部分成功、外置 Root 断开、空轨、加载与错误状态均不伪造内容；编辑、Piano Roll、Mixer 与 Export UI 保留给后续阶段。
- Import Review 可接收既有 Project，并用显式顺序队列导入多个 Stem。每个文件独立保存 rights、progress/error 和 retry/skip 状态；每次成功后重读 Project head，下一文件绑定新 base Revision；Revision conflict 停止队列并刷新权威 Project，不创建第二个 Project。
- S3 确定性 Chromium gate 只用浏览器可见控件和公开 HTTP 执行 Project → Brief → parent Plan → child Replan → Approval → complete export → Studio/play → Project reopen → same-Project two-Stem import。容器 no-key attestation 在任何浏览器写操作前 fail closed；S3 没有改变 provider prompt/schema/planner，因此没有触发新付费调用。
- 最终浏览器事实为父/子 Plan 各 1 且旧 Plan 可读，批准子 Run `succeeded`，1 Revision、7 succeeded Jobs、6 Audio、1 Bundle、单一 Media Run；delivery MP3 为 2,426,924 bytes 并实际开始播放。390px 的 Run/Studio/reopen 无页面级 overflow，两个 Stem 使 Branch head 连续推进两次，provider requests/tokens 为 `0/0`。
- 主机门为 Python unit + S3 contract `415 passed`、Audio `13 passed`、Web `41 passed`、Ruff、Mypy strict 85 source、Vite build、OpenAPI 双生成一致和 diff clean。Compose runtime 使用独立已迁移测试库，真实 PostgreSQL integration `59 passed / 1 Redis+Artifact opt-in skipped`；主作品库中的 lossless-v2 Plan 按设计阻止危险 migration downgrade，未为测试删除或改写任何作品事实。
- 运行态只重建了本阶段后端/API Read Model 所需的 API target；Media Worker 镜像未重建，Render Worker 只因同机旧容器占用 8090 而精确切换到当前 worktree。固定 Playwright Chromium 安装到用户工具缓存供后续 Web 阶段复用；没有清理共享 BuildKit、数据库卷、业务 Artifact 或当前具名镜像。
