# Motif M2.1：双钢琴真实三段 EQ

2026-10-19；BASE/Guide `9520a89548826baf0c9882f96422694e1cc6ff69`，工作区与 Guide clean。用户已明确要求沿 M1 继续，先检查链与成本，再选择低资源实现，音频/接口优先、最小交互随后，独立审查通过后正常开发分支推送。沿既有 Sol/xhigh 配置；不合 main、不部署。覆盖 MF-P05/P06/P11/P13/P15/P16/P17/P18/P21。

## 用户结果与范围

已保存 M1 双钢琴 v4 可以调低/中/高频、总旁路、归零、恢复该保存版 EQ。仍是草稿→显式保存→显式生成保存版试听/导出；重开和 Undo 保持精确状态。原 Track、音符、来源、performance 及 M1 gain/pan/mute/solo 不因 EQ 改变。旧 v1–v4 声音不重解释。

本门只支持已启用 M1 的 v4/v5 双钢琴，v3 需先通过现有基础混音保存进入 v4。没有单段 enable、可拖频率/Q、实时音频、频谱分析、EQ自动化、额外效果或整页重排。两套配色未被选定，不能作为定稿。正式界面只显示参数计算的 EQ 响应，不接原型的合成频谱。

## 已核实的链与选择

已安装 Tone15.1.22 的 EQ3 用四个分频 biquad、三路增益/求和，默认 crossover400/2500Hz，与 v3 原型架式/峰值算法不同。三选一：继续 ToneEQ3 就必须另绘真实分频响应；替换为三个新滤波器会改变新版本旁路相对 M1 的声音；**保留 M1 链再串接三段**可以精确保留旁路与历史声音，采用第三种。

链：现有受审核钢琴→现有 ToneEQ3→新增静态 EQ→既有声像/音量→既有 master/limiter。只对可听轨建立滤波，最多每轨增加三个原生 BiquadFilterNode；总旁路或全0增益跳过新增节点，单个0增益段也可跳过。保留既有 limiter 行为，不引入隐形自动归一化；响应曲线仅描述新增三段的增减，提升可能增加输出电平。

既有 Chromium/Tone 的一次小样本 preflight：4秒合成信号、单浏览器、每模式5次（首冷+4暖），旧链暖中位35.85ms，新串接40.20ms，新增旁路35.30ms。四→七个 biquad（每轨），没有新依赖、音源、FFT、Worker或常驻循环；不是生产CPU/RSS/P95测量。六组±6dB实际PCM频响与 native getFrequencyResponse 差<0.02dB，全0与直接旁路精确相同。原始 results.json 在任务 eq-preflight 目录。

## 固定接口

- `PianoEqProfile`：schema `three-band-eq-profile.v1`、profile_id `motif-three-band-static.v1`；采样率48000，low shelf180Hz、mid peaking1000Hz/Q0.8、high shelf6000Hz，shelf S1。所有 profile 值为受验证 Literal，随新 render_profile 序列化并进入 graph；前端曲线与 DSP 消费同一 profile 数据。
- `PianoTrackEq`：track_id；schema `piano-eq.v1`、profile_id固定；bypass严格bool；low_gain_db/mid_gain_db/high_gain_db为严格有限数值，范围−12..12dB，默认0，bypass默认false。不得clamp或把字符串转换为数值。
- `PianoEqState`：schema `piano-eq-state.v1`，tracks精确覆盖两轨，无缺失/重复/额外ID。
- `ArrangementIRV5` 继承v4，保留 `piano_mix:piano-mix.v1`，新增required `piano_eq:PianoEqState`；`EqPianoRenderProfile` engine5且required固定eq_profile。`set_piano_eq` human-only L0，selection全两轨无ticks，payload `eq:PianoEqState|None`；非None仅v4→v5或v5修改，None仅v5→原v4。完整EQ snapshot保证多命令反序Undo，首次升级Undo恢复精确v4 hash。
- v5中 `set_piano_mix` 非None必须保留eq/profile5，None拒绝，需先显式退出EQ；混合批次Undo按逆序退出EQ再退出mix。局部语义改音符保留mix与eq；不支持的结构/profile写入明确拒绝。不能将human EQ授权暴露给Agent proposal。
- `audio-graph-spec.v5`/`motif-forge-audio-engine.v5`，canonical/candidate Job5；沿v4 audible/expectedSilence，top required `eqProfile`，每轨required `eq3`为该轨EQ设置（snake_case配置字段）。保留原有 track.eq 作为受保护旧链。TS严验profile/config/schema对应，Python Worker由权威Revision/Snapshot重编译并比对全graph/hash，静音许可不能由caller单独放宽。
- `ExportPlan v6`/`BundleArtifact v6`显式pin engine5/profile5，所有reader/rebuild/读模型支持；0029扩约束与历史downgrade guard（IR5/Job5/recipe5/Plan6/Bundle6/command）。不迁移用户库，仅自有隔离PG。
- v5新candidate recipe使用与有声/预期静音一致的规则标签和明确v5策略；旧v4 recipe不改写、不破坏已存hash（M1-R1仍保留原历史范围）。

## 共享数学与最小交互

新增纯TS模块 `packages/audio-engine/src/piano-eq.ts`，只依赖类型/数学，不能import Tone。导出profile类型、EQ类型、固定常量、`eqResponseDb(eq, profile, frequencyHz)`，`connectPianoEq(context, input, output, eq, profile)`；同一profile/系数定义驱动图与实际节点。曲线按20Hz–20kHz对数频率、dB响应，参数改变时计算，不常驻AudioContext/RAF。DSP用native Biquad；曲线RBJ公式在真实浏览器对native getFrequencyResponse核对。

Mixer内只增加选中轨的三段EQ小面板：三个旋钮/明确数值、总旁路、当前轨三段归零（gain0/bypassfalse）、恢复该保存版EQ。旁路保留gain，实线0dB、虚线保留设置；一手势只产一个草稿命令。数字非法/空值报具体错误并保持原值；键盘可用。不接未实现的单段开关、频率/Q或假频谱。沿现有保存、冲突、错误/重试和新Revision音频缺失状态，无滑杆自动Job。

## 证据与失败边界

先窄RED→GREEN：严格参数/权限/选轨、source不变、mix与EQ互不覆盖、多命令Undo与局部语义保留；TS profile/graph欺骗拒绝，旁路保留参数、零段跳过。至少一个成功Eval与一个失败标签。

真实音频：同一quiet多正弦输入覆盖三段boost/cut与多个频点，用独立PCM幅度/相位或频率响应比对公式；曲线误差≤0.05dB。生产共享compiler的钢琴fixture验证v5旁路/全0与M1 WAV最大1PCM24 LSB、有效EQ改变真实信号；保持全静音真0。相同Revision Preview/Canonical/MP3/Stem绑定同graph/hash，MP3仅按预声明有损容差，不能声称字节相同。

真实PG/builtUI至少一条：v4→EQ草稿→保存/重开→旁路/归零/保存→精确Undo→显式export，含非法HTTP head不动、旧音频不继承、请求幂等与持久Parent重复resume。既有v1–v4完整graph投影兼容；一次代表性历史5阻止降级。用真实时长/节点数/新增文件/渲染耗时报告成本，不拿测试个数当用户质量。

新资源/依赖/DSAPI调用预期0，累计既有4调用/7228tokens/公开峰价上界¥0.023852原账不变，累计预算≤10元仍保留。用户取消额度定时检查，不轮询。自有服务最后精确关闭，共享资源不动。最多一次fresh独立审查与一次作者修复/限定复核；若仍阻塞立即报告。

参考：前端v3原型（独立设计、未定配色）；[W3C Audio EQ Cookbook](https://www.w3.org/TR/audio-eq-cookbook/)（2021-06-08 Note，2026-10-19查阅）；[Web Audio BiquadFilterNode](https://www.w3.org/TR/webaudio/#BiquadFilterNode)（同日查阅）；已安装Tone源码 `EQ3.ts/MultibandSplit.ts/Filter.ts`。公式和原型不是生产声音验收。
