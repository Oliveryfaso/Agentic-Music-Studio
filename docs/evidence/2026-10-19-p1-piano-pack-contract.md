# P1 钢琴包合同与播放适配准备

2026-10-19，Asia/Shanghai。Stage P1 包合同子门；MF-P02/P05/P10/P15/P16/P17/P18/P21。起点823c4e7；本轮保持手动模型设置，provider requests/tokens=0/0。

本轮完成的是可复用的包校验和播放适配准备。真实KW小包已固定来源、大小、hash并隔离保存，但现有工具不能读取其压缩member，包内许可和SFZ映射还没核实。因此没有接入真实钢琴、没有发布可用pack manifest，也没有改旧引擎或用户作品。

## 小包已经确认和仍未知的部分

[FreePats官方条目](https://freepats.zenvoid.org/Piano/acoustic-grand-piano.html)将小型SFZ WAV标为4.3MiB下载/10MiB展开，页面说明CC0；两力度层描述属于大包，不能直接套用到小包。选择WAV版是为了继续使用现有浏览器PCM路径，无需新增音频解码软件。核查日期2026-10-19。

| 项目 | 本次证据 |
|---|---|
| 精确来源 | [UprightPianoKW-small-SFZ-20190703.7z](https://freepats.zenvoid.org/Piano/UprightPianoKW/UprightPianoKW-small-SFZ-20190703.7z) |
| 实际下载 | 4,551,289 bytes；下载硬限5MiB，未取得大包 |
| SHA256 | ffb547fceb91eeb93d78cf8d220d1d5f726dcac891afc15e517805ac48abb39d |
| 目录 | 30个普通文件，其中26个WAV；无绝对路径或..条目；未执行包内文件 |
| 声明展开 | 总10,509,268 bytes；WAV共9,452,994 bytes；此为归档目录值，未解码核实 |
| 文本成员 | SFZ 2,641 bytes；cc0.txt 7,048 bytes；readme 896 bytes，尚未读取内容 |
| 日期 | 文件名20190703；页面标题2022-02-21；HTTP Last-Modified 2022-02-26，三者分别记录 |
| 未知 | 小包真实力度层、SFZ root/key/velocity zones、WAV格式/frames/loop以及逐文件许可范围 |

系统现有bsdtar/libarchive3.5.3可以列目录，但读SFZ时报`Unsupported filter 3 for 40202`；本地没有7z/7zz/py7zr。没有把文件名中的音名或vH当作已验证root/层数。包内CC0文本未读，官方页面声明目前仅是候选来源依据。[CC0官方说明](https://creativecommons.org/publicdomain/zero/1.0/)用于解释许可名称，不能替代该包的具体出处核查。

## 已实现并验证

新增`instrument-pack.v1`与`multisample-buffer-source.v1`适配标识，限定pack/version、来源archive hash、许可文本hash、本地WAV路径、样本hash/字节/格式/frames、rootMidi、键区/力度区、显式loop与release。**合同校验通过不等于许可审批通过**；真实应用接入时仍必须来自审核catalog，并把manifest hash绑定v2 Revision/profile/recipe。

- 校验相对路径、hash/size和PCM RIFF元数据；拒绝不支持版本、区间重叠、缺样本、错误hash和越界loop。
- 音高以rootMidi计算`2^((midi-root+cents/100)/12)`；力度区用闭区间选择，velocity 63/64边界有测试，增益为velocity/127。
- 普通note-off用独立voice envelope和有限release；同音重击互不共用stop句柄。规划与实际调度两端都核查复音和释放硬界。
- 本子门不支持踏板、半踏、物理共鸣或release-trigger样本。pedal events抛`PIANO_PEDAL_UNSUPPORTED`，release-trigger能力抛`PIANO_RELEASE_TRIGGER_UNSUPPORTED`，不静默忽略。
- 硬界：最多64样本/区域、单样本4MiB、编码总16MiB、48k目标预计解码64MiB、32复音、2000音符、单gate<=30秒、release<=2秒。异步加载/审核catalog、SFZ转换与voice stealing仍未实现；超复音直接拒绝。

适配函数消费调用者已校验并decode的AudioBuffer，可用于将来共享Tone raw context；本轮仅测试/probe调用。v1 compiler、AudioGraph/Engine/Job版本和aliases不改，未允许新pack从现有v1入口直接播放。没有持久结构变化或DB迁移。

## 实际离线工程验证

使用现有自制builtin click，独立Chromium151.0.7922.34、file页面、阻断HTTP/HTTPS、OfflineAudioContext，串行渲染5份0.3秒波形；没有扬声器播放。该声音是测试信号，绝非钢琴录音或音质验收。

| 检查 | 结果 |
|---|---|
| 根音/升八度 | 短窗口过零估计1751.8Hz/3553.7Hz，频率比约2.03；不是高精度频谱测量 |
| 力度32→64 | 同一PCM信号能量比4.0 |
| note-off之后 | 约定stop之后窗口能量0 |
| 重击 | 后一voice在旧voice释放后仍有能量0.0164630 |
| 最后释放 | 所有voice stop之后窗口能量0 |

本轮音频TS suite 48 passed（新增18，原有30）；tsc noEmit和宿主render bundle构建通过。先记录缺API、缺scheduler、调度复音、释放时间修改及release-trigger标签的RED，再GREEN。Python未改，未重跑数据库/API suite。

P1-A1五分钟的2.15GiB是本任务进程树RSS采样，可能重复计共享页；320MiB是声明的裸媒体缓冲预算，二者不可混同。本轮短probe没有另测RSS，更没有证明真实钢琴解码常驻或12轨最大负载。

## 继续真实包核查所需条件

已查到[7-Zip官方macOS console 26.04](https://www.7-zip.org/download.html)的[具体归档](https://github.com/ip7z/7zip/releases/download/26.04/7z2604-mac.tar.xz)，HEAD体积1,861,928 bytes（约1.78MiB）；**未下载、安装或运行**。用途仅为从已隔离小包读上述约10.6KiB文本，再按明确清单审查WAV。GitHub API当时403限流，未取得published digest，未编造摘要。

继续需要明确允许下载并运行该新解压器，限定本任务隔离工具目录、下载上界2MiB、展开预算10MiB、不改全局PATH或依赖；也可提供现有兼容解压器路径。之后先核实包内许可证、SFZ未知opcode和逐WAV格式/loop，再产生可审查manifest；不得直接放行音源。无需付费API、大库或共享VM。

本轮只是P1准备子门。A2动态完整导出、B持久v2双读/迁移/Undo、生产HTTP按审核pack ID取样本、真实钢琴30秒A/B与人耳判断仍待完成。


## 独立审查与一次修复

只读审查发现Important：1秒起点、5ms gate在调度器相减后变成0.004999999999999893，被误拒。新增回归先RED，再改为比较绝对release时间与start+边界，GREEN。审查另报探针NaN可绕过比值判断为Minor；本轮重评为影响验收可信度，纳入同一次修复：共享验收helper检查明确数值字段为有限正频率/能量比，补静音和NaN回归。最终浏览器重跑又复现描述fixture字符串被Object.values误判，修正为命名数值字段并补RED→GREEN。代码不因此扩展到真实音源准入。

## 存储与恢复点

仅保留最终accepted短probe、P0/P1-A1基线及本任务workspace的隔离小包/审计元数据，删除本轮四份过期probe构建。没有删除用户作品、原始录音、数据库卷或共享缓存。见[清理账本](2026-10-19-p1-piano-pack-storage.json)。清理后重跑音频suite、类型检查并核对保留JSON；真实包仍未解包准入。
