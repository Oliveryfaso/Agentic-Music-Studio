# M1 基础混音第一阶段：实施合同

2026-10-19；BASE/Guide `9e6cf1551295a195ae0402106e8fc73ae29f1810`，工作区和Guide clean。用户已要求继续已有基础混音合同第一阶段，允许验收后正常开发分支同步；不合main、不部署。保持手动模型设置。沿本轮真实API4调用/7228tokens/公开峰值价上界¥0.023852原账，M1不调用模型。

覆盖 MF-P05/P06/P11/P13/P15/P16/P17/P18/P21。本切片只服务现有单/双钢琴（优先已保存双轨经典谱）；volume/mute/solo/pan、保存重开、Undo/reset、明确保存版音频与导出一致。原谱锁继续保护所有音符、片段、来源及Track字段；不做EQ/混响/master编辑、实时AudioContext或整页布局重构。

## 核心合同

- 显式新IR `arrangement-ir.v4`、`MixPianoRenderProfile` engine4；继承现双钢琴约束。`PianoMixState`保存唯一有效gain/pan/mute/solo，逐轨精确覆盖现有track_id，无额外/缺失/重复轨；gain −60..+6dB、pan −1..1、布尔strict。保留原Track所有字段，仅从旧Track初始化一次；拒绝无法无损初始化的超界旧值，不静默clamp。
- 新human-only `set_piano_mix`命令保存完整有限mix snapshot（最多2条），payload `mix: PianoMixState | None`；非None从v3显式升级4或修改4。None仅在v4移除profile并恢复原v3，供精确逆命令/撤回模式；不能删除音符或解锁原谱。命令是L0，不能给模型工具新增此权限；旧v1/v2/v3声音解释不变。初始版本仅v3双钢琴进入新模式，单轨/旧v2界面准确禁用，避免扩大范围。
- 已进入mix模式后，旧 `set_track_param` 的gain/pan/mute/solo拒绝，防止两套可变真值。源Track保持不可变；local note semantic修改需要保留mix。明确不可支持的旧profile/structural操作预写拒绝，不能隐形降回v3。
- 新 `audio-graph-spec.v4` / `motif-forge-audio-engine.v4` / canonical/candidate Job v4；每个piano track新增required `audible:boolean`，有效可听规则 `!mute && (!anySolo || solo)` 在完整IR轨集合计算一次，stem保持相同有效状态。图新增required `expectedSilence:boolean`，仅当所选轨没有audible=true时为true；TS验证与音轨audible逐项一致。音符/Track gain之外的新mix参数决定graph gain/pan，旧eq照旧（当前不开放编辑）。
- v4音频引擎仅调度audible轨；全部mute真正零输出，不使用−60dB模拟。仅v4且规范graph expectedSilence=true时允许receipt peak=0和合法静音MP3；其他版本/预期有声仍拒绝静音。共享Worker再次由Revision/Snapshot重编译graph并比对hash，不能由调用者任意放宽gate。不全局关闭静音检测。
- ExportPlan v5 / BundleArtifact v5显式绑定engine4/render profile。所有旧reader继续支持旧版本；持久JSON类型与command约束如需变更加0028及不安全降级guard。Master/MP3/selected stem使用同一IR/graph语义，工程及provenance保留mix。MIDI仍是原结构音符，不宣称携带音频效果。
- 此阶段不做实时调参。Mixer仅编辑草稿，保存为新Revision；播放始终标明保存版。无该Revision音频时提供显式“生成此保存版试听/导出”入口，复用现有Parent export完整链，避免滑杆每次排Job。实际一致性验收含一份CandidatePreview和同Revision Master/MP3，两个都用同一compile函数；不新增第三Graph或后台任务。
- UI控制器以props/草稿为真值，受控音量/声像、键盘/触控可用；显式按“恢复当前保存值”对本轨产生一个mix命令，回到打开版本的有效mix，不把伴奏−10dB重置成0。保存后重置基准更新。草稿Undo/Redo、已保存Undo继续既有语义；无改动reset禁用。旧非piano界面不冒称solo已生效，可准确说明legacy范围，不修齐整个旧合成器。

## 实施与验证分工

1. 后端作者：IR/mix命令/policy/Undo/版本/迁移/graph投影/Jobs/Export/piano语义保留mix，以及Python相关测试；不动audio/chromium_render.py、audio/transcode.py或TS/Web。先RED再GREEN，PG由主控统筹隔离实例。
2. 音频作者：TS audio-engine/RenderWorker v4与audible/expectedSilence，以及Python上两audio adapter文件和相关unit测试；不动worker/execution.py，由后端作者接allow_expected_silence参数。既有v1–v3行为/golden不改，v4 allmute真实PCM0与有声方向后续真实Chromium验收。
3. 主控：Mixer/editorState/Studio小接线、生成DTO；自有PG+真实Chromium/固定两轨短音频、保存→重开→Undo/reset、音量/左右声像/solo/mute/全静音和试听导出对照；检查无隐藏model/Job风暴。一次fresh声音/状态一致性审查、最多一次作者修复与限定复核，记录文档/清理/checkpoint/push。

至少一个成功Eval与一个失败标签；对照旧v3 graph不变。参数越界/NaN/未知轨/原谱notes变动拒绝，mix不能成为改音符的payload。真实验证固定短样本，不下载新音源/安装工具/改用户库，不停止共享Colima。资源成本用实际耗时/文件量和有限调度记录，不虚构CPU/RSS保证。

Library前置：当前技能支持流程已一次有界尝试；系统Python导入失败后改用已有3.12，助手返回Library prepare_uploads unavailable，未产生可确认ID，停止重试。保留本地文档和四段40.8秒音频，不能声称Library成功。
