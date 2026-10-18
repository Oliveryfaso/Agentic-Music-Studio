# P1-A1：有界渲染容量修复

日期：2026-10-19，Asia/Shanghai。Stage P1-A1；MF-P02/P15/P16/P17/P18/P21。起点 e3d943844b77c177b93437abfe530c989989feee，工作区 clean，分支 codex/motif-p0-piano-preparation。用户已明确授权本次产品容量修复；P0/P1准备限定已被本次窄实现授权推进。

目标：五分钟 48k stereo PCM24 不再被固定 64MiB 错拒，同时拒绝无界/超资源请求；不改 v1 音乐/引擎/IR/Job schema、音色或尾音长度，不接 P1-A2/钢琴样本/付费模型/前端重写。

## 合同

- `render-capacity.v1`：ceil((score+explicit_tail)*sampleRate)×channels×bytesPerSample+44；现有 v1 explicit_tail=0，graph.durationSeconds 已是整个输出窗口。混响 decay 不等于追加尾长，不能为了预算改声音。
- 继续支持 bridge 16/24bit、44.1/48k、stereo；canonical 仍为48k24。总输出窗口最多300s、12轨、最多20,000事件；预计裸媒体缓冲（float32+两份编码WAV）最多320MiB；输出硬上限96MiB。该缓冲预算不是OS RSS保证，实际RSS另测。
- 新 producer 输出 cap=max(1MiB,精确WAV上界)，保留旧序列化/legacy overprovisioned预算字段范围；执行前下调有效sink上限到推导值，低于必需WAV的旧预算明确报错，不能自动扩预算。
- StoragePressureGate 对 artifact/temp 分别估算相同输出上界，覆盖temp写入+提升到最终目录的同时两份磁盘占用；client在请求前复核实际两个root余量，保留minimum-free硬边界。配额仍由现有权威gate执行，不新增模型决策。
- 超容量/资源非重试拒绝；磁盘不足阻断DSP，Worker沿用既有存储路由，client临时余量复核失败则结束本次尝试。超时/断连保持原有可重试分类；cancel保留CancelledError，清理本job的render.wav/.partial，不删除别的job或最终原件。

## 步骤与验证

1. RED：新增producer短/30/72/300秒精确预算及candidate PCM中间件测试，先在旧代码看到64MiB断言失败。Expected：5个预算测试失败，v1语义测试通过。
2. RED→GREEN：pure容量估算/超时长/非有限数/格式/显式尾音/事件/缓冲拒绝；Python/TS共享字面量边界用例；新builder使用估算，Worker gate复用推导值。不得先抬高常量。
3. RED→GREEN：client预算不足、磁盘不足、service error、invalid receipt、oversize临时文件、取消和清理；受控HTTP/本地文件，模型不参与。stream hash/header避免校验时整WAV副本。
4. RED→GREEN：TS request preflight clamp/拒绝/并发串行与sink超限清理；保留原v1 bridge。只改容量相关接线，不重构默认Colima stopper。
5. GREEN：聚焦Python application/audio/storage/worker测试与完整 audio TS suite；TypeScript build/Mypy/Ruff，风险触及的组合unit回归。DB未修改，不为该无DB边界启动共享VM。
6. 真实integration：独立headless/临时loopback，串行执行300秒代表谱，通过production HTTP render service与Python adapter验证/原子promote；FFprobe、hash、精确bytes、峰值/资源采样、临时文件清理。另跑低预算/超时/取消小用例。独立profile、不接用户浏览器、无需Docker/DB/模型。仅本任务进程RSS；峰值采样和物理RSS边界分开报告。
7. 更新状态/技术记录/本轮证据；一次独立审查；本地checkpoint不推送。保留本轮有效基线，清理仅本任务scratch，不停止/改变共享VM。

## 账本

- Pre-flight：producer cap→Worker quota→HTTP sink→adapter promotion 共用同一推导输出上界；v1 schema/声音不变，不能用 MP3 最终大小估算 PCM。
- Ruling：本轮仅做容量A1，不并行执行A2动态导出、VM stopper或钢琴资产。其成本是单琴完整Bundle仍待A2，真实音色仍待许可/预算准备。
- Ruling：保留 v1 零额外尾音，不把 reverbDecay 追加到 300 秒外。其成本是本次不解决现有尾音截断，后续表现力版本需显式合同。


## 执行结果

2026-10-19：步骤1–7完成当前host边界，见[实测/回归报告](../../evidence/2026-10-19-p1a-render-capacity.md)。API unit552、音频TS30、tsc/Mypy/Ruff通过；一次独立审查与一次修复复审关闭当前路径阻塞。真实300秒WAV及低预算/超时/取消通过。容量相关恢复修复额外覆盖重叠body单槽、timeout teardown竞态、建页取消丢失。DB/UI/pinned Docker/12轨最坏负载/完整Bundle/钢琴不计入已验。磁盘/临时与cache清理证据在报告收尾账本；仅本地提交不推送。
