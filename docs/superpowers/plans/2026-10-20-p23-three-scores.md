# P2.3 First Three Scores Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 三份审核旋律完成导入、加轨、试听保留、重开、Undo和完整导出。

**Architecture:** 固定来源registry代替单曲限制；确定性编译使用实际拍号/小节数。旧语义v1保持，新来源使用v2请求/计划及record，复用Parent Graph、Revision和Worker。

**Tech Stack:** Python3.12/FastAPI/Pydantic/PostgreSQL/LangGraph；TypeScript/React与共享AudioGraphCompiler。

**Spec:** `docs/superpowers/specs/2026-10-20-p23-three-scores-design.md`

## Global Constraints

- PPQ480，3/4或4/4，每曲另1小节仅供尾音释放。
- 不执行LilyPond、不装工具/下载新数据、不新增付费调用、不改旧声音/哈希、不合main/部署。
- 保留原谱锁定、单Parent、HITL、持久重放及精确Undo；披露转换损失及Public Domain来源。

## Review Focus

1. 换曲或重试必须绑定当前scoreID/确认/key。
2. 3/4 gate、8小节上限、谱内休止与尾音小节正确。
3. 错meter/key/来源结构即使ref/hash正确也应拒绝；v1不能冒充新来源。
4. 重放/拒绝/Undo保留原轨、范围外音符与模型支出；和声不能猜。
5. 新来源/schema存在时降级安全拒绝；旧工程回放/导出不改写。

### Task 1：来源注册、导入和导出

**Files:** 新domain/reviewed_scores.py；application/classical_import.py、api/classical.py、application/exporting.py、domain/accompaniment.py、commands.py；resources/scores新增三份XML/manifest/源文本/rights/conversion；unit/domain/test_reviewed_scores.py及API/application/eval测试。

**Interfaces:** `reviewed_score(score_id: str = SCORE_ID) -> tuple[dict[str, Any], bytes]`；`reviewed_source(base: ArrangementIR) -> ReviewedScore`核验唯一ref/version/PPQ/meter/key/duration；四个固定ID，legacy默认兼容。

- [ ] RED：三个新ID可构造导入；各曲真实notes/meter/tail/stableID；规则伴奏每bar3或4拍；原轨和精确Undo；未知ID/错version拒绝；C02末拍休止保留。
- [ ] 观察因当前单曲限制失败，保留日志。
- [ ] GREEN：registry、所有打包文件hash检查、事务/audit/source/export参数化；新增F/Dm三和弦，旧默认不变。
- [ ] focused旧+新测试及导出/MIDImeter检查通过。

### Task 2：实际节拍的语义计划与重放

**Files:** domain/piano_plan.py、piano_requests.py、ai_runs.py；providers/piano.py；application/piano_semantic.py、piano_harmony.py、piano_preview.py；api/piano.py；infrastructure/persistence/piano_plans.py、tables.py；0030迁移；unit/provider/integration/eval。

**Interfaces:** `PianoSemanticRequestV2`带beats_per_bar；`AccompanimentPlanV2`及union解析；compile_piano_plan接受v1|v2并使用来源bar_ticks；record v2与旧v1并存。provider上下文真实meter/key/chords，单次预算保持。

- [ ] RED：三曲v2 append/局部modify；3/4 step+gate>12拒绝；v1新来源拒绝；错meter/8bar越界在planner前拒绝；C调F/Dm有效、不支持7th；原轨/范围外保持；record replay不调用。
- [ ] 观察失败后实现版本union、确定性时间、0030 JSON版本绑定及降级guard。
- [ ] GREEN：旧语义/provider/store回归及实际PG边界通过。

### Task 3：目录交互与三曲真实闭环

**Files:** apps/web/src/features/projects/ClassicalScoreEntry.tsx、classicalApi.ts、studio/PianoPanel.tsx和tests；generatedDTO；docs/evidence/2026-10-20-p23-three-scores.*、IMPLEMENTATION_STATUS、roadmap、TECH_EVOLUTION。

**Interfaces:** 选曲ID/名字/确认/key同一意图；PianoPanel按import_report构建v2，legacy用v1；8bar默认5–8，16bar默认9–12。

- [ ] RED：换曲reset确认/key，导入当前ID，8bar/3/4请求范围正确，越界禁止，F/Dm可用。
- [ ] GREEN：最小界面改动、生成DTO；不重写整页/主题。
- [ ] 相关Python/Web/Audio、mypy/Ruff、两build；真实PG/正式Worker三曲import→rule preview→reject/approve→reopen→Undo→MIDI/完整导出，核验sourceTrack/meter/hash/credits。离线semantic明确只属接线测试。
- [ ] fresh独立review，至多一次修复复核；记录限制、模型0及storage前后，recheck Guide diff。
- [ ] 更新证据/状态/演进，Git checkpoint和正常dev push，核对main未变；ledger写实际结果。
