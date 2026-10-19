# Motif Forge M1 基础混音验收

2026-10-19。基础混音第一阶段通过验收；一次 fresh 独立审查无 Critical 或当前路径 Important。开发分支交接由 Git 提交与任务本地推送回执记录。

现在可以对已保存的双钢琴版本调整音量、声像、静音和独奏，再保存为新版本。原谱音符、片段、来源与原 Track 不变；重开恢复混音值，撤回恢复精确的父版本。播放明确使用保存版，草稿调整后需要保存并显式生成新版试听/导出。

覆盖 MF-P05/P06/P11/P13/P15/P16/P17/P18/P21。只完成双钢琴基础混音第一阶段，不提供实时调参、EQ、混响或 master 编辑。新的配色与专业调音台原型另行研究；不会把模拟 EQ 发布为真实音频功能。

## 实测结论

| 检查 | 最终证据 |
|---|---|
| 保存、重开、reset、Undo | built UI 操作通过；reset 回到当前保存值；Undo 的权威 hash 与原 v3 相同，完整 IR 相同 |
| 音量 | −12→−18 dB，实际 RMS 变化 −5.9999994 dB |
| 静音与独奏 | 单独奏与静音另一轨的 PCM 在 1 个 PCM24 LSB 容差内一致；多个独奏保留两轨；静音优先 |
| 声像 | 最左时右声道为 0，最右时左声道为 0 |
| 全静音 | canonical WAV、被排除的 Stem 为真实零 PCM；静音 MP3 正常完成并可解码 |
| 试听与导出 | Candidate Preview、同版 Master/MP3、Stem 共用同一 graph/hash；MP3 有损，不要求与 WAV 字节相同 |
| 版本绑定 | 新混音版本不会继承旧版本 MP3；导出工程携带 piano_mix，原 Track 与来源保持一致 |
| 请求边界 | 超界 gain/pan、字符串布尔拒绝，Branch head 不动；显式保存前无服务端保存请求 |

以上为内部两小节、4 秒、两轨固定信号样本。另有真实 PostgreSQL 集成测试从已审核经典谱导入、人工伴奏和保留开始，覆盖 JSONB 保存、重开、多命令幂等、精确 Undo 与历史降级 guard。短样本不代表整曲保真度、主观音乐质量、长期负载或所有恢复排列。

## 检查记录

- API unit/Eval 758 项、root 34 项，共 792 项；Mypy 133 个源文件、Ruff 和 diff 检查通过。
- Web 109 项（单 worker）、Audio/Render Worker 77 项；两个宿主 build 通过。
- 本阶段新增真实 PostgreSQL 集成 1 项通过。真实 built UI、生产 Worker 与 Parent export 共 19 个 Job，保存了 17 份实际音频的信号指标。
- 默认并行 Web 回归曾有 2 个既有异步等待超时；原日志保留，未修改断言或测试超时。随后完整单 worker 109 项通过，不据此宣称并行问题已解决。
- Preview MP3 相对 canonical RMS 差 −0.44608 dB，Export MP3 差 −0.00078 dB，均在预先声明的 0.5 dB 容差内。不是 LUFS、true-peak 或审美评测。

## 发现过的问题

真实 HTTP 负例发现旧公共解析入口使用宽松类型转换，曾将 `mute: "false"` 接受为布尔。已仅对新 `set_piano_mix` 路径启用严格 JSON 校验，保留旧命令兼容性。新增 13 项先 RED 再 GREEN，最终真实 HTTP 负例复验通过；首次失败记录仍保留。

前两类 probe 失败属于测试自身：reset 的 React 更新需要等待可观察状态；Studio 读模型没有 content_hash，应读取 Undo 响应中的权威 hash。两者未通过修改产品或放宽音乐断言处理。曾提出的 JSON 键顺序假设不成立，失败说明已更正。

## 费用与交付边界

M1 模型调用为 0，既有付费账本保持不变。本轮此前 P2.2 累计 4 调用、7228 tokens，按公开峰值费率计算的保守上界为 ¥0.023852；没有查询账户实际扣款。

Library 支持的批量上传助手报告 prepare_uploads 不可用。没有可确认的 Library ID，已停止重试，保留 P2.2 验收文档、四段 40.8 秒 MP3 和本地 ZIP。不能将本地文件冒称 Library 已保存。

未修改用户数据库；未新装依赖或音源；未合并 main 或部署。真实验证使用本任务隔离 PostgreSQL 和现有 Chromium/FFmpeg，未验 Redis/Celery 传输、Compose 重启、主机掉电或生产容量。

仓库证据：[浏览器](2026-10-19-m1-browser.json)、[音频指标](2026-10-19-m1-audio-metrics.json)、[独立审查](2026-10-19-m1-review.md)、[存储关闭](2026-10-19-m1-storage.json)。完整原始日志、音频与本地交付归档由任务保存。

## 独立审查与阶段关闭

独立 63 项聚焦离线测试通过；另复核 31 文件 SHA、13 份 PCM24、旧 v1/v2/v3 相对 BASE 的完整 graph，以及 v4 有声/静音重建 payload 的版本与 hash。不是作者重复自证，也不是重新执行整仓或真实数据库重建。

延后 M1-R1（Minor）：合法静音 v4 Candidate Preview 的 recipe 仍标注 non-silence.v1，policy 标签也沿旧名。当前执行不消费这串规则标签，authoritative graph 静音门及离线重建均通过；后续消费 validation_rules、升级 Inspector 或公开发布前，修正新配方标签并保留旧 recipe hash 兼容。此问题未被隐去或降为已修复。

自有 PostgreSQL/tmpfs 和生成凭据已移除，保留产物 36 文件重新核 SHA；共享容器身份集合不变，没有 prune 共享 Builder。精确回收自有 launcher 43,632 logical bytes、两份本任务 Mypy cache 43,352,658 bytes，共 43,396,290 bytes；不把文件逻辑回收量当作 Docker 稀疏盘实际压缩量。最终音频、失败反例、已审来源与构建产物保留。
