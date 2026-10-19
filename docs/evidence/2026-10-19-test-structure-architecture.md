# 测试精简与技术栈判断

2026-10-19；P1 supporting task，MF-P15/P16/P17/P18/P21。结论：这次应减少过时和重复的证明，把下一步精力用于新音色的版本化保存、恢复与编辑。现有 Python + TypeScript + PostgreSQL 的分工足以继续推进，没有证据要求引入 Java；Rust 应等实测热点明确后再考虑。

## 本轮实际删了什么

删除 S2/S3/S5/S6/S7 五个“门禁列出自己、package 命令必须这样拼写”的测试，及一个仍要求 README 保留旧英文说明的文档布局测试；删除 S3 一个已过时的“只读时间线”字符串断言。S7 gate 不再先跑 S7 Eval 子集再跑全 Eval，也不再在 OpenAPI 生成之前多构建一次 Web。报告生成有自己的用途，未当成重复测试删除。

六个测试函数都可从 Git 恢复；没有找到完全相同 AST body 的测试，不能把它们说成“完全重复用例”。删除理由是没有独立的行为保障，且已引发文档/文案漂移误报。没有为了降低数量删除版本兼容、缺陷回归、安全或真实边界检查。

| 同一 root tests 范围，各实测一次 | 修改前 | 修改后 |
|---|---|---|
| 结果 | 38 passed / 2 failed（过时文案/位置检查） | 34 passed |
| pytest 报告耗时 | 8.81 s | 7.91 s |
| 整个测试进程耗时 | 9.852 s | 8.819 s |
| 最慢停止流程测试 | 7.29 s | 6.60 s |

这不是稳定提速证明。顺序、缓存、主机负载未控制，最慢的保留测试自身波动约 0.69 秒；本批可确认的收益是减少误报和重复执行。没有更改这个较慢测试的等待逻辑，因为它验证 PID 所有权、正常停止以及不删数据。

保留的 Compose 测试现在显式用 `--env-file /dev/null`，防止自动读取真实 `.env`；它仍解析实际 Compose 并检查假 Key 只给批准服务、输入输出隐藏、非观察服务无 Key。默认关闭追踪的示例配置检查也保留。LangSmith 文档现行位置人工核实为 `docs/LANGSMITH.md`，没有改 README 来满足旧测试。

## 风险覆盖及日常运行方式

| 层 | 保护的失败 | 本次处理/耗时证据 |
|---|---|---|
| Python unit | 音乐/命令边界、预算、schema/hash、取消/重试/幂等、旧版本 | 保留；最近 A2.1 历史 561 passed/6.86 s，本批未重跑，不作为当前新验收 |
| Python integration | PostgreSQL 事务、Revision/审批、Job/Outbox/Artifact lineage 与读模型 | 保留；本轮独立临时 PG 两个导出边界 2 passed/1.18 s，其他未重跑 |
| Eval | 有界生成/编辑、成功与失败分类、报告分母 | 保留；删 S7 gate 的子集重复调用，全 eval 仍执行；未宣称音乐审美过关 |
| root contracts | 启停所有权、无付费/密钥隔离、smoke 入口边界 | 小批精简；仍有弱源码检查，不能替代实际行为 |
| TS audio/Worker | 映射/资源 cap、样本/许可 hash、旧 v1、sink 与新启动竞态 | 保留；本轮最终 55 passed，JSON suite span 约 0.94 s；不是含 npm 启动的 wall time |
| Web + browser journey | 导入/生成→编辑→渲染→导出及实际控件、刷新/恢复 | 保留；本批未重跑旧端到端，历史可运行路径不等于新钢琴路径 |
| 长音频/压力 | 五分钟资源与超时/取消，最大密度/并发 | 独立 probe 按资源变更/阶段门运行；不放日常 pytest；12 轨/20k events 最坏负载仍未验 |

日常只跑改动对应的窄层和一个必要边界。跨服务或每 2–3 个任务检查组合回归；阶段门才跑完整 Eval、Web build、真实 PG 和必要 browser journey。文档改动核对链接/事实；不因此重跑音乐渲染。原谱保护、新古典轨隔离、持久 Undo 应由下一条真实链路验证，目前仍是计划，不登记成通过。

AST 清点附录：127 个 Python 测试文件，unit 414、integration 70、eval 17、root 37 个函数定义（精简前）；参数化执行数不同。读取文件可能是在核对真实产物，mock 可能是在隔离付费或外部系统，因此不按 `read_text` 或 mock 次数自动判坏。这次没有批量合并不相关测试，也没有引入新的测试框架。

## 代码支持的技术栈分工

| 现有层 | 已实现的具体责任 | 代码证据 |
|---|---|---|
| Python | FastAPI、唯一 Parent Graph、严格领域模型/命令、任务与确定性编译、Worker 调度 | `api/app.py`、`agent/parent_graph.py:778`、`domain/commands.py`、`worker/outbox.py` |
| TypeScript | React 工作台、共享 Tone/Web Audio 语义、Chromium Render Worker、PCM 编码 | `apps/web`、`packages/audio-engine/src/compiler.ts`、`wav.ts:40`、`services/render-worker/src/page-entry.ts` |
| PostgreSQL/SQL | Revision JSONB+hash/version、Branch CAS、Job 幂等/lease、Outbox/inbox 去重、Artifact 身份/lineage、迁移 | `infrastructure/persistence/tables.py`、`database.py:440`、`worker/outbox.py:170`、`infra/migrations/versions` |

这里的 SQL 不是未来待补的另一门语言。本轮在自己创建的 PG17.10 临时库上实际执行现有迁移、核对 30 张 app 表；选定表可见 38 个约束和 18 个索引。举例：Job 唯一键包含 project/type/idempotency_key；Outbox 有 dedupe 唯一键和 dispatchable 索引；Artifact 有来源互斥、版本化 lineage 检查及候选/非候选部分唯一索引；Branch head 更新比较 expected head。不能再把“没有数据库约束/幂等/索引”写成架构缺口。[PostgreSQL 17 约束文档](https://www.postgresql.org/docs/17/ddl-constraints.html)解释这些约束的作用（访问 2026-10-19）；本项目是否存在则由实际 schema 和代码证明。

真正待验证的是新版本的一致性：`database.py:503`、`project_reads.py:205`、`media_jobs.py:127` 仍按 v1 ArrangementIR 读取，`commands.py:365` 仍重建 v1；导出表目前 project+revision 唯一，若将来同一 Revision 允许多个 export/render profile，身份和重放语义必须一起确定。已有 A2.1 helper 不代表这些消费者已接线。新增字段还须穿过读模型、恢复、hash、Undo 和不兼容版本保护；这不是换语言可以替代的工作。

## 优先顺序

1. 完成 A2.2 的 Parent/Outbox/Job/权威导出读模型，再完成 B 的双读、版本身份、命令与持久 Undo，形成新琴可保存、可编辑、可导出的链路。直接提升用户功能和版本可靠性。
2. 若资源仍阻碍这条链路，在解码前后、render 前后、PCM 编码和上传/释放后分阶段量 CPU/耗时/内存；区分 JS heap、ArrayBuffer、浏览器子进程和共享页，比较固定作品的 cold/warm，检查缓存寿命与并发。当前 30 秒聚合 RSS 约 1.16 GiB 不能定位具体热点。
3. 先评估减少完整缓冲同时存活、序列化/拷贝、编码分块和缓存释放。当前编码确实分配完整 PCM24 ArrayBuffer，渲染也返回整段 AudioBuffer；5 分钟双声道 Float32 原始输出约 115.2 MB，PCM24 约 86.4 MB，但这些只是可见底数，不能解释全部 RSS。[W3C Web Audio 规范](https://www.w3.org/TR/2021/REC-webaudio-20210617/#OfflineAudioContext)规定离线渲染结果为 AudioBuffer，底层处理通常由浏览器实现；把 Python 调度器换成 Java 不会自动消除这些缓冲。分块音频也必须验证音色、效果尾音和拼接连续性，不能直接切段冒充等价。
4. 只有 profile 证明 CPU 密集的 DSP/分析/编码长期主导，并且优化 Python/TS 或现有 FFmpeg 不足时，才评估一个有明确输入输出的 Rust/WASM/native 模块，同时把跨语言调用、数据复制、部署和声音兼容纳入对照。先测再改，见 [Rust Performance Book 的 profiling 方法](https://nnethercote.github.io/perf-book/profiling.html)；没有实测瓶颈时不做 Rust 重写。现阶段也没有独占 JVM 依赖、组织约束或可测收益支持引入 Java。

这些是本项目当前证据下的工程判断，不是“某语言一定更快/更成熟”的普遍结论。未换语言、未装运行时、未修改生产数据库。测试精简独立审查无阻塞，Ruff/脚本语法/diff 检查通过；剩余弱源码断言的局限已明确保留。


## 复查入口

- [before/after 原始输出、清点和审查记录](2026-10-19-test-structure-architecture.json)
- [真实 PG/schema 与钢琴资源证据](2026-10-19-p1-c1-real-piano.json)
- [最小精简计划](../superpowers/plans/2026-10-19-test-structure-minimal-trim.md)
- [事务、版本、索引与约束代码](../../services/api/src/motif_forge/infrastructure/persistence/tables.py)
- [旧 Revision 读取和 Branch CAS](../../services/api/src/motif_forge/infrastructure/persistence/database.py)
- [PCM24 全量缓冲编码](../../packages/audio-engine/src/wav.ts)
