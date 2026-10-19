# P2.2 semantic piano contract v1

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
