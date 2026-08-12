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

这是一条完整的 Import/Analysis/Alignment 纵切，不是完整的 AI 编曲产品。当前系统还不能从用户 Brief 生成并导出一首完整作品。

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
| PostgreSQL/Redis/Celery/Outbox | 可运行 | Compose readiness、幂等事件和恢复测试 | Render Worker 尚未进入正式 Job 链路 |
| 受控音频上传与导入 | 可运行 | 浏览器真实 30 秒 WAV E2E | 多 Stem 加入同一 Project 的产品流程未完成 |
| BPM/key 分析 | 可运行的轻量基线 | FeatureArtifact、置信度与 HITL | 精度阈值尚无规模化 Eval 校准 |
| 保持音高 time-stretch | 可运行的受限基线 | FFmpeg atempo、Artifact lineage、恢复和质量测试 | 尚不是专业弹性音频；复杂 tempo map 不在首版 |
| Artifact 生命周期与 StoragePressureGate | 可运行 | 四态、配额、驱逐/重建、外置 Root | 暂不扩建通用缓存平台，按新 Artifact 类型增量接入 |
| Tone.js AudioGraphCompiler | 部分完成 | 30 秒 Chromium Spike、Master/Stem、6 项测试 | 仅 3 个 Synth Preset 和 click sample；未编译真实 Project |
| PatternSpec 与确定性 Composer | 未开始 | 只有目标合同 | 缺 Plan → Pattern → Note/Clip 编译器 |
| 完整成曲与导出 | 未开始 | 无 | 缺 1–5 分钟作品、WAV/MP3/MIDI/Stem/manifests 正式链路 |
| 四个 Style Pack 与 Theory Engine | 未开始 | 只有设计 | 缺知识卡、规则、示例、检索和许可资产 |
| Web Import Review | 可运行 | 上传、分析确认、试听、恢复、窄屏 E2E | 尚未进入 Project Home、Brief/Plan 或 Timeline |
| Web Studio/DAW | 未开始 | 只有视觉与交互合同 | 缺 Project Home、Brief/Plan、Timeline、Piano Roll、Mixer、Export |
| AI 选区编辑 | 未开始 | 有命令与 ChangeImpact 基础 | 缺 EditPatchProposal 生成、Preview、局部性 Eval |
| Eval/可观测性 | 部分完成 | Trace/Span/Usage 表和 1 条 smoke fixture | 缺真实数据集、OTel、看板、Baseline/消融和失败报告 |
| CI/CD 与负载测试 | 未开始 | 本地脚本 | 无 CI workflow、P50/P95 和完整一键演示验收 |

## 4. 当前验证基线

2026-08-12 只读审计重新执行：

- Python：`152 passed / 13 opt-in skipped`。
- 真实 PostgreSQL 集成：`13 passed / 1 Redis+Artifact opt-in skipped`。
- TypeScript Audio Engine/Render Worker：`6 passed`。
- Web：`15 passed`。
- TypeScript strict 与 Vite production build：通过。
- Ruff：通过。
- Mypy strict：`64 source files` 通过。
- Compose：API、Dispatcher、Resume Dispatcher、Media Worker、PostgreSQL、Redis 运行；`/health/ready` 为 ready。
- 当前迁移 head：`20260812_0009`。

跳过项必须继续保持显式 opt-in，不能用 SQLite 或隐式本机凭证伪造 PostgreSQL/Redis 集成结果。

## 5. 已确认的设计漂移与技术债

### 5.1 生产 Graph 暂时分成两条

`motif-forge-plan.v3` 已实现，但 API lifespan 只编译 `motif-forge-parent.v1`。这是阶段 1 的先行纵切，不是允许长期保留两个独立生产编排器。下一次生成能力开发必须把计划节点作为 Parent Graph 的 `generate` 子图接入；禁止再创建第三个生产 Graph。

### 5.2 音频可靠性领先于创作主链路

Import、Artifact、恢复和容量治理已达到较高完成度，但 `CompositionPlan → PatternSpec → ArrangementIR → Render` 尚未成立。除新 Artifact 类型的必要接线外，暂停扩建通用存储/恢复能力，直到确定性完整成曲 Walking Skeleton 通过。

### 5.3 前后端 DTO 仍由手工维护

`apps/web/src/shared/api.ts` 当前手写解析 API DTO。下一次新增公开业务 API 时，同一纵切必须建立 Pydantic/OpenAPI 到 TypeScript 的生成边界；在此之前不单独发动前端 API 全量重写。

### 5.4 大文件按触达拆分

`api/app.py`、Persistence、Provider 与 Graph 已出现多个 500–900 行文件。不安排独立“大重构阶段”；下一纵切触达某个文件并新增第二项职责时，先保留测试再提取该纵切所需的 Router、Repository 或 Subgraph。禁止顺手改写未经过的模块。

### 5.5 Eval 建设过晚

当前只有 1 条正式 Eval fixture。自下一条创作纵切起，每个任务至少增加一个成功案例和一个失败标签；Walking Skeleton 结束时至少形成 20 条可重复的确定性创作/渲染案例，之后随四个 Style Pack 扩展到首版要求的 96 条。

## 6. 版本治理状态

审计时 `main` 只有一个已推送 commit，而工作区包含 47 个已修改文件和 62 个未跟踪项。它们包含已经验收的完整纵切，继续开发前必须先形成可恢复的里程碑版本。

该收口不是删除或重写用户变更，也不是为追求整洁而重新设计代码。执行时必须：

1. 重新盘点所有状态项并确认均属于当前项目。
2. 复跑本文件第 4 节基线。
3. 以当前完整 Import 纵切作为一个可恢复 checkpoint；若能在不拆坏依赖的前提下安全分组，可按 Domain/Agent、Media/Storage、Web/Docs 分组提交。
4. 不提交 `.env`、API key、音频临时文件、测试 cache 或本机路径。
5. 推送前检查迁移、锁文件、外置 Artifact 忽略规则和文档状态。

在这一版本治理门通过前，不开始新的业务功能代码。

## 7. 当前开发断点

下一条业务纵切不是继续扩充 Import 页面，也不是先做完整 DAW，而是：

> **不依赖 LLM，从固定 Brief/模板生成一首 60–90 秒、4 轨、单候选的 Synth Ambient 完整作品，并由正式 Render Job 完整导出 Master WAV/MP3、四条 Stem、MIDI、可编辑 Project 与全部 manifests。**

这是内部 Walking Skeleton，不改变首版最终要求的 1–5 分钟、最多 12 轨、最多 2 个候选和四个 Style Pack 同时交付。

具体前后顺序、阶段门和优化规则见 `NEXT_DEVELOPMENT_ROADMAP.md`。
