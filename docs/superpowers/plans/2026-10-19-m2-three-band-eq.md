# M2.1 三段 EQ Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.用户已明确授权继续主线、选择低资源实现并先音频/接口后最小交互，沿既有分工执行；一次fresh独立最终审查。

**Goal:** 已保存双钢琴M1版本可真实调整三段EQ，保存/重开/Undo/试听/导出同源。
**Architecture:** 保留M1音色链，原生三段静态biquad显式IR/graph/engine5；人类L0完整EQ snapshot；无实时频谱或新Graph。
**Tech Stack:** 现有Python3.12/Pydantic/PostgreSQL、TypeScript/Web Audio/Tone/Chromium、React。
**Spec:** `../specs/2026-10-19-m2-three-band-eq-design.md`。

## Global Constraints

BASE/Guide9520a89548826baf0c9882f96422694e1cc6ff69/clean。MF-P05/P06/P11/P13/P15/P16/P17/P18/P21。Profile180/1000/Q0.8/6000Hz、S1、48k；gain±12严格有限，bypass严格bool；源Track及M1mix不变。保留旧v1–v4、recipehash/版本读取。无付费/新工具/主题重排/假频谱/main合并/部署。自有PG由主控隔离提供，所有测试禁.env/模型/Tracing key。

## Review Focus

- EQ后改gain或旧profile命令不得丢eq/降版本；领域混合命令与Undo测试。
- 非法HTTP类型不得进入事务，未知profile/轨道和伪静音拒绝；API/TS/Worker负例。
- 旁路必须保留参数并回到M1实际声音；共享compiler真实PCM对照。
- 曲线仅显示新增EQ，native架式Q语义与数学S1一致；native频响/实际PCM与公式交叉核对。
- 保存新版本不得播放旧MP3，隐藏/离开不得遗留绘图循环；builtUI路径与资源关闭。

### Task 1：领域、版本与持久接口（后端作者）

**Files:** `domain/ir.py,commands.py,policies.py,revisions.py,piano_plan.py,media_jobs.py,export_plan.py`；`application/rendering.py,undo.py,media_jobs.py,exporting.py`；`api/app.py`；`worker/execution.py`；`infrastructure/persistence/tables.py,media_jobs.py,export_reads.py`；migration0029；新M2领域/HTTP/Worker/Eval/PG聚焦测试。不动TS/Web与audio两个adapter。
**Interfaces:** Spec命名 `PianoEqProfile/PianoTrackEq/PianoEqState/EqPianoRenderProfile/ArrangementIRV5/SetPianoEqCommand/SetPianoEqPayload`；graph5 top eqProfile、track eq3；Job5、Plan6/Bundle6。

- [x] RED：v4固定两轨→set_piano_eq→v5，原Track/mix/performance完全相同；参数/权限/选轨拒绝；v5改mix和local-note保持EQ；EQ+mix批次精确Undo。
- [x] GREEN：实现最小schema、humanL0、inverse、严格HTTP及所有版本dispatch/reader；消费新静音策略标签不改旧recipe。
- [x] RED→GREEN：Job/Export/rebuild pin，伪graph/profile/hash失败；成功与失败Eval。
- [x] 迁移0029及PG测试：真实JSONB保存/重开、幂等、精确Undo，head回4但历史5阻止downgrade。PG只由主控执行。
- [x] 窄pytest+Mypy/Ruff，提交文件账本给主控；不commit/push。

### Task 2：共享音频、曲线数学与bridge（音频作者）

**Files:** 新 `packages/audio-engine/src/piano-eq.ts`；contracts/compiler/validation；render-worker executor/page/server；Python `audio/chromium_render.py,transcode.py` 仅必要版本识别；对应聚焦测试。不改domain/worker/execution/Web。
**Interfaces:** `PianoEqProfile`与 `PianoEqSettings` TS数据与spec蛇形字段一致；导出 `PIANO_EQ_PROFILE`、`eqResponseDb(eq,profile,frequencyHz)`、`connectPianoEq(context,input,output,eq,profile)`；v5继承audible/expectedSilence，top eqProfile+track eq3。

- [x] RED：unknown/mismatchprofile、gain非有限/超界、bypass伪bool拒绝；zero/bypass不加滤波，active最多3；旧v1–v4不变。
- [x] GREEN：纯TSprofile/数学/native连接；compiler只在v5现ToneEQ3后插入新filter，旧路径不改；bridge/Python正确信任5静音。
- [x] 测公式flat/旁路、峰值中心、架式端点及组合响应，必须给主控可真实浏览器复验接口；测试不镜像实现。
- [x] 窄audio/adapter tests、tsc/build、ledger；不安装/启动服务/付费/commit。

### Task 3：最小EQ交互（主控，Task1/2接口到位后）

**Files:** 新 `apps/web/src/features/studio/pianoEq.ts,PianoEqPanel.tsx` 与聚焦tests；MixerPanel/editorState/sharedunion/generatedDTO；只需小范围scopedstyle，不全页配色。
- [x] RED：v4默认0/false，v5保存值；一次手势命令、旁路保留、归零、恢复保存值、数字错误、轨道切换/Undo同步。
- [x] GREEN：三个可键盘/数字输入旋钮、总旁路、重置/恢复，SVG参数曲线；不加单段开关/频率Q或分析器。
- [x] 生成DTO并核union5、编辑保存路径保持hash/revision/音频身份；Web窄测/build。

### Task 4：真实边界、一次审查与交付（主控）

- [x] 自有PG0029、真实持久化M2边界；真实compiler/native多正弦频响，v4/v5旁路PCM与curve误差证据。
- [x] builtUI+正式Worker/Parent保存版Preview/Export/Undo，源Track/mix/旧hash/负例/幂等/音频版本一致，无模型调用。
- [x] 实际节点/渲染时长、产物大小/服务退出与必要资源指标；相关组合回归一次，不堆重复矩阵。
- [x] 一次fresh独立审查，最多一次修复复核；有阻塞即停报，不无限循环。
- [x] 更新合同/状态/Guide/TECH/延期项；精确库存与关闭自有资源，保留accepted/失败证据。
- [x] Git checkpoint，正常推当前开发分支；ls-remote确认head与main；交本地报告/试听/归档与剩余边界。不上传密钥/DB日志/音源。

Self-review：上述四任务覆盖spec，profile/字段/版本命名一致；五个reviewfocus均有测试归属。测试次数按风险而非数字目标；新版本dispatcher逐项核，不能仅grep替换。

收尾记录：实现、真实边界、唯一审查/修复复核、文档与资源关闭已完成。远端 checkpoint/push 以本次提交与主控回执为准，不以勾选代替远端证据。最终 Python838/Web115/Audio124/PG1/Mypy133；两UI Minor均关闭，历史M1-R1范围保留。
