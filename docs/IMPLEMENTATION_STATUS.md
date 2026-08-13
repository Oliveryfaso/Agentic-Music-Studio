# Motif Forge 当前实施状态

> 状态日期：2026-08-13
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
浏览器创建 Project
→ 受控上传 WAV/MP3/FLAC
→ PostgreSQL Job + Outbox
→ Redis/Celery Media Worker
→ FFmpeg 标准化
→ waveform/BPM/key 分析
→ 低置信度 HITL
→ pitch-preserving BPM 对齐
→ 生成不可变 Revision
→ 网页试听原始/对齐音频并查看分析
```

这是一条完整的 Import/Analysis/Alignment 纵切，不是完整的 AI 编曲产品。当前系统还不能从用户 Brief 在网页中生成并导出一首完整作品。

此外，内部 S1 验收路径已经可以在不使用 LLM/API key 的情况下完成：

```text
固定 Brief/seed → PatternSpec → 四轨 ArrangementIR → L3 Preview/HITL
→ PostgreSQL Outbox → Redis/Celery → Chromium Master/Stem Render
→ FFmpeg MP3 → MIDI/Project/manifests → Export Bundle
```

它证明了完整作品的事实链和 Worker 链，但尚无公共 Generate API 或网页入口，因此不能描述为用户可操作的 AI 编曲产品。

S2 已完成前半段内部事实链：持久 AI Run/Plan/审批/预算、无副作用 Planning Subgraph、受控 DeepSeek Provider、Synth Ambient Plan 策略与编译器，以及 `approved Plan → Candidate/Preview → immutable Revision` 原子物化。该能力仍未挂入唯一 Parent Graph，也未复用 S1 Render/Export Job 链，因此同样不是用户可调用的完整生成产品。

## 3. 能力矩阵

状态定义：

- `可运行`：已接入用户/API/Worker 运行路径，并有可复现验收证据。
- `内部完成`：代码、Schema 或测试已存在，但尚未形成用户可操作的生产路径。
- `部分完成`：只完成合同、Spike 或能力子集。
- `未开始`：仍仅存在于目标文档。

| 能力 | 状态 | 当前证据 | 主要缺口 |
|---|---|---|---|
| ArrangementIR、EditorCommand、Revision、Branch | 可运行 | 严格 Schema、事务写入、乐观锁和测试 | Studio 尚未消费完整编辑命令集 |
| CandidateSnapshot、PreviewCandidate、L2/L3 审批事务 | 内部完成 | Plan 驱动的 Candidate/Preview/Revision、原子 receipt、取消/并发/回放真实 PostgreSQL 测试 | 尚未进入 Parent Graph、媒体 Job 和公共 API |
| DeepSeek Provider | 内部完成 | 持久请求/token 预算、真实 usage、JSON envelope、官方 endpoint、MockTransport + PostgreSQL 重启测试 | 尚未执行一次真实付费验收；尚未由生产 Dispatcher 构造 |
| CompositionPlan Graph | 内部完成 | 无副作用 Planning Subgraph、Legacy v3 wrapper、Fallback/Repair、PostgreSQL checkpoint 测试 | 尚未成为 Parent Graph 的 `generate` 分支 |
| Parent Graph Import/Recovery | 可运行 | Import、time-stretch、rehydrate、HITL、resume | 尚无 generate/edit/export 路由 |
| PostgreSQL/Redis/Celery/Outbox | 可运行 | Compose readiness、幂等事件和恢复测试 | Generate 尚未并入 Parent Graph |
| 受控音频上传与导入 | 可运行 | 浏览器真实 30 秒 WAV E2E | 多 Stem 加入同一 Project 的产品流程未完成 |
| BPM/key 分析 | 可运行的轻量基线 | FeatureArtifact、置信度与 HITL | 精度阈值尚无规模化 Eval 校准 |
| 保持音高 time-stretch | 可运行的受限基线 | FFmpeg atempo、Artifact lineage、恢复和质量测试 | 尚不是专业弹性音频；复杂 tempo map 不在首版 |
| Artifact 生命周期与 StoragePressureGate | 可运行 | 四态、配额、驱逐/重建、外置 Root | 暂不扩建通用缓存平台，按新 Artifact 类型增量接入 |
| Tone.js AudioGraphCompiler | 内部完成 | ArrangementIR 投影、72 秒 PCM24 Master/Stem、10 项测试 | 仅 3 个 Synth Preset；尚无 Studio/runtime 投影 |
| PatternSpec 与确定性 Composer | 内部完成 | 固定 S1 基线 + Synth Ambient Plan 兼容策略/确定性编译、版本化 Plan hash、共享完整 Export cursor | 仅一个 Style Pack；尚未接 Parent Graph |
| 完整成曲与导出 | 内部完成 | 72 秒作品、Master/MP3/四 Stem/MIDI/Project/13 项逻辑 Bundle | 尚无公共 API/Web；1–5 分钟和 12 轨留待产品验收 |
| 四个 Style Pack 与 Theory Engine | 未开始 | 只有设计 | 缺知识卡、规则、示例、检索和许可资产 |
| Web Import Review | 可运行 | 上传、分析确认、试听、恢复、窄屏 E2E | 尚未进入 Project Home、Brief/Plan 或 Timeline |
| Web Studio/DAW | 未开始 | 只有视觉与交互合同 | 缺 Project Home、Brief/Plan、Timeline、Piano Roll、Mixer、Export |
| AI 选区编辑 | 未开始 | 有命令与 ChangeImpact 基础 | 缺 EditPatchProposal 生成、Preview、局部性 Eval |
| Eval/可观测性 | 部分完成 | Trace/Span/Usage 表和 1 条 smoke fixture | 缺真实数据集、OTel、看板、Baseline/消融和失败报告 |
| CI/CD 与负载测试 | 未开始 | 本地脚本 | 无 CI workflow、P50/P95 和完整一键演示验收 |

## 4. 当前验证基线

S2 Task 5 最终复审后的最新 Python/PostgreSQL证据：

- Python unit + eval：`389 passed`。
- Task 1 + Task 5 + PostgreSQL Project 合同：`36 passed / 1 Redis+Artifact opt-in skipped`。
- Task 5 原子物化专项：真实 PostgreSQL `12 passed`；独立复审为 `Spec ✅ / Quality Approved / Critical 0 / Important 0 / Minor 0`。
- Ruff：通过；Mypy strict：`80 source files` 通过；`git diff --check` 通过。
- 当前业务迁移 head：`20260813_0016`。本轮没有重建 Docker 镜像，不能把旧运行镜像描述为已接通 S2。
- DeepSeek 相关测试全部使用 MockTransport；真实付费 API 验收尚未执行。

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

### 5.1 生产 Graph 暂时分成两条

`motif-forge-plan.v3` 保留为旧 checkpoint regression wrapper；共享 Planning Subgraph 已提取，但 API lifespan 仍只编译 `motif-forge-parent.v1`。下一步必须把共享子图作为 Parent Graph 的 `generate` 分支接入；禁止再创建第三个生产 Graph。

### 5.2 音频可靠性领先于创作主链路

Import、Artifact、恢复和容量治理已达到较高完成度；S1 的 `PatternSpec → ArrangementIR → Render` 已成立，但还没有由真实 CompositionPlan 驱动。除 S2 所需 Run/Revision/Render 接线外，继续暂停扩建通用存储/恢复能力，直到 Generate Parent Graph 通过。

### 5.3 前后端 DTO 仍由手工维护

`apps/web/src/shared/api.ts` 当前手写解析 API DTO。下一次新增公开业务 API 时，同一纵切必须建立 Pydantic/OpenAPI 到 TypeScript 的生成边界；在此之前不单独发动前端 API 全量重写。

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

## 7. S1 验收事实与当前开发断点：S2 Task 7

S1 已完成：固定作品为 24 bars、80 BPM、4/4、C major、四轨、72 秒；固定 seed 生成完整 ArrangementIR。L3 生成先创建 Candidate/Preview，再由调用者提供 16 字符以上审批断言，事务持久化 actor、审批 payload hash 和原始五条生成命令后物化 Revision。正式 Job 链输出 PCM24 Master（20,736,044 bytes）、四条 PCM24 Stem、经 FFprobe 验证时长/格式/码率/非静音的 256 kbps MP3、MIDI、Project JSON 与 credits/license/provenance/trace/export manifests。

最终新容器/新 `/temp` 挂载真实队列复验为 Project `af988445-9123-40f6-81bf-7a6bcc037099`、Revision `f49b820e-0e56-4038-9108-a72cdc3affa5`、Run `c713a239-d169-4c02-836f-ec20ad657c3e`、Bundle Artifact `86d18388-1159-4c76-83ed-ffc317948007`；逻辑 Bundle 只保存 13 个校验项与音频 Artifact 引用，自身占 `59,396` bytes，不复制约 100 MB Master/Stem/MP3。Worker 会从数据库 Revision 重新编译 AudioGraph并拒绝不匹配 payload；`audio-artifact.v2` 结构化保存 Revision/Arrangement/render scope，转码和 Bundle 均拒绝跨 Revision 输入。Render/Transcode/Bundle 均先过会计入显式 temp root、真实目录与有效 Job lease 的 StoragePressureGate；跨挂载提升先复制到最终目录的唯一 partial、复核 bytes/hash，再在 Artifact 文件系统内原子 rename。运行中显式取消会中断协程/FFmpeg、清理新建但未登记的输出并阻止迟到/分歧 completion；Chromium 客户端断连会关闭页面并清理一次性 sink/partial；MP3 还拒绝 `max_volume <= -80 dBFS` 的数字近静音。

当前下一条业务纵切不是扩充 Import 页面，也不是先做完整 DAW，而是：

> **S2：把现有 CompositionPlan Graph 作为 `generate` 子图并入唯一 Parent Graph，接通 DeepSeek 与确定性 Fallback，在 PlanApproval 后复用 S1 的 Pattern/Render/Export 事实链。**

S2 仍不得绕过 PlanApproval，也不得创建第三个生产 Graph。S1 的固定策略继续作为无模型降级和回归基线，不改变首版最终要求的 1–5 分钟、最多 12 轨、最多 2 个候选和四个 Style Pack 同时交付。

S2 实施计划 Task 1–5 已独立复审通过：

1. PostgreSQL AI Run、Plan、审批、Event、真实 usage 与请求预算；
2. 可复用且无审批/持久化副作用的 Planning Subgraph；
3. DeepSeek V4 Flash 安全 Provider 合同与持久预算（仅 MockTransport，未付费调用）；
4. Synth Ambient Plan 策略、确定性编译器和 v1/v2 Plan hash 兼容；
5. 原子 `approved Plan → Candidate/Preview → Revision`，包含 receipt、取消/并发/回放和 legacy fail-closed。

Task 6 已把 S1 的完整导出链抽为共享应用服务：严格七步 cursor 依次 enqueue Master、pad/melody/bass/rhythm Stem、MP3 与逻辑 Bundle；首个 Job 创建唯一 MediaRun，后续 Job 复用同一 Run。每次 enqueue/collect 都重新加载权威 Revision/Artifact，校验 Arrangement hash、render scope、track、quality、availability 与 source Job；cursor 只接受一致的有序前缀，重复 completion 不推进第二次。S1 smoke 已删除第二套 payload 构造并复用该服务。

Task 6 验收为 focused unit `12 passed`、真实 PostgreSQL `1 passed`、Ruff、目标 Mypy、S1 script compile 与 `git diff --check` 通过；独立审查经唯一修复复审后为 `Spec PASS / Quality APPROVED`。本 Task 没有修改 Worker/Artifact/取消合同，没有重跑 S1 故障矩阵、Docker 或 DeepSeek API。

**暂停断点：Task 7 尚未开始。** 下一次恢复从“把 generate 分支挂入唯一 Parent Graph v2”开始；之后仍需 Dispatcher/API/SSE、代表性恢复/取消、16+ Eval、Compose smoke 和一次预算受控的真实 DeepSeek 付费验收。S2 不能提前标记完成。

具体前后顺序、阶段门和优化规则见 `NEXT_DEVELOPMENT_ROADMAP.md`。
