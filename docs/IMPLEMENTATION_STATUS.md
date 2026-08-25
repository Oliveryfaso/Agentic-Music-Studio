# Motif Forge 当前实施状态

> 状态日期：2026-08-25
> 性质：当前代码事实与验收证据，不替代产品合同
> 更新规则：每个被验收的小纵切结束后更新；不要把目标设计写成已实现能力

## 1. 阅读顺序

开发模型开始任务时按以下顺序读取：

1. `DECISION_LOG.md`：不可静默推翻的决定。
2. `PROJECT_GUIDE.md`：最终产品范围和总体架构。
3. 本文件：当前代码到底完成到哪里。
4. `NEXT_DEVELOPMENT_ROADMAP.md`：下一阶段的依赖顺序和验收门。
5. 与当前纵切有关的专项合同和项目 Skill。

若本文件与测试、迁移或运行时证据冲突，以代码和最新可复现证据为准，并在继续开发前修正文档。历史过程只写入 `TECH_EVOLUTION.md`。

## 2. 当前产品形态

当前可由用户实际操作的主路径是：

```text
Project Home → Brief → Parent Graph Planning → Plan Review/Adjustment
→ 人工审批 → 两个候选 Preview → 证据 Critic/至多一次 Repair → 显式 A/B 选择
→ 仅选中候选物化为不可变 Revision → 七步完整导出
→ 持久 SSE 进度/刷新恢复 → Arrangement Timeline → MP3 播放
→ 轻量 Timeline/Piano Roll/Mixer Draft → EditorCommand → 不可变 Revision/Undo/Redo
→ AI 有界选区 EditSubgraph → L0/L1 自动 Revision 或 L2/L3 Preview/HITL

或：既有 Project → 顺序导入多个 WAV/MP3/FLAC Stem
→ 每个文件独立权利确认/分析 HITL → 每次成功后刷新 Branch head
```

S3 已把 S2 的 API 级闭环变成用户可操作的作品流，S4/S5 加入四个 Style Pack、Theory 证据、双候选、Critic/Repair 和 A/B 人工选择，S6 加入轻量手工编辑与有界 AI 选区编辑，S7 再补齐正式 Export、Run Inspector、About/Eval 证据面和 96 条内部 Eval。当前已经达到个人作品集首版；负载、多租户和发布运维属于按需后置硬化，不再是默认活动阶段。

## 3. 能力矩阵

状态定义：

- `可运行`：已接入用户/API/Worker 运行路径，并有可复现验收证据。
- `内部完成`：代码、Schema 或测试已存在，但尚未形成用户可操作的生产路径。
- `部分完成`：只完成合同、Spike 或能力子集。
- `未开始`：仍仅存在于目标文档。

| 能力 | 状态 | 当前证据 | 主要缺口 |
|---|---|---|---|
| ArrangementIR、EditorCommand、Revision、Branch | 可运行 | 严格 Schema、事务写入、乐观锁、Studio draft/save 和不可变 Undo/Redo | 仍是轻量命令集，不冒充专业 DAW |
| CandidateSnapshot、PreviewCandidate、L2/L3 审批事务 | 可运行 | Generate A/B 与 Edit Preview Artifact、Critic/Repair lineage、原子 Revision 和 PostgreSQL 回放 | 广泛并发/故障矩阵留到 S7 |
| DeepSeek Provider | 可运行（API） | 生产 Dispatcher、四风格结构化 Plan、持久请求/token 预算、真实 known usage、严格 JSON envelope、官方 endpoint、MockTransport/重启测试与一次受控 live acceptance | 模型调用继续 opt-in；S4 no-key 路径使用同合同 Fallback |
| CompositionPlan Graph | 可运行 | Parent Graph v2、四风格 Fallback/Strategy、PlanApproval/Replan、双候选、Critic/Repair/A-B interrupt、EditSubgraph、PostgreSQL checkpoint | Legacy v3 仅保留回归 |
| Parent Graph Import/Generate/Edit/Recovery | 可运行 | 浏览器 Import/generate/edit、time-stretch、HITL、resume/cancel、持久 SSE 与刷新恢复 | 极端 checkpoint 矩阵留到 S7 |
| PostgreSQL/Redis/Celery/Outbox | 可运行 | Generate start/resume/cancel Dispatcher、权威 outbox、Compose readiness、幂等事件和恢复测试 | S7 才扩充负载与极端故障矩阵 |
| 受控音频上传与导入 | 可运行 | 单文件 Import 与同一 Project 顺序多 Stem；每项独立权利/错误并刷新 head | 自动 stem separation 明确不做 |
| BPM/key 分析 | 可运行的轻量基线 | FeatureArtifact、置信度与 HITL | 精度阈值尚无规模化 Eval 校准 |
| 保持音高 time-stretch | 可运行的受限基线 | FFmpeg atempo、Artifact lineage、恢复和质量测试 | 尚不是专业弹性音频；复杂 tempo map 不在首版 |
| Artifact 生命周期与 StoragePressureGate | 可运行 | 四态、配额、驱逐/重建、外置 Root | 暂不扩建通用缓存平台，按新 Artifact 类型增量接入 |
| Tone.js AudioGraphCompiler | 可运行 | ArrangementIR 编译/渲染、12 个语义 Preset alias、Web 只读 Timeline/Track projection、真实 MP3 Transport | Lite 音色仍投影到 3 个合成核心与 click sample；HQ 音色不属于 S4 |
| PatternSpec 与确定性 Composer | 可运行 | 四风格 Plan 策略、稳定双 seed Candidate、局部 Repair Snapshot、版本化 Plan hash、Parent Graph、共享 Export cursor 与有界 Edit Patch | 更丰富生成/编辑质量随 S7 Eval 校准 |
| 完整成曲与导出 | 可运行 | 四风格 Web Brief→审批→Revision→7 Jobs→Studio；Master/MP3/四 Stem/MIDI/Project/逻辑 Bundle | 1–5 分钟与最多 12 轨仍留待最终产品验收 |
| 四个 Style Pack 与 Theory Engine | 可运行 | 四个严格 `StylePack v1`、reviewed source/license snapshot、symbolic exemplar、Preset Palette、稳定 Theory rule/evidence、Web 解释与四风格 no-key 完整导出 | 当前为 Project-authored Lite 知识/音色；更丰富检索与 HQ Pack 非 S4 门槛 |
| Web Import Review | 可运行 | 上传、分析确认、试听、恢复、同 Project 多 Stem 与窄屏回归 | 更复杂的多轨编辑不属于 Import Review |
| Web Studio（轻量编辑） | 可运行 | Timeline/Piano Roll/Mixer/Library 面板、Draft/save/Undo/Redo、AI Edit/Preview、MP3 Transport、390px review-only | 更丰富专业 DAW 工具不属于个人作品集首版 |
| AI 选区编辑 | 可运行 | 有界上下文、EditPatchProposal/真实影响升级、锁定/非目标保持、L0/L1 自动提交、L2 Preview/HITL、重启恢复 | 付费 Edit planner 未验收；no-key fallback 只覆盖显式 gain/本地音色 |
| Export / Run Inspector | 可运行 | 权威七步 Export 投影、安全下载、最多 200 条脱敏 Timeline、决策/预算/Job/Artifact/恢复事实；重复读取不写库 | 大规模历史 Trace 与外部对象存储不属于首版 |
| Eval/可观测性 | 可运行（作品集） | S1–S7 共 96 条内部案例、80 条公开 measured 分母、持久 Event/Trace/Usage、About/Eval 页面、一条历史 Generate paid 样本 | 主观音质、长时负载和完整 OTel 看板明确未测 |
| CI/CD 与负载测试 | 后置可选 | 精确本地 S7 gate、确定性报告、PostgreSQL 与浏览器代表性验收 | CI workflow、soak、正式容量 P95 在公开托管/多人使用前再做 |

## 4. 当前验证基线

S7 阶段门的最新证据：

- Python unit `494 passed`；全阶段 Eval `36 passed`；S7 contract/report focused `6 passed`；Web `67 passed`。
- 真实 PostgreSQL Export、Inspector、Dispatcher 三个代表性边界 `3 passed`；Export 为 7 steps/13 files，Inspector 对已有成功 Run 投影 7 Jobs/6 Artifacts。
- Ruff、Mypy strict `107 source files`、Vite production build、OpenAPI generation、确定性 Eval 报告与 `git diff --check` 通过。
- Eval inventory 正好 96 条内部案例；公开 measured 分母 80，另列 13 个 expected reject 与 3 个 not measured；报告生成用量为 `0 request / 0 token`。
- Chromium 真实读取 `/about`、`/evaluation`、一个 Run Inspector 和一个 ready Export；桌面与 390px 无横向溢出。新的完整 no-key Run 因测试环境混用了旧 S6 dispatcher 而停在 `materializing`，未伪报为 S7 端到端成功，并在诊断后通过公开 API 正常取消；S2/S5/S6 已有完整 no-key 队列证据仍有效。

S6 阶段门的最新证据：

- Python unit `485 passed`、S6 Eval/contract `8 passed`、真实 PostgreSQL Edit/Dispatcher/SSE `5 passed`；Web `58 passed`。
- Ruff、Mypy strict `101 source files`、Vite production build、OpenAPI generation 与 `git diff --check` 通过。
- 12 条 S6 Eval 覆盖 L0/L1/L2 路由、锁定/非目标/冲突、重复 resume 与 no-key fallback；未量测的主观音质不伪报通过。
- no-Key 公共 API/真实队列 smoke 完成手工 Revision/Undo、L0 自动 Revision、L2 真实 Preview Artifact/审批 Revision，provider requests/tokens 为 `0/0`。
- 真实 PostgreSQL 重启边界复现并修复同一嵌套 EditSubgraph 的连续 worker/HITL interrupt；同一 outbox 重投后 Run 从 `waiting_edit_approval` 到 `succeeded`，无新增模型调用。
- Chromium 从当前 Branch HEAD 完成 Clip 选择和 AI 编辑，刷新后保留 Revision；桌面与 390px 无横向溢出，移动端保持 review-only。

S5 阶段门的最新证据：

- 集中 Python unit/eval/contract `517 passed`；真实 PostgreSQL Candidate/Preview/Parent Graph/SSE `8 passed`；Audio/Render `13 passed`、Web `46 passed`。
- Ruff、Mypy strict `94 source files`、Audio/Web build、OpenAPI generation 与 `git diff --check` 通过。
- 12 条 S5 Eval 覆盖四种风格各两例，以及 repair improved、non-improving、restart replay、reject/cancel；Repair 严格限制为至多一个子 Snapshot。
- no-Key 公共 HTTP/Graph/真实队列 smoke 精确得到 `2 candidate families / 3 snapshots / 1 repair child / 2 selection previews / 1 selected Revision / 7 Jobs / 6 Audio / 1 Bundle / 0 request / 0 token`，并核对协议要求的 Artifact checksum 与单一 Revision/Media Run/source Job lineage。
- 真实浏览器从 Brief、PlanApproval、A/B 逐一试听、选择 B 到只读 Studio 走通同一事实计数；页面在 390px 无横向溢出，候选播放保持单一 audio 元素。
- 运行态验收只修复三个真实当前路径问题：Candidate Preview Media Run 未进入 Parent dispatcher、Worker resume 未按 AI Run 重建完整 S5 Graph、60 秒 fallback 的小节取整超过策略时长容差；均有 RED/GREEN 与 PostgreSQL/浏览器复验。没有调用付费模型，也没有扩充 S7 负载/极端并发矩阵。

S4 阶段门的最新证据：

- 集中 Python unit/eval/contract `482 passed`；真实 PostgreSQL物化回放 `1 passed`（阶段实现时同文件完整门 `12 passed`）；Audio/Render `13 passed`、Web `41 passed`，Ruff、Mypy strict `89 source files`、Vite build、OpenAPI generation 与 `git diff --check` 通过。
- 八条代表性生成 Eval 覆盖每风格两例；另有未知风格和未审核知识拒绝，模型文本不能直接决定音符合法性或许可。
- 独立 Compose no-key 运行态中，Synth Ambient、Minimal Electronic、Classical Chamber、Jazz 均经公开 HTTP/PlanApproval/Parent Graph 得到 `1 Revision / 7 succeeded Jobs / 6 Audio / 1 Bundle / 0 request / 0 token`；容器内六个实体 checksum 与数据库 lineage 一致。
- 阶段只修复真实主路径暴露的两项跨服务问题：Render Worker 使用与 Media Worker 相同的非 root UID 写共享 temp；Jazz swing 保持同一 chord attack 成组且每个 Clip 事件单调。未扩展 S7 故障、负载或多租户矩阵，也未调用付费模型。

S3 最终门的最新证据：

- Python unit + S3 contract：`415 passed`；Audio `13 passed`；Web `41 passed`；Ruff、Mypy strict `85 source files`、Vite build、OpenAPI 双生成一致与 `git diff --check` 均通过。
- 专用空测试库上的 Compose runtime：真实 PostgreSQL integration `59 passed / 1 Redis+Artifact opt-in skipped`；API、Dispatcher、Resume Dispatcher、Media/Render Worker、PostgreSQL、Redis 与 migration head 均通过。
- no-key Chromium 主旅程：父 Plan 与子 Replan 各 1 个且旧 Plan 可读；批准子 Run 得到 `1 Revision / 7 succeeded Jobs / 6 audio / 1 Bundle`，delivery MP3 为 `2,426,924 bytes` 并实际开始播放。
- 同一浏览器旅程在 390px 的 Run/Studio/Project reopen 无页面级 overflow；两个 Stem 进入同一 Project 后 Branch head 连续推进两次；provider requests/tokens 均为 `0/0`。
- S3 没有修改 provider prompt、structured output schema 或 planner 构造，因此未触发新的付费调用；S2 的一次预算受控 live acceptance 仍是当前 provider 证据。

S2 Task 12 最终门后的最新证据：

- 集中 Python gate：`440 passed / 56 integration-only skipped`；最终修复聚焦 suite `152 passed / 7 integration-only skipped`，真实 PostgreSQL恢复/Dispatcher/Parent Graph `8 passed`。
- 当前 Compose runtime 已迁移到 `20260813_0016`；最终无付费运行时 gate 为真实 PostgreSQL integration `57 passed / 1 Redis+Artifact opt-in skipped`，API/Dispatcher/Resume/Media/Render/PostgreSQL/Redis 合同通过。
- Task 10 权威 SQL 主路径精确得到 `1 Plan / 1 Candidate / 1 Revision / 1 receipt / 7 Jobs / 6 audio / 1 Bundle`；重复 start/Master completion 不增加事实，取消和错误 lineage 不产生越权副作用。
- Task 11 Eval 为 16 条（6 valid、3 unsupported、3 malformed、2 approval、2 recovery），包含 S1 fixed sample 与 Parent baseline；确定性 Compose smoke 得到 `7 Jobs / 6 audio / 1 Bundle / 0 model calls / 0 tokens`。
- Audio `13 passed`、Web `15 passed`，Audio/Web build 与 OpenAPI 确定性生成通过；Ruff 通过，Mypy strict `82 source files` 通过，`git diff --check` 通过。
- Task 12 v1 在单请求 2,400 output cap 下只得到 reasoning，记录 4,135 tokens 后安全进入 fallback，未物化 Revision/Job，不计验收成功。修复后固定 v2 Run `3de2a947-6118-45d8-ae7a-f829ef7bc0a0` 以唯一一次 DeepSeek V4 Flash 请求、4,911 known tokens、无 fallback 完成；最终为 1 Plan/1 Revision/7 succeeded Jobs/6 audio/1 Bundle，六个实体文件 checksum 与权威 lineage 一致，`cost_status=unknown` 未伪造费用。Key 随后撤下。

上一份完整跨栈审计（2026-08-12）仍提供 Audio/Web/Compose 基线：

- Python（非 integration）：`205 passed / 21 integration-only skipped`。
- 真实 PostgreSQL 集成：`21 passed / 1 Redis+Artifact opt-in skipped`；其中 S1 专项 `6 passed`，包含执行前/运行中取消、promote/completion 竞态、分歧重复 completion 清理与容量门合同。
- TypeScript Audio Engine/Render Worker：`13 passed`。
- Web：`15 passed`。
- TypeScript strict 与 Vite production build：通过。
- Ruff：通过。
- Mypy strict：`73 source files` 通过。
- Compose：API、Dispatcher、Resume Dispatcher、Media Worker、Render Worker、PostgreSQL、Redis 运行；API 与 Render readiness 均为 ready。
- 当时的运行镜像迁移 head 为 `20260812_0012`；S2 代码/测试数据库已推进到 `20260813_0016`，运行镜像将在后续明确的 S2 Compose 门刷新。

跳过项必须继续保持显式 opt-in，不能用 SQLite 或隐式本机凭证伪造 PostgreSQL/Redis 集成结果。

## 5. 已确认的设计漂移与技术债

### 5.1 单一生产 Parent Graph 已成立

API/Dispatcher 只把 `motif-forge-parent.v2` 作为生产拓扑，`generate` 复用共享 Planning Subgraph；`motif-forge-plan.v3` 仅保留旧 checkpoint 回归 wrapper，不是第三个生产 Graph。后续 S3/S5/S6 继续扩展同一 Parent Graph，禁止复制生成编排。

### 5.2 音频可靠性领先于创作主链路

Import、Artifact、恢复和容量治理已达到较高完成度，S5 已证明四风格 Plan 上的 `two Candidates → Critic/Repair → A/B → Revision → Render → Bundle → Studio`。继续暂停通用存储/恢复平台扩建；下一产品门是 S6 手工编辑与 AI 选区编辑。

### 5.3 前后端 DTO 仍由手工维护

Project、Run 与 Studio 的公开 DTO 已进入 Pydantic/OpenAPI → TypeScript 生成边界；`apps/web/src/shared/api.ts` 仍保留 Import/Artifact 的窄手写运行时解析。后续只在触达具体 API 时增量迁移，不单独发动前端 API 全量重写。

### 5.4 大文件按触达拆分

`api/app.py`、Persistence、Provider 与 Graph 已出现多个 500–900 行文件。不安排独立“大重构阶段”；下一纵切触达某个文件并新增第二项职责时，先保留测试再提取该纵切所需的 Router、Repository 或 Subgraph。禁止顺手改写未经过的模块。

### 5.5 Eval 建设过晚

S1 已形成 20 条可重复的确定性创作/渲染 Eval。S2 剩余工作不再要求每个工程 Task 都单独扩充 Eval；Task 11 集中建立至少 16 条 Generate 代表性案例，之后随四个 Style Pack 和 AI 编辑扩展到首版要求的 96 条。功能 Task 仍须为新创作行为或新失败路由提供至少一个可回归样例，但可以先放在窄测试中，到阶段 Eval 门再统一入库。

### 5.6 当前开发采用作品集工程模式

S2 Task 1–5 的多轮审查证明了核心数据边界，但也产生了明显的重复验证成本。从 Task 6 起按 ADR-016 执行：保留单一 Parent Graph、DeepSeek/Fallback、HITL、原子 Revision、完整导出、持久恢复、代表性 Eval 和真实付费验收；把极端并发矩阵、所有历史 populated downgrade、全量负载/P95、多租户和无上限复审移到 S7/后置硬化。

这不是把系统降成 Demo。当前 Task 仍需 TDD、窄单元测试、一个真实 PostgreSQL/跨服务边界、结构化错误与费用事实；每 2–3 个 Task 做组合回归，S2 结束做完整 Compose 与 live gate。只有不影响当前用户主路径、数据/Secrets、模型费用、HITL、幂等与恢复的非核心问题才可登记后置。

## 6. 版本治理状态

`G0` 已完成：原先跨多个纵切的 48 个修改项和 65 个未跟踪项经逐项盘点后，以一个保持跨服务一致性的里程碑提交 `6bf21f5`（`feat: complete durable audio import web slice`）推送到 `origin/main`。没有提交 `.env`、API key、用户音频、Artifact bytes、dist、node_modules、Python/工具 cache 或 AppleDouble sidecar。

Checkpoint 前复验：Python `152 passed / 13 opt-in skipped`；真实 PostgreSQL `13 passed / 1 Redis+Artifact opt-in skipped`；Audio `6 passed`；Web `15 passed`；Ruff、Mypy strict、Vite build、Compose runtime contract 和 readiness 均通过。Checkpoint 推送后工作区为 clean。

后续每个可独立验收纵切都必须形成 Git checkpoint，不再跨多个阶段积累未提交业务代码。

## 7. S1–S6 验收事实与当前开发断点：S7

S1 已完成：固定作品为 24 bars、80 BPM、4/4、C major、四轨、72 秒；固定 seed 生成完整 ArrangementIR。L3 生成先创建 Candidate/Preview，再由调用者提供 16 字符以上审批断言，事务持久化 actor、审批 payload hash 和原始五条生成命令后物化 Revision。正式 Job 链输出 PCM24 Master（20,736,044 bytes）、四条 PCM24 Stem、经 FFprobe 验证时长/格式/码率/非静音的 256 kbps MP3、MIDI、Project JSON 与 credits/license/provenance/trace/export manifests。

最终新容器/新 `/temp` 挂载真实队列复验为 Project `af988445-9123-40f6-81bf-7a6bcc037099`、Revision `f49b820e-0e56-4038-9108-a72cdc3affa5`、Run `c713a239-d169-4c02-836f-ec20ad657c3e`、Bundle Artifact `86d18388-1159-4c76-83ed-ffc317948007`；逻辑 Bundle 只保存 13 个校验项与音频 Artifact 引用，自身占 `59,396` bytes，不复制约 100 MB Master/Stem/MP3。Worker 会从数据库 Revision 重新编译 AudioGraph并拒绝不匹配 payload；`audio-artifact.v2` 结构化保存 Revision/Arrangement/render scope，转码和 Bundle 均拒绝跨 Revision 输入。Render/Transcode/Bundle 均先过会计入显式 temp root、真实目录与有效 Job lease 的 StoragePressureGate；跨挂载提升先复制到最终目录的唯一 partial、复核 bytes/hash，再在 Artifact 文件系统内原子 rename。运行中显式取消会中断协程/FFmpeg、清理新建但未登记的输出并阻止迟到/分歧 completion；Chromium 客户端断连会关闭页面并清理一次性 sink/partial；MP3 还拒绝 `max_volume <= -80 dBFS` 的数字近静音。

当前下一条业务纵切是：

> **S7：把已有完整导出和 Agent/编辑闭环产品化为可公开演示的作品集，并补齐 96+ Eval、Run Inspector、必要可观测性与风险驱动硬化。**

S2 仍不得绕过 PlanApproval，也不得创建第三个生产 Graph。S1 的固定策略继续作为无模型降级和回归基线，不改变首版最终要求的 1–5 分钟、最多 12 轨、最多 2 个候选和四个 Style Pack 同时交付。

S2 实施计划 Task 1–5 已独立复审通过：

1. PostgreSQL AI Run、Plan、审批、Event、真实 usage 与请求预算；
2. 可复用且无审批/持久化副作用的 Planning Subgraph；
3. DeepSeek V4 Flash 安全 Provider 合同与持久预算（仅 MockTransport，未付费调用）；
4. Synth Ambient Plan 策略、确定性编译器和 v1/v2 Plan hash 兼容；
5. 原子 `approved Plan → Candidate/Preview → Revision`，包含 receipt、取消/并发/回放和 legacy fail-closed。

Task 6 已把 S1 的完整导出链抽为共享应用服务：严格七步 cursor 依次 enqueue Master、pad/melody/bass/rhythm Stem、MP3 与逻辑 Bundle；首个 Job 创建唯一 MediaRun，后续 Job 复用同一 Run。每次 enqueue/collect 都重新加载权威 Revision/Artifact，校验 Arrangement hash、render scope、track、quality、availability 与 source Job；cursor 只接受一致的有序前缀，重复 completion 不推进第二次。S1 smoke 已删除第二套 payload 构造并复用该服务。

Task 6 验收为 focused unit `12 passed`、真实 PostgreSQL `1 passed`、Ruff、目标 Mypy、S1 script compile 与 `git diff --check` 通过；独立审查经唯一修复复审后为 `Spec PASS / Quality APPROVED`。本 Task 没有修改 Worker/Artifact/取消合同，没有重跑 S1 故障矩阵、Docker 或 DeepSeek API。

Tasks 7–11 已依次完成 Parent Graph v2 Generate 挂载、权威 Dispatcher、REST/SSE、真实 PostgreSQL 恢复/取消/lineage 组合验证、16 条代表性 Eval 与无付费 Compose smoke，且各自形成 Git checkpoint并通过有界独立复审。

Task 12 已完成：预付费保护使用固定 Project/Run/resume 数据库幂等身份，v2 账本上限为一次 provider 请求和 12,000 tokens；严格核验 Plan v2、审批与 Artifact lineage。真实 v2 Run 在审批后曾暴露两个确定性问题：Plan section function 超过 IR 80 字符边界，以及 approval checkpoint 已推进后 outbox 重投未继续执行。二者均经 RED/GREEN 修复，同一 Run 在 Key 撤下后恢复且没有新增模型调用，最终成功导出。

S3 已完成 Project Home、Brief validation、Plan Review/Approval、immutable child Replan、持久 Run 进度、只读 Arrangement Studio、真实 MP3 Transport、Artifact 四态、390px 审阅以及同一 Project 顺序多 Stem。确定性 browser smoke 从公开 UI 完成整条路径，并用只读 PostgreSQL 事实核验 7 Jobs/6 Audio/1 Bundle；没有第三个 Graph、直接 Revision 写入或付费模型调用。

S4 已完成四个 reviewed Style Pack、稳定 Theory error/warning/advice 证据、四个确定性策略和 Web 风格/来源/许可说明。四风格均通过公开 HTTP → Parent Graph → PlanApproval → Revision → 七步队列导出；每条路径为 7 succeeded Jobs、6 Audio、1 Bundle，provider requests/tokens 为 0/0，物理 checksum 与单一 Revision/Media Run lineage 一致。Compose 验收还真实发现并修复了 Render Worker 与 Media Worker 共享临时文件的 UID 不一致，以及 Jazz chord swing 造成的非单调事件调度。

S5 已完成两个稳定 Candidate family 的 fan-out/fan-in、真实候选 Preview Job、结构化 Critic、至多一次局部 Repair、两个最终 Preview 与显式 CandidateSelection interrupt。选择前不写 Revision；选择后只物化一个 Revision 并复用七步导出。重启/重投、reject/cancel、非改善终止和 no-Key 费用事实均有测试；CLI 与浏览器运行态都得到 2 families、3 snapshots、2 previews、1 Revision、7 Jobs、6 Audio、1 Bundle、0 request/0 token。

S6 已完成轻量 Studio Draft、不可变 Undo/Redo、严格 EditRun/EditPatchProposal、同一 Parent Graph v2 的 EditSubgraph，以及 L0/L1 自动提交和 L2/L3 Preview/HITL。no-key Compose/Chromium 与真实 PostgreSQL 连续 interrupt 重启恢复均已通过，未执行新的付费模型调用。

**当前断点：S6 已关闭，S7 为唯一活动门。** 保留单一 Parent Graph、PlanApproval/CandidateSelection/EditPreview、不可变 Revision、持久费用/恢复、四风格策略和完整导出合同；下一步先写正式 S7 计划，再做 Export/Inspector/Eval/作品集演示，不回头扩建无消费者的通用平台。

具体前后顺序、阶段门和优化规则见 `NEXT_DEVELOPMENT_ROADMAP.md`。
