# P1 B/C2/D/E — 可保存、可审批、可撤回的真实钢琴

2026-10-19；MF-P01/P02/P05/P06/P08/P10/P11/P13/P15/P16/P17/P18/P20/P21。BASE `a099cc50893b1ee0fe714bade595af25c11a170b`。本次有限生产纵切已验收，**不是整个 P1/MF-P09、踏板、P2–P5 或发布验收**。Guide 起点 `e3d9438`/clean；本轮最终仅同步其实施状态，未改变产品要求。手动模型设置未改，无付费模型或新包下载。

## 用户行为与版本边界

首页“新建钢琴练习谱”创建确定性自制30秒单轨谱。Studio 的力度/起音/gate覆盖独立于原谱，生成原声/表达两段试听；同位置A/B、确认/放弃/取消、URL刷新恢复待批、精确候选hash审批后才写入新Revision。保存的试听按同项目+相同arrangement hash读取，显示为160kbps预览；正式WAV经既有动态导出。受限Undo恢复当前专用钢琴命令的精确父快照，不放宽其他L2。

ArrangementIR v1/旧aliases/旧引擎保持，新增显式IR v2、render-profile/performance-plan；Revision/Candidate/Studio/DB/命令保持版本。共享compiler使用AudioGraph/Job v2和审核catalog；ExportPlan v3/BundleArtifact v3固定engine2。0024/0025双读与前向CHECK、不兼容downgrade guard有真实PG证据。人工作业挂同一Parent `operation=piano_preview`，复用Preview/Snapshot/Job/Outbox/HITL，没有新生产Graph/AI Run/模型调用。Worker resume dispatcher识别专用run type。

固定一条乐器轨、PPQ480、globalBPM、48kHz、32voices/2000notes；已审核CC0小包单有效力度层。踏板/releaseTrigger、不支持的非默认clip/articulation明确拒绝；固定profile下普通instrument_ref切换拒绝并在库界面说明，旧v1保留原选择。Bundle带确切来源/作者/archive/license/manifest哈希。

## 实测与复现范围

实际链：v1自制谱→原声canonical导出→两个candidate预览→错误hash409→精确人工审批及重放→新app/checkpoint读v2→Plan3canonical导出→Undo→新连接读v1/hash/音频→Undo canonical导出。8Jobs/3Bundles、5次短真实Chromium渲染；所有导出文件实际下载size/SHA校验。每个Worker步骤重开app/checkpoint连接，实际持久Outbox交生产Publisher并重复投递。不是Redis/Celery进程、Compose重启或断电证明。

另外实际built UI+Uvicorn HTTP+独立Chromium验证新建入口、排队试听刷新/取消、已保存v2播放、390px无横向溢出；真实无catalog executor拒绝INSTRUMENT_PACK_UNAVAILABLE，无回退。该项目AI Run查询0，模型调用/Token0。隔离profile、随机loopback端口与进程已关闭。

三份PCM24 WAV均30秒/48k/stereo/8,640,044B，last2s peak0。Undo相对原声max1LSB；钢琴与原声差分RMS0.0546732，钢琴peak0.241933。Eval成功PIANO_EXPRESSION_AUDIBLE只说明信号不同；两版未做响度匹配，不能推断主观音质。失败Eval为上述真实缺包拒绝。既有A1/C1资源门未重跑；没有本轮生产冷/热RSS新上限。

## 审查、修复与检查

一次[独立审查](2026-10-19-p1-piano-review.md)发现2Important、0Critical/Minor，作者一次有界修复：已知准备前服务/缺包失败使用新intent，网络失败保留原key；v2普通换音色fail-closed，v1不变。复现测试先RED后GREEN，真实PG拒绝错误换音色且head不变。没有第二轮独立审查，不把作者修复验证冒充复审。

最终Python unit/Eval/相关真实PG **635 passed/15.35s**；Web **92 passed**；Audio/Worker **59 passed**；Mypy **121源文件**；Ruff、TS/audio宿主build及最终web build通过。一个既有Starlette/httpx弃用warning。实际链还修复了strict JSON tuple解析、保存/Undo试听读取、Undo新ID配旧IR、A2.2多Bundle标量读取等消费边界。完整[机器证据](2026-10-19-p1-piano-production.json)与[裁决账本](2026-10-19-p1-piano-ledger.md)。

## 运行配置与清理

仅当正常启动本地render service时，显式提供 `MOTIF_FORGE_REVIEWED_PIANO_ROOT=$PACK_ROOT` 和 `MOTIF_FORGE_REVIEWED_PIANO_MANIFEST_SHA256=264fdbf12f3c7273a0d15fbcb86abed04b73e08b6fc4faf482eaf41040a0b813`；PACK_ROOT指向已审核manifest、CC0与WAV所在目录。没有默认下载/任意路径请求/缺包fallback。正常应用需迁移至0025；本任务未读取真实.env、未升级用户数据库、未常驻应用。

最终精确核对自有PG容器ID/label后移除容器与生成DSN/private目录。只清理具名可重建启动器、空log和自身临时metadata：54,631,469→54,564,567 logical bytes，partial0。保留已审核源包/CC0/manifest/accepted音频；共享Colima/旧容器不停止，不prune，Docker context不变。自制隔离测试项目随临时DB清除，音频/JSON证据保留；本地checkpoint保留当前分支，不push/发布。MF-P09默认古典/爵士入口过滤仍是下一独立UI Task。
