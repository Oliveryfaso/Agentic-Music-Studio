# 钢琴语义合同：P2.2 v1 / P2.3 v2

固定Mutopia528/16bar/Gmajor4/4/同包双钢琴。覆盖MF-P02/04/05/06/11/13/15/16/17/18/21；更广P2/P3另列。

- `POST /api/v1/projects/{project_id}/piano-previews` 保留旧人工请求，新增互斥`semantic`：`piano-semantic-request.v1`，intent≤800，mode append/modify，target_track_id、start_bar/end_bar。append只接受新增槽和1..16；modify仅已保存第二轨的连续1..4bar，原和声不变。模型不能获得commit/render工具。
- semantic POST只排队持久EDIT AIRun并返回thread/run IDs；重放由项目+Idempotency-Key与完整请求绑定。已提交但未确认POST的标识由UI sessionStorage绑定project/branch/base恢复；不能凭网络错误自动新付费。
- 使用现`parent.edit.v1` Action/EDIT预算账本，但在唯一Parent的piano_preview分支运行，状态`piano-accompaniment-run.v1`；旧edit/manual piano state照旧读，不创建第三Graph。
- 每Run1request/12000tokens/3072output、inputUTF8≤8000、non-thinking JSON、transport attempts1/schema repair0。`accompaniment-plan.v1`逐bar包含chord/grid/octave/velocity/gate。服务验证后存不可变`piano-plan-record.v1`（0027表）再创建候选；响应返回reported model、摘要、真实submitted请求及usage。known0只能来自observed回执，RESERVED统一unknown/None。
- local harmony来源必须由现NoteEvents与历史Revision/可信Plan或严格人工recipe相等证明，最多64祖先；无法验证付费前失败。Prompt v2收到fixed_harmony，保存前/结果重放后逐bar硬检查；换和弦、不支持意图、非法schema明确失败，不隐形Fallback/repair。
- 新`agent_append_piano_track`与`replace_piano_range`命令均L2。旧human-only append保持原义；range全量Track payload仅由server编译，domain核对metadata、clip/selection和范围外NoteEvents相等。人工精确Undo仍限当前head父版本。
- Candidate Snapshot/source_run_id、真实Worker A/B、exact-hash HITL、保存/重开/Undo/导出复用原链。规划不可即时取消；Worker边界可cancel，待审批可reject。通用旧AI Edit mutation对新piano request预写拒绝，读取/Inspector可用。
- Schema变化为显式新请求/state/record/command type；IR/Graph/engine/Job v1/v2/v3、Plan/Bundle v4声音合同不改。0027前向建表；存在semantic Run或Plan时拒绝危险降级。

实际验收、费用/审查/限制：[P2.2 evidence](evidence/2026-10-19-p22-semantic-piano.md)。后续曲库/混音/UI可复用身份、阶段与审批接口，但本v1的固定谱面/和声范围不能被前端静默放宽。


## P2.3 新来源显式 v2（2026-10-20）

- v1上述16bar/G/4/4合同和旧record原样保留。c01-minuet-g-a16.v1（16bar3/4 G）、c02-la-candeur-a8.v1（8bar4/4 C）、j01-bethena-a-first8.v1（8bar3/4 G）必须使用`piano-semantic-request.v2`，显式`source_score_id`与`beats_per_bar`；registry决定谱内bars，append全范围，modify第二轨连续1–4bar，不含额外尾音bar。
- `accompaniment-plan.v2`带实际beats；PPQ480、step120，3/4每bar12步，4/4每bar16步，step+gate不得越界。G只G/Am/Bm/C/D/Em；C只C/Dm/Em/F/G/Am。固定原和声、原轨及范围外保护不减；新规则单D根音的D/Dm歧义付费前失败，不能猜。
- `piano-plan-record.v2`保存精确请求和固定source元数据；新旧双读，保存前及重放后重验。0030将row/payload/plan/request/source/meter绑定，存在新来源Revision/Candidate、v2请求或record时拒绝危险降级，不更新旧行。上线新writer前先迁移自有目标库到0030；本轮未动用户库。
- 新调用Prompt v3使用实际meter/key/bar ticks/chord词汇；state/Parent/IR/engine/Worker版本不变。1request/12000tokens/3072output/8000输入字节/repair0不变；模型前验证来源/范围/已证和声。新的三曲付费模型质量未验，离线fixture只证明接线。
- UI按权威source report发v2，8bar默认5–8、16bar默认9–12；未知回执同请求重试/刷新，不自动新付费。actual保存/重开/HITL/Undo与既有导出链复用。
- 产品验收：同一实际候选选区，原增益判断力度，固定增益等综合响度比较音色/密度；canonical不改写，不以强诊断滤波代替成品预设。把可辨、意图符合、偏好与客观文件检查分开记录。

[本轮验收与边界](evidence/2026-10-20-p23-semantic-v2.md)。

### P2.3 Q4 explicit register preservation (2026-10-20)

New `piano-accompaniment-prompt.v4` writers retain Plan/Record v1–v2. For a
recognized explicit keep-register clause during modify, `piano-register-preserved.v1`
means that each selected bar's saved Plan `octave` stays equal. It does not mean
locking every note pitch: allowed rhythm changes can select different tones of the
same verified triad. Register-changing requests remain permitted when no keep lock
is requested. This bounded recognizer supports explicit Chinese/English keep phrases;
it is not a general proof that arbitrary prose has been understood.

Before building a Provider, the service proves each octave by replaying the saved
source run's bar plan and comparing exact NoteEvent identities/values and Track
identity through at most 64 Revision ancestors. Missing/manual/unverifiable octave
provenance returns `PIANO_REGISTER_UNVERIFIED`; no inference from a single root.
Contradictory recognized keep/shift clauses return `PIANO_REGISTER_INTENT_UNSUPPORTED`.
The Provider receives `fixed_register`; Provider and application validate exact
per-bar equality before saving a plan, and application revalidates stored-plan replay.
A violation returns `PIANO_REGISTER_CHANGED`, schedules no candidate media and never
transposes/clamps/retries the response. Original melody, harmony, outside-range
notes and hash-bound human approval retain their existing protections.

Historical plans, Revisions and failed Q4 media remain immutable. Existing records
are readable; an old violating plan is refused when rematerialized under the new
explicit lock. Safe optional `register_policy` metadata records the validation rule;
no IR/DB/request schema or migration changes. The saved real 2026-10-20 Q4
counterexample is the failure Eval `PIANO_REGISTER_CHANGED`; compliant replay with
exact model-plan equality and protected notes is its success control. Offline
fixtures are not new model calls or human music-quality acceptance.

The user explicitly accepted the official V4.1-Flash-1017 replacement after the
original seven-call batch was paused. A separate targeted batch may reserve at
most CNY0.20 / two submissions, including failures, within the original cumulative
CNY10 approval; one Q4 call is planned. Old history is not unlocked or reset.
Official routing plus a generic response name does not prove a cryptographic
weight identity. See the task evidence and subsequent outcome for actual use.

### P2.3 music-fit context (2026-10-21)

New v2 calls use `piano-accompaniment-prompt.v5` and record optional
`fit_policy=piano-musical-fit-context.v1`. The pure helper supplies compact
advisory facts: duration/metric-weighted two-chord candidates with a bounded
passing/neighbor heuristic, a few reductions checked against pinned source
left-hand voices, source cadence destinations, exact repeated-bar identity,
pulse steps and the principal's terminal rest. It neither identifies a unique
true harmony nor certifies musical quality. Source seventh chords, inversions,
chromatic inner voices and phrase-internal harmony changes remain outside the
current triadic/barwise palette; historical `default_chords` are rule baselines,
not original-score harmony ground truth.

For modify, source chord candidates/anchors/cadences are omitted; existing
fixed_harmony and fixed_register always win. Advice never rewrites/clamps a
returned Plan or adds paid repair. New/old Plan and Record schemas, IR, compiler,
Graph, storage, DSP and instrument stay unchanged. Cached historical plans are
replayed exactly, not reinterpreted by new taste rules. There is no new hard
quality rejection based on scale/chroma/dissonance or movement proxies.

Eval labels for the saved corpus include HARMONIC_ROLE_DRIFT, METRIC_PULSE_DRIFT,
UNMOTIVATED_REGISTER_LEAP and CADENCE_REST_FILLED. They name observable hypotheses,
not universal errors: syncopation and nonchord tones can be intentional. Compare
single-field chord/grid/octave controls and fixed-gain equal-LUFS full mixes;
separate fit, melody clarity, phrase flow and preference in human acceptance.
