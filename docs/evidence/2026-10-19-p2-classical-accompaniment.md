# P2.1 经典谱导入与新增伴奏验收

Stage P2.1；MF-P01/P02/P05/P06/P08/P10/P11/P13/P15/P16/P17/P18/P20/P21。BASE/Guide `d3ff8b0f91670df400de7d814e02a3849b8ea4d7`，开始和初审时Guide clean；收尾仅更新顶部实际阶段说明，不改批准架构。用户已在本任务直接授权P2小切片及测试/独立审查后正常推开发分支，不合main、不部署；最初研究-only权限误判已由直接授权解除，不是当前阻塞。

## 用户实际得到的流程

Home“查看经典谱”先读来源与转换、勾选后导入。Mutopia528《欢乐颂》固定16小节/62notes soprano旋律转单声部无歌词MusicXML；原SATB其余3声部、bar10/11两处slur明确省略。原文件/转换文件hash、来源、Public Domain、数字编辑与转换说明均随资源固定，并进入导出credits/license/provenance。原谱全时段锁定，原Revision/分支保留，改编使用工作分支。

用户选择逐小节和弦(G/C/D/Em/Am/Bm)、根音/分解织体、八度2/3和力度32–80，新增同一审核小钢琴包的独立低音声部。复用同一Parent的有限Worker等待与两版真实MP3；显式试听并绑定candidate hash保留/放弃，保存、重开、Undo、canonical导出继续使用不可变Revision与既有读模型。原谱导入Project/root/Revision/两branch/active指针/audit/receipt在一个事务中提交；失败全部回滚，原key重试仅创建1份。

## 新旧合同

旧IR/Graph/engine/Job v1/v2不放宽。新`arrangement-ir.v3`、`audio-graph-spec.v3`、engine/Job v3最多两条同包钢琴；`render-profile.v1`以明确engine.v3分流；Plan/Bundle v4及0026 SQL检查/危险降级guard。Append/remove是明确L2命令；Undo仍限当前head的精确parent，没有任意快照覆盖权限。前端DTO由OpenAPI生成，未增加付费调用/依赖/语言/音源包。

## 实际运行与测试

真实新建临时PG、built Web、loopback API和共享Chromium编译器：导入→伴奏请求→刷新→两次真实试听→同位置A/B真实播放→错误hash409→人工保留→重开播放/390px无溢出→Master+Bundle→8个文件下载bytes/SHA→Undo原hash/原谱播放→新试听刷新后取消。4Jobs，两个preview/一个canonicalMaster/一个bundle；每次Worker后重新创建应用，生产Outbox Publisher重复事件仍安全。项目AI Run与模型调用0。

导出完成后最初的读取遗漏v4分支曾返回500；已用窄测RED→GREEN修复，重启应用后从同一持久结果完成下载与Undo，没有重复渲染。不是全无故障的首次演示。

作者最终Python unit/Eval+仓库合同679 passed；Web96、Audio/Worker61、两个宿主build、Mypy127源、Ruff/diff通过。真实PG相关共4项：旧v2两项、新谱版本读/分支/重放/Undo/降级guard一项、后半导入失败回滚/精确重试一项。初审1Important经一次作者修复关闭：PG RED五表均+1空项目残留，GREEN五表count不变、同key重试重放仅1project/2revisions/2branches；相关7 passed。修复后再跑Python679/类型/lint/diff；未重复未改的Web/Audio或整条实际音频链。一次fresh初审及一次限定修复复核，无剩余阻塞，原始报告附后。

日志在任务workspace `research/p2-runtime-2026-10-19/checkpoint-*.txt`、原子回滚RED `1792395881299598000.txt`、GREEN `1792395934551183000.txt`。独立审查另跑21项窄测。复现实验使用显式新建一次性DSN，不读取项目.env；正式回归见`services/api/tests/integration/test_postgres_classical.py`。旧DSN locators已关闭，不能直接重跑工作区临时启动器。

## 声音和资源

Master40.79998s、48k stereo PCM24、11,750,438bytes，SHA256 `1d5cf66073ba7ecb31ee5515441bcd59d49b63815fca45c16b779d06be3c7811`；样本peak−13.18dBFS、满幅0。两预览平均RMS差0.455dB，交付试听HTML只在播放器衰减B、不重新编码或改母版；不是LUFS/感知响度或偏好测试。WAV比旧30秒示例大，原因是时长，未增采样率/位深。

延用26文件小包，本曲10个zone；manifest推导48k浮点解码11,173,160bytes，非RSS。每次render共享已核验buffer，交叉zone窄测证明单fetch/decode；本曲两个音区没有共享zone，不宣称实曲解码减半。Worker+恢复wall约2.223/2.641/2.479/0.183s，单次宿主测量，非稳定性能分布/生产上限。

前期保真度审计未发现已证实削波/混叠/loop/单位转换缺陷；没有基于猜测改旧音色。单有效力度层、无踏板与release-trigger、简单包络仍是声音边界。本轮不证明审美质量提升。

## 清理与边界

冻结Master/试听/MIDI/项目/许可/源谱与证据，inventory后仅移除自有PG/tmpfs数据/生成凭据和可重建renderer启动器/空log，重新校验保留文件。无partial、无本任务常驻服务、未动共享Colima/历史容器/数据库卷/混合BuildKit缓存；宿主验证无Dockerfile/系统依赖/锁变化，不作无消费者的镜像重建。存储明细见附件。用户库未迁移。

只提供一首审核旋律谱和两条同包钢琴，不是全部P2、任意上传/复杂MusicXML/MXL、自然语言编曲、真实贝斯/弦乐或两首古典/室内乐验收。未复验Redis/Celery传输、Compose、主机掉电持久性、长负载/P95/RSS、踏板/更大音源或音乐质量。开发分支提交/远端SHA另由最终交付记录核对，不合main/不部署。

## 原始证据

- [实际浏览器/PG链](2026-10-19-p2-browser.json)、[音频/资源](2026-10-19-p2-audio.json)、[checkpoint](2026-10-19-p2-checkpoint.json)、[存储](2026-10-19-p2-storage.json)
- [初审](2026-10-19-p2-review.md)、[独立复现](2026-10-19-p2-review-atomic-repro.json)、[一次修复复核](2026-10-19-p2-repair-review.md)
- [Mutopia谱源](https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=528)、[原LilyPond](https://www.mutopiaproject.org/ftp/BeethovenLv/ode/ode.ly)、[许可](https://www.mutopiaproject.org/legal.html)，2026-10-19核验；source date2009-08-05。
