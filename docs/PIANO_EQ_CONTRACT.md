# 双钢琴三段 EQ M2 合同

2026-10-19；MF-P05/P06/P11/P13/P15/P16/P17/P18/P21。在 M1 已保存的 v4/v5 双钢琴工程上显式使用；v3 需先保存基础混音。旧 v1–v4 声音不被重新解释。

| 层 | 版本与约束 |
|---|---|
| ArrangementIR | v5，保留 required piano_mix.v1，新增 required piano_eq=piano-eq-state.v1，精确覆盖原两轨，无缺失/额外/重复 |
| PianoTrackEq | track_id + schema_version=piano-eq.v1、profile_id=motif-three-band-static.v1、bypass 严格 bool、low/mid/high_gain_db 严格有限数值 −12..+12；字符串和布尔不能冒充数字 |
| Render profile | engine5；required eq_profile，完整固定 descriptor 进入持久化与 hash |
| Human command | L0 set_piano_eq，payload.eq 为完整两轨 snapshot 或 None；仅 v4→v5、v5 修改、None 从 v5→v4；模型 proposal 不具备此权限 |
| AudioGraph/Job/engine | v5；top eqProfile 完整 descriptor，track.eq3 为六字段设置，省略 track_id；旧 track.eq 保留为原链 |
| ExportPlan/BundleArtifact | v6；pin Revision/IR/hash/profile/engine5，所有读取、重建路径显式支持 |
| Migration | 20261019_0029；历史 IR5/Job5/recipe5/Plan6/Bundle6/EQ command 阻止不安全 downgrade，即使当前 head 已 Undo 为 v4 |

固定 `eq_profile`：schema_version=three-band-eq-profile.v1、profile_id=motif-three-band-static.v1、sample_rate_hz=48000、low_frequency_hz=180、mid_frequency_hz=1000、mid_q=0.8、high_frequency_hz=6000、shelf_slope=1。低/高为架式，中频为峰值；profile 既不能遗漏，也不能由调用者改成另一个听感后继续使用原版本。

原链为审核钢琴→既有 Tone EQ3→新增三段→既有 pan/gain→master/limiter。只为可听轨建立非零段，最多每轨三个 native Biquad；总旁路和全零直接连接，不增加滤波节点。保留 Tone 原链是为了使新旁路/全零保持 M1 声音；其四个分频滤波器不被替换。没有新增依赖、FFT、常驻分析循环、音源或第二套渲染语义。

原 Track/notes/clips/来源/锁/performance 与 M1 mix 保留。v5 的非 None set_piano_mix 保留 EQ/profile5；不能直接以 mix=None 吞掉 EQ，应先退出 EQ。局部语义改音符保留 EQ/mix；不支持的结构/profile/旧 Track EQ 写入拒绝。完整快照及逆序批次保证 Undo；首次启用的逆操作精确恢复原 v4 hash。

Worker 从权威 Revision/Snapshot 重编译完整 graph/hash，拒绝 caller 伪造 gain/profile 或 expectedSilence。mute/solo 由完整 IR 算可听集合后选 stem；可信预期静音才能输出真零 PCM，旧版本及预期有声 gate 不放宽。v5 新 candidate recipe 区分 silence/non-silence 并标明 v5 policy；旧 v4 recipe/hash 不改，历史 M1-R1 仍按路线登记。

前端只将参数写入草稿：三个旋钮及数值、总旁路、当前轨三段归零（gain0/bypassfalse）、恢复保存 EQ。一手势一次草稿命令；非法数值报错而不修改参数。曲线和音频共用生产纯 TS profile/数学模块，显示新增 EQ 的参数响应；旁路实线0dB、虚线保留设置。没有音频频谱、实时试听、单段 enable、频率/Q 编辑、EQ 自动化或整页主题变更；两套候选配色未被选定。

显式保存、重开、草稿 Undo/Redo 和持久 Undo 沿既有机制。试听/导出使用保存版 Revision；新版本不继承旧 MP3，不随旋钮自动排 Job。Master/Stem 保持 48kHz stereo PCM24；MP3 有损，按声明的容差核验；MIDI 表示音符，不宣称携带 EQ 音效。增益提升可能提高电平，既有 limiter 不改，不做隐形归一化。

验收为有界信号/真实 PG/built UI/正式 Worker/Parent export 与一次独立审查，不代表整曲审美、生产 CPU/RSS/P95、Redis/Celery/Compose 故障矩阵。详见[设计](superpowers/specs/2026-10-19-m2-three-band-eq-design.md)、[计划](superpowers/plans/2026-10-19-m2-three-band-eq.md)、[验收](evidence/2026-10-19-m2-three-band-eq.md)。

来源：[W3C Audio EQ Cookbook](https://www.w3.org/TR/audio-eq-cookbook/)（2021-06-08 Note）及 [Web Audio BiquadFilterNode](https://www.w3.org/TR/webaudio/#BiquadFilterNode)，2026-10-19 核对；实际行为由共享生产模块和 PCM 探针验证。
