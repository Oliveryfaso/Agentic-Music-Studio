# Motif Forge 当前实施状态

> 状态日期：2026-08-12
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

## 3. 能力矩阵

状态定义：

- `可运行`：已接入用户/API/Worker 运行路径，并有可复现验收证据。
- `内部完成`：代码、Schema 或测试已存在，但尚未形成用户可操作的生产路径。
- `部分完成`：只完成合同、Spike 或能力子集。
- `未开始`：仍仅存在于目标文档。

| 能力 | 状态 | 当前证据 | 主要缺口 |
|---|---|---|---|
| ArrangementIR、EditorCommand、Revision、Branch | 可运行 | 严格 Schema、事务写入、乐观锁和测试 | Studio 尚未消费完整编辑命令集 |
| CandidateSnapshot、PreviewCandidate、L2/L3 审批事务 | 内部完成 | 持久化与事务测试 | 没有真实音乐 Preview、公共 API 和 Graph resume 接线 |
| DeepSeek Provider | 内部完成 | JSON、thinking/tool continuation、timeout/429、usage 契约测试 | 未配置 live key 验收；未挂入用户可调用生成入口 |
| CompositionPlan Graph | 内部完成 | Validate/Plan/Repair/HITL/Error Router、PostgreSQL checkpoint 测试 | 尚未成为 Parent Graph 的 `generate` 分支 |
| Parent Graph Import/Recovery | 可运行 | Import、time-stretch、rehydrate、HITL、resume | 尚无 generate/edit/export 路由 |
| PostgreSQL/Redis/Celery/Outbox | 可运行 | Compose readiness、幂等事件和恢复测试 | Generate 尚未并入 Parent Graph |
| 受控音频上传与导入 | 可运行 | 浏览器真实 30 秒 WAV E2E | 多 Stem 加入同一 Project 的产品流程未完成 |
| BPM/key 分析 | 可运行的轻量基线 | FeatureArtifact、置信度与 HITL | 精度阈值尚无规模化 Eval 校准 |
| 保持音高 time-stretch | 可运行的受限基线 | FFmpeg atempo、Artifact lineage、恢复和质量测试 | 尚不是专业弹性音频；复杂 tempo map 不在首版 |
| Artifact 生命周期与 StoragePressureGate | 可运行 | 四态、配额、驱逐/重建、外置 Root | 暂不扩建通用缓存平台，按新 Artifact 类型增量接入 |
| Tone.js AudioGraphCompiler | 内部完成 | ArrangementIR 投影、72 秒 PCM24 Master/Stem、10 项测试 | 仅 3 个 Synth Preset；尚无 Studio/runtime 投影 |
| PatternSpec 与确定性 Composer | 内部完成 | 固定 Brief/seed、Pattern 编译、20 条 Eval | 目前仅 S1 Synth Ambient 固定策略，尚未接 Plan/Style Pack |
| 完整成曲与导出 | 内部完成 | 72 秒作品、Master/MP3/四 Stem/MIDI/Project/13 项逻辑 Bundle | 尚无公共 API/Web；1–5 分钟和 12 轨留待产品验收 |
| 四个 Style Pack 与 Theory Engine | 未开始 | 只有设计 | 缺知识卡、规则、示例、检索和许可资产 |
| Web Import Review | 可运行 | 上传、分析确认、试听、恢复、窄屏 E2E | 尚未进入 Project Home、Brief/Plan 或 Timeline |
| Web Studio/DAW | 未开始 | 只有视觉与交互合同 | 缺 Project Home、Brief/Plan、Timeline、Piano Roll、Mixer、Export |
| AI 选区编辑 | 未开始 | 有命令与 ChangeImpact 基础 | 缺 EditPatchProposal 生成、Preview、局部性 Eval |
| Eval/可观测性 | 部分完成 | Trace/Span/Usage 表和 1 条 smoke fixture | 缺真实数据集、OTel、看板、Baseline/消融和失败报告 |
| CI/CD 与负载测试 | 未开始 | 本地脚本 | 无 CI workflow、P50/P95 和完整一键演示验收 |

## 4. 当前验证基线

2026-08-12 只读审计重新执行：

- Python（非 integration）：`205 passed / 21 integration-only skipped`。
- 真实 PostgreSQL 集成：`21 passed / 1 Redis+Artifact opt-in skipped`；其中 S1 专项 `6 passed`，包含执行前/运行中取消、promote/completion 竞态、分歧重复 completion 清理与容量门合同。
- TypeScript Audio Engine/Render Worker：`13 passed`。
- Web：`15 passed`。
- TypeScript strict 与 Vite production build：通过。
- Ruff：通过。
- Mypy strict：`73 source files` 通过。
- Compose：API、Dispatcher、Resume Dispatcher、Media Worker、Render Worker、PostgreSQL、Redis 运行；API 与 Render readiness 均为 ready。
- 当前迁移 head：`20260812_0012`。

跳过项必须继续保持显式 opt-in，不能用 SQLite 或隐式本机凭证伪造 PostgreSQL/Redis 集成结果。

## 5. 已确认的设计漂移与技术债

### 5.1 生产 Graph 暂时分成两条

`motif-forge-plan.v3` 已实现，但 API lifespan 只编译 `motif-forge-parent.v1`。这是阶段 1 的先行纵切，不是允许长期保留两个独立生产编排器。下一次生成能力开发必须把计划节点作为 Parent Graph 的 `generate` 子图接入；禁止再创建第三个生产 Graph。

### 5.2 音频可靠性领先于创作主链路

Import、Artifact、恢复和容量治理已达到较高完成度；S1 的 `PatternSpec → ArrangementIR → Render` 已成立，但还没有由真实 CompositionPlan 驱动。除 S2 所需 Run/Revision/Render 接线外，继续暂停扩建通用存储/恢复能力，直到 Generate Parent Graph 通过。

### 5.3 前后端 DTO 仍由手工维护

`apps/web/src/shared/api.ts` 当前手写解析 API DTO。下一次新增公开业务 API 时，同一纵切必须建立 Pydantic/OpenAPI 到 TypeScript 的生成边界；在此之前不单独发动前端 API 全量重写。

### 5.4 大文件按触达拆分

`api/app.py`、Persistence、Provider 与 Graph 已出现多个 500–900 行文件。不安排独立“大重构阶段”；下一纵切触达某个文件并新增第二项职责时，先保留测试再提取该纵切所需的 Router、Repository 或 Subgraph。禁止顺手改写未经过的模块。

### 5.5 Eval 建设过晚

S1 已形成 20 条可重复的确定性创作/渲染 Eval。自下一条创作纵切起，每个任务至少增加一个成功案例和一个失败标签；之后随四个 Style Pack 扩展到首版要求的 96 条。

## 6. 版本治理状态

`G0` 已完成：原先跨多个纵切的 48 个修改项和 65 个未跟踪项经逐项盘点后，以一个保持跨服务一致性的里程碑提交 `6bf21f5`（`feat: complete durable audio import web slice`）推送到 `origin/main`。没有提交 `.env`、API key、用户音频、Artifact bytes、dist、node_modules、Python/工具 cache 或 AppleDouble sidecar。

Checkpoint 前复验：Python `152 passed / 13 opt-in skipped`；真实 PostgreSQL `13 passed / 1 Redis+Artifact opt-in skipped`；Audio `6 passed`；Web `15 passed`；Ruff、Mypy strict、Vite build、Compose runtime contract 和 readiness 均通过。Checkpoint 推送后工作区为 clean。

后续每个可独立验收纵切都必须形成 Git checkpoint，不再跨多个阶段积累未提交业务代码。

## 7. S1 验收事实与当前开发断点：S2

S1 已完成：固定作品为 24 bars、80 BPM、4/4、C major、四轨、72 秒；固定 seed 生成完整 ArrangementIR。L3 生成先创建 Candidate/Preview，再由调用者提供 16 字符以上审批断言，事务持久化 actor、审批 payload hash 和原始五条生成命令后物化 Revision。正式 Job 链输出 PCM24 Master（20,736,044 bytes）、四条 PCM24 Stem、经 FFprobe 验证时长/格式/码率/非静音的 256 kbps MP3、MIDI、Project JSON 与 credits/license/provenance/trace/export manifests。

最终新容器/新 `/temp` 挂载真实队列复验为 Project `af988445-9123-40f6-81bf-7a6bcc037099`、Revision `f49b820e-0e56-4038-9108-a72cdc3affa5`、Run `c713a239-d169-4c02-836f-ec20ad657c3e`、Bundle Artifact `86d18388-1159-4c76-83ed-ffc317948007`；逻辑 Bundle 只保存 13 个校验项与音频 Artifact 引用，自身占 `59,396` bytes，不复制约 100 MB Master/Stem/MP3。Worker 会从数据库 Revision 重新编译 AudioGraph并拒绝不匹配 payload；`audio-artifact.v2` 结构化保存 Revision/Arrangement/render scope，转码和 Bundle 均拒绝跨 Revision 输入。Render/Transcode/Bundle 均先过会计入显式 temp root、真实目录与有效 Job lease 的 StoragePressureGate；跨挂载提升先复制到最终目录的唯一 partial、复核 bytes/hash，再在 Artifact 文件系统内原子 rename。运行中显式取消会中断协程/FFmpeg、清理新建但未登记的输出并阻止迟到/分歧 completion；Chromium 客户端断连会关闭页面并清理一次性 sink/partial；MP3 还拒绝 `max_volume <= -80 dBFS` 的数字近静音。

当前下一条业务纵切不是扩充 Import 页面，也不是先做完整 DAW，而是：

> **S2：把现有 CompositionPlan Graph 作为 `generate` 子图并入唯一 Parent Graph，接通 DeepSeek 与确定性 Fallback，在 PlanApproval 后复用 S1 的 Pattern/Render/Export 事实链。**

S2 仍不得绕过 PlanApproval，也不得创建第三个生产 Graph。S1 的固定策略继续作为无模型降级和回归基线，不改变首版最终要求的 1–5 分钟、最多 12 轨、最多 2 个候选和四个 Style Pack 同时交付。

具体前后顺序、阶段门和优化规则见 `NEXT_DEVELOPMENT_ROADMAP.md`。
