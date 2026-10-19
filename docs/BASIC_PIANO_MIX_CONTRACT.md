# 双钢琴基础混音 M1 合同

2026-10-19；覆盖 MF-P05/P06/P11/P13/P15/P16/P17/P18/P21。已保存的 v3 双钢琴可显式启用新模式；新声音语义不覆盖旧工程。

| 持久/执行层 | 新版本与约束 |
|---|---|
| ArrangementIR | v4，继承双钢琴约束；required piano_mix=piano-mix.v1，精确覆盖现有两轨 |
| PianoTrackMix | gain_db −60..+6、pan −1..1，有限严格数值；mute/solo 严格布尔 |
| EditorCommand | human-only、L0 set_piano_mix，完整 mix snapshot；None 仅从 v4 恢复原 v3 |
| AudioGraph/engine/Job | v4；required audible、expectedSilence；同一共享 compiler |
| ExportPlan/BundleArtifact | v5；pin Revision/hash/profile/engine4；reader 保留旧版本 |
| PostgreSQL | 0028 扩版本约束；任何历史 v4/Job4/recipe4/Plan5/Bundle5/mix command 阻止不安全降级 |

混音只改变顶层 piano_mix 和显式 profile，原 Track、notes、clips、来源、锁与 performance 保留。进入模式后拒绝旧 set_track_param 的 gain/pan/mute/solo，避免两份真值；局部钢琴语义修改保留 mix，不支持的结构/profile 操作明确拒绝。

有效可听规则为 !mute && (!anySolo || solo)。anySolo 从完整 IR 计算，再选择 stem；多个 solo 是并集，mute 优先。全部不可听生成真实零 PCM。仅由 Revision/Snapshot 重编译并校验完整 graph/hash 的 v4 expectedSilence 允许合法静音；预期有声及旧版本静音门保留。PCM 与 receipt 必须一致。

Web 只改草稿；显式保存形成新 Revision，重开恢复。每轨“恢复当前保存值”回到该保存版，草稿 Undo/Redo 与已保存 Undo 使用既有机制。播放标明保存版；该版本没有音频时，用户显式“生成此保存版试听/导出”，复用 Parent export；不逐滑杆排 Job，不新增模型调用。导出工程保留 mix；MIDI 是原音符，不声称包含音频混音效果。

单钢琴 v2、EQ/reverb/master、实时混音、主题/整页重排、通用 DAW 不在本门。新的专业推子/旋钮/频谱与 EQ 响应曲线仍为设计研究；真实三段 EQ 必须另有预览/导出同源合同。recipe 静音规则标签 Minor M1-R1 记录于路线，不把模拟控件当音频功能。

详见[实施计划](superpowers/plans/2026-10-19-m1-piano-mixing.md)、[验收](evidence/2026-10-19-m1-basic-mixing.md)、[独立审查](evidence/2026-10-19-m1-review.md)。


## 2026-10-19 M2 三段 EQ 增补

后续 M2 已按独立合同实现真实静态三段EQ，保留本M1历史语义；v5非None mix修改保留EQ，退出mix前必须先退出EQ。详见[版本合同](PIANO_EQ_CONTRACT.md)和[验收证据](evidence/2026-10-19-m2-three-band-eq.md)。
