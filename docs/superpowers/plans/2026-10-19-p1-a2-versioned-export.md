# P1 A2 版本化单轨导出与持久合同接线计划

2026-10-19；Stage P1-A2；MF-P02/P05/P06/P08/P10/P11/P15/P16/P17/P18/P21。起点2d6d588，工作区clean，Guide无diff。用户明确继续A2/B，7-Zip未批准，不下载运行。保持手动模型。按executing-plans/TDD执行；当前可独立验收A2.1纯合同/文件边界，不能把它写成生产A2或持久v2完成。

## 已核实依赖与真实资源门

现有EXPORT_STEPS/CompleteExportCursor.v1在application/generation.py；Agent generate.py两处创建/一处reader；EnqueueNextCompleteExportJob/CollectCompleteExportArtifact和build_export_bundle_payload固定四角色；domain/media_jobs.py BundleJob.v1固定6音频；domain/exporting.py Request.v1同样6音频；worker/execution.py parser/loader/gate只接受v1；application/export_reads.py及persistence/export_reads.py固定7步/13文件；ExportPage通过生成DTO消费投影。完整接线不能只改常量。

B持久v2另外触及domain ir/revisions/candidates/commands/canonical、database.py row读写、preview readers、生成与编辑、AudioGraph/Job/Recipe版本和Alembic前向/降级guard。当前迁移源码在infra/migrations/versions，已仅用ScriptDirectory读取迁移源码head=20260824_0021（未执行env.py或连接DB）；未来迁移需据此接续，不猜编号。

宿主PATH及常用已安装Postgres位置均无postgres/initdb/pg_ctl/psql；MOTIF_FORGE_TEST_POSTGRES_DSN未配置。现有integration fixture明确禁止SQLite/默认连接/隐式凭据。未读取.env、不扫描或连接用户库；不启动共享VM或新装DB。因此只能完成以下A2.1纯合同和真实文件边界，生产Outbox/持久checkpoint/UI/新v2写入必须等待授权的隔离PostgreSQL验收条件。

## A2.1 当前执行

- 新独立export-plan.v2固定project/revision/arrangement_hash/seed/实际轨道ID；新请求默认为master+MP3，可显式选择真实stem IDs或不请求MP3。MIDI/project/credits/license/provenance/trace固定保留。输出步骤与名字从plan推导，不接受任意step或路径；顺序规范化，plan hash参与幂等。
- 新complete-export-cursor.v2验证plan hash、完成prefix、Job/Artifact计数、pending与MediaRun身份，旧cursor.v1定义/序列化不改。显式双读helper先供测试使用，不先让Graph生成v2 checkpoint。
- 新export-bundle-job.v2与request.v2对准确输入集合/filename/profile做严格验证，binding helper从真实Revision验证实际轨道ID；旧v1 job/request仍只接受4stems/6音频。
- 现有write_export_bundle通过显式版本分派支持内部v2 request，manifest.v2写plan hash；v1 identity/manifest/bytes保持不变。共享元数据/MIDI写法继续复用，不新增Graph。音频仍是受控Artifact引用，不把WAV复制进checkpoint。
- RED→GREEN：单轨master-only、默认MP3、一个真实stem、不存在轨道、错revision/hash、重复/越界progress、unknown版本、旧7步cursor与旧6输入约束；真实临时FS打包fixture验证8/9/10按计划文件数和完整checksum，重复幂等/取消/缺依赖路径。自制PCM与已有FFmpeg仅是文件交付fixture，不是钢琴音质或canonical DSP验收。
- 验证：新窄测试→受影响application/domain/audio/export tests→unit组合/Ruff/Mypy。一次独立审查，当前路径Important先RED→GREEN。仅本地checkpoint、证据/清理，不push。

## A2.2 等待Postgres后

先验证新版Job/Cursor双读和严格绑定，接入原Enqueue/Collect/同一Parent Graph，不新增第三Graph；旧Run仍按v1执行，新显式请求才v2。Bundle artifact/read模型固定plan hash/version，持久读/下载依据计划核对文件集；API/DTO/ExportPage展示真实步骤与未请求stem状态。隔离PG证明一条single-track Revision master-only与显式单stem、重复完成/刷新、重启checkpoint、旧7步恢复；通过后才允许生产创建v2 cursor/job。

## B 持久v2合同顺序

A2接线之后逐producer/consumer明确ArrangementIRV2/render_profile/performance_plan的canonical hash，保留v1 bytes；dual readers与commands重建/Undo/Candidate一起实现。schema能力marker和downgrade guard先验证，再放开v2写。单纯JSON往返/Mock不能证明事务、迁移、回退或真实持久恢复；未有隔离PG时不改生产reader或用户库，不引入SQLite分支。

## 账本

Ruling：先做A2.1纯合同/FS子门，不开启生产v2输出 — 当前无授权隔离PG可验同一Parent/Outbox事务 — 代价是用户导出入口仍为legacy，A2/B整体未完成。
Ruling：B目前只冻结兼容和迁移接线计划，不先存v2 JSONB — 避免新写可存但旧reader/Undo读不回 — 代价是持久v2需等待真实PG资源门。


## A2.1执行结论

本内部子门已验：API unit561、Mypy5源、Ruff7文件、真实FS三包8/9/10逻辑文件通过；一次独立审查无新增Critical/Important。隔离PostgreSQL集成2 skipped，A2.2/B保持未激活，真实钢琴不准入。详见docs/evidence/2026-10-19-p1-a2-contract.md。仅清理本任务Mypy cache，保留accepted；无push/发布/新工具。
