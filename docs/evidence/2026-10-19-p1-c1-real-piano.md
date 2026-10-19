# P1-C1：真实钢琴边界与资源解阻

2026-10-19；MF-P02/P05/P10/P15/P16/P17/P18/P21。真实小型钢琴已经通过“审核包→本机 catalog→共享适配器→WAV”的内部边界，用户作品仍走原来的 v1 路径。下一生产任务是 A2.2 接线与 B 持久音乐 v2；这次没有证明新音色在界面中保存、Undo 或完整导出。

## 可听文件与实际结果

同一份自制 64 音符、30 秒短谱，串行生成旧 warm pad、真实钢琴机械版、真实钢琴表达版和旧声音回退版。表达仅覆盖力度、起点与时值，原谱内容未改。四份文件均为 48 kHz、双声道、PCM24、8,640,044 bytes，最后两秒全零。

| 项目 | 实测 |
|---|---|
| 审核/解码 | 26 个源样本；源 WAV 全为 44.1 kHz、mono、PCM16；解码到 48 kHz 共 20,575,408 bytes |
| 载入解码 | 214 ms |
| 渲染并写文件 | 旧声音 1854 ms；机械钢琴 808 ms；表达钢琴 805 ms；回退 1822 ms |
| 同标尺 | 全曲 RMS 目标 0.04；不是 LUFS 或感知响度匹配 |
| 独立文件检查 | SHA/头/时长通过；peak 0.189–0.303；旧声音与回退最大差 1 LSB |
| 声音差异 | 旧声音/钢琴差值 RMS 0.0568；机械/表达差值 RMS 0.0286，只证明波形不同 |
| 资源 | 200 ms 采样本任务进程树 RSS 最大 1,246,576,640 bytes，约 1.16 GiB；3 GiB 保护未触发 |

这是宿主 Chromium 151.0.7922.34 的一次受控测量，不能当作生产延迟分布或内存硬上限。RSS 求和可能重复共享页，不含 Colima/PG/其他服务；与历史五分钟 A1 的约 2.15 GiB 不是等条件比较。没有播放扬声器或进行人耳盲听，因此不宣称琴声自然、表达更好或音乐审美过关。

## 音源、许可和权限边界

来源为 [FreePats KW small 原始归档](https://freepats.zenvoid.org/Piano/UprightPianoKW/UprightPianoKW-small-SFZ-20190703.7z)，4,551,289 bytes，归档 SHA256 `ffb547fceb91eeb93d78cf8d220d1d5f726dcac891afc15e517805ac48abb39d`。包内 CC0 文本、readme、SFZ 和全部 WAV 实际读取校验；26 region 覆盖 MIDI 21–108，无声明的速度分层。12 个连续循环按 [SFZ loop_end 的 inclusive 语义](https://sfzformat.com/opcodes/loop_end/) 转为内部 exclusive end+1，并核对实际帧范围（访问 2026-10-19）。

Manifest SHA256 `264fdbf12f3c7273a0d15fbcb86abed04b73e08b6fc4faf482eaf41040a0b813`，固定 pack/version/adapter、CC0 文本 hash、每个样本 hash/格式/帧数/键区/循环。限制仍为 32 voices、2,000 notes、30 秒 gate、2 秒以内 release；当前包 release 0.6 秒。踏板和 release-trigger 明确不支持。

新增 loader 只接受受信配置提供的 root+manifest pin，拒绝符号链接、越界、hash/许可证/PCM 不符。HTTP 只接受已注册随机 nonce 与 sampleId，缺包或未知 ID 返回 404，不把 URL 当文件路径，不下载模型给出的地址。原始音源只留在忽略的 Artifact 目录，未提交 Git。

## 资源操作已完成

用户明确批准后，对同一个 UnityWorkspace sparsebundle 普通 detach，再 readwrite attach；两步退出 0，Writable=true。没有 force、改权限、删除 VM 或改配置。官方 [7-Zip 26.04 macOS 归档](https://github.com/ip7z/7zip/releases/tag/26.04) 仅下载运行于任务 tools 目录，1,861,928 bytes，SHA256 `bee04358cbcbc7106273cee0e8d72916db2696c48067a3538c34d8cd6fd16578` 与发布方 asset digest 一致；没有全局安装或改 PATH。

原配置 Colima 已成功运行。复用缓存 PostgreSQL 镜像、pull=never、localhost 随机端口，创建带任务标签的专用临时库。原来 skipped 的两个导出集成真实通过：pytest 1.18 秒、含启动的进程总计 2.36 秒；迁移头 `20260824_0021`。本轮只读核验迁移后 30 张 app 表、选定表 38 个约束和 18 个索引。tmpfs 只证明真实 PostgreSQL 事务边界，未检验容器重建或宿主掉电持久性。

收尾已停止并删除唯一自有 PG 容器及自生成凭据目录，未连接旧库。Colima 保持运行：daemon 启动时历史服务自动恢复，任务未对这 10 个运行/重启中的历史容器做启停。Docker context 仍为 default。只删除本任务旧探针和重复解压目录，回收 44,824,612 logical bytes；保留最终四份 WAV、审核源、源归档及工具，未清共享缓存/镜像/Volume。

## 验证与未完成部分

新增 catalog 测试先 RED 后 GREEN；独立审查发现启动期间 RSS 超限会遗漏浏览器关闭，已用真实 deferred Promise 生命周期回归修复。唯一一次修复复核通过，catalog/runtime 13 通过；最终共享音频/Worker 55 通过、TypeScript、宿主打包、脚本语法通过。没有为纯文档重跑 Python 全套或旧 Compose。

失败探针采用诊断保留策略：某个后续 variant 失败时，已经写完的 WAV 可以留在该次新目录；cancelSink 不负责删除已成功 201 的文件，精确 hygiene 处理这些目录。当前 accepted 目录 partial 为 0。

生产 v2 IR/Commands/Undo、Parent/Outbox/Worker 动态导出、API/UI、render profile 身份与迁移 guard 仍待实施；当前“回退”只是同一探针再次渲染旧声音，不是持久 Undo。没有调用付费模型、下载大样本、push 或发布。Guide 历史提交 e3d9438，任务起点 HEAD 6099fca，Guide 前后无 diff。


## 可复查附件

- [结构化运行/源/PG/schema/hygiene 证据](2026-10-19-p1-c1-real-piano.json)
- [表达钢琴 WAV](../../artifacts/piano-real/2026-10-19-accepted/piano-expression.wav)
- [机械钢琴 WAV](../../artifacts/piano-real/2026-10-19-accepted/piano-mechanical.wav)
- [旧声音 WAV](../../artifacts/piano-real/2026-10-19-accepted/legacy.wav)
- [回退 WAV](../../artifacts/piano-real/2026-10-19-accepted/rollback.wav)
- [本纵切计划](../superpowers/plans/2026-10-19-p1-c1-real-piano-boundary.md)
