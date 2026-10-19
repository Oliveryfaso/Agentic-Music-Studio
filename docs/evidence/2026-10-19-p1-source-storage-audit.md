# Motif Forge 音源许可核验与 Colima 只读根因

2026-10-19；Stage P1支持资源核查；MF-P05/P10/P15/P16/P17/P18/P21。手动模型设置保持不变，无付费、安装、公开push或发布。本轮没有产品代码、数据库或音频接线修改。

**Colima的直接阻塞已定位到真实只读卷，之前仅归因执行环境权限不准确。小钢琴包的许可和SFZ文本已使用现有工具核验，但WAV仍未解压，真实钢琴未准入。**

## Colima为什么在用户终端也失败

真实路径链：`~/.colima/_lima` → `/Volumes/UnityWorkspace/ColimaVM/lima` → `colima/lima.yaml`。`.colima`本身是内置Data卷普通目录，真正指向外部的是`_lima`符号链接。

| 证据 | 实测 |
|---|---|
| mount与statvfs | `/Volumes/UnityWorkspace`实际为APFS read-only |
| diskutil info | Writable=false，APFSSnapshot=false，BusProtocol=Disk Image |
| hdiutil info | 映像`/Volumes/KINGSTON/idea/.tools/UnityWorkspace.sparsebundle`已附加，writeable=false |
| 底层KINGSTON | ExFAT，Writable=true；不是整块外置盘只读 |
| VM目录/文件 | UID501与当前用户一致；lima.yaml为rw-r--r--，相关目录/文件flags=0 |
| 可用空间 | UnityWorkspace约44.9GB；KINGSTON约127.6GB，不是空间耗尽 |
| 当前运行 | Colima仍Stopped；本轮未再次启动、改挂载或修改配置 |

这足以解释同一文件在用户终端和Agent工具里都报EROFS。它不证明用户权限有错，也不证明磁盘损坏。**为什么该映像最初以只读方式附加，尚未确定**；不能把“显式只读附加”“系统回退”或“文件系统故障”任意一个说成已证实。hdiutil imageinfo只确认UDSB sparsebundle格式，不能据此推断数据完整性。

本轮针对该卷的lsof仅请求PID/进程名，未列出可见使用者；这不能担保其他任务没有依赖该卷。没有读取Lima配置内容、密钥或无关私人文件。

### 最小修复方案，尚未执行

先确认UnityWorkspace上的编辑器/其他任务均已释放，再**普通弹出同一个磁盘映像，并正常以读写方式重新附加**，保持既有路径、VM数据与配置。只针对这一个映像；不使用force、不删VM、不重置配置、不chmod/chflags、不禁用验证或安全机制。普通弹出被占用或读写附加失败时就停止，先看实际错误，不强制修复。

拟议命令（尚未执行，须先确认共享卷可短暂离线）：`hdiutil detach /Volumes/UnityWorkspace`，随后`hdiutil attach -readwrite -mountpoint /Volumes/UnityWorkspace "/Volumes/KINGSTON/idea/.tools/UnityWorkspace.sparsebundle"`。再以`diskutil info -plist /Volumes/UnityWorkspace`核对Writable=true。正常detach若报告busy或attach报错就停止，不加-force，不执行强制mount -uw。

这一动作会短暂卸载整个共享UnityWorkspace，不仅是Colima。因此本轮只提出具体方案，等待明确确认共享卷可短暂离线；不会要求用户再机械重跑尚无意义的Colima启动命令。完成后应先验证diskutil Writable=true、挂载不再read-only，再尝试一次保留配置的Colima启动和缓存镜像核查。镜像仍不自动下载。

## 小型钢琴包实际核验到哪里

复用已隔离的FreePats KW small SFZ WAV归档，4,551,289 bytes，SHA256=`ffb547fceb91eeb93d78cf8d220d1d5f726dcac891afc15e517805ac48abb39d`；没有为“下载完成”重复下载同一文件。用户此次音源下载批准已记录。[官方音源页](https://freepats.zenvoid.org/Piano/acoustic-grand-piano.html)声明该音源采用CC0；包内2019-07-03 readme同样声明CC0，内附完整CC0 1.0文本。许可声明与包内文本核验已完成；真实WAV内容审计仍独立进行。

此前普通bsdtar读取报错时，文本已输出但后续扫描又遇到不支持的过滤器。现改用系统已有`/usr/bin/bsdtar -xqOf`，读到选定成员后停止扫描：

| 包内成员 | bytes | 退出码 | 状态 |
|---|---|---|---|
| SFZ | 2,641 | 0 | 完整文本与SHA已保存 |
| cc0.txt | 7,048 | 0 | 完整文本与SHA已保存 |
| readme.txt | 896 | 0 | 完整文本与SHA已保存 |
| A3vH.wav探针 | 0输出／应373,678 | 1 | Unsupported filter 3 for 40202 |

系统bsdtar3.5.3与已经安装的Anaconda bsdtar3.7.7均不能读取该WAV；未安装或运行新工具。已有Conda环境无py7zr；没有通过安装依赖绕开待批准工具。官方同名.tar.xz与.zip两条候选HEAD为404，这只描述这两个URL，不能断言不存在其他格式。

SFZ实际声明26个region、26个样本路径，MIDI21–108覆盖连续且无重叠，root落在各自key range；12个loop_continuous、14个no_loop，ampeg_release=0.6。未声明lovel/hivel或速度分组，不能把大包的“两力度层”描述移植到这个小包。这里只有文本映射得到验证；尚无WAV采样率、声道、位深、frame count或逐样本SHA。原始loop_start/end保留为SFZ整数，未擅自转换成内部exclusive-end manifest。

仍需兼容解压能力才能继续WAV核验。此前提议的官方7-Zip26.04 macOS归档1,861,928 bytes，**仍未获明确工具运行批准，未下载/安装/执行**。音源批准没有被扩展成任意软件安装许可。即使未来解压成功，也要先完成逐WAV格式/hash/frames与loop验证，再审查manifest；当前没有新钢琴播放、render或音质结论。

## 复查与项目状态

本轮审计脚本和原始JSON保存在本任务research目录。`audit_selected_piano_text.py`复查三个文本成员、SFZ覆盖/路径/字段及明确失败的WAV；`record_colima_root_cause.py`仅采集相关路径元数据和卷信息，不改变挂载。包内文本与WAV失败输出分开记录，不把失败当成功。

A2.1已验的内部合同不变；A2.2/B仍等真正可运行的隔离PG。旧作品、声音、Artifact、数据库和共享卷均未改；7-Zip和共享卷操作分别保留明确批准边界。


## 独立证据审查

一次只读审查通过，无未关闭Critical/Important；独立复算归档与三文本bytes/SHA、SFZ区域/覆盖/loop/release，均与原始JSON一致。旧Status“文本尚未读取”的残留已修正并复核。Guide相对起点无diff，未为文档变化运行无关产品全suite。尚未证明的边界保持列明，不把文本核验当成音源准入。
