# P1-A1 五分钟渲染容量验收

2026-10-19，Asia/Shanghai。Stage P1-A1；MF-P02/P15/P16/P17/P18/P21。起点 e3d943844b77c177b93437abfe530c989989feee；本轮只实现输出容量与直接相关的错误恢复。

五分钟、3轨、880事件的代表谱通过了生产 HTTP 服务、Chromium executor、Python 客户端校验和原子提升，得到300秒48kHz stereo PCM24 WAV。64MiB固定上限冲突已修复；单琴完整Bundle、v2钢琴与表达尚未实施。

## 实际结果

| 项目 | 结果 |
|---|---|
| 输出 | 86,400,044 bytes；FFprobe确认300.000000s、pcm_s24le、48kHz、2ch、24bit |
| 渲染加校验提升延迟 | 40.776秒；一次宿主机样本，不是P95 |
| WAV SHA256 | f30c49623a8857fbce4f2c5b8ac16eea0fe600192b0ff41120fc2b8e447f12cf |
| peak | 0.07167027145624161；未进行主观试听 |
| 资源 | 本任务进程树RSS采样最大2,306,146,304 bytes，约2.15GiB；214次、200ms间隔 |
| 低预算 | 旧64MiB五分钟请求在DSP前HTTP400 / RENDER_OUTPUT_BUDGET_EXCEEDED；Python同样非重试拒绝 |
| 超时 | 实际executor 1秒超时，HTTP504 / RENDER_TIMEOUT |
| 取消 | 页面重建期间0.5秒取消；保留CancelledError，单槽释放，临时音频0 |
| 单元和静态检查 | API unit 552 passed；音频TS 30 passed；tsc noEmit、4个受影响源文件严格Mypy、Ruff通过 |
| 外部调用 | provider requests/tokens=0/0；无DB、Docker/Colima、用户浏览器或扬声器播放 |

RSS为`ps`对本任务Node/Python/Chromium子进程的RSS求和；共享页可能重复计数，采样可能漏峰，不是物理内存或内核封顶。probe的3GiB采样停止阈值未触发；它不是生产RSS硬限制。12轨/20k事件最坏负载及pinned Docker内存门尚未测量。

## 容量合同

`render-capacity.v1`：`ceil((scoreSeconds + explicitTailSeconds) × sampleRate) × channels × (bitDepth / 8) + 44`。

现有v1输出窗口已经由graph.durationSeconds定义，额外tail固定为0；reverb decay不追加到时长。Python和TS有相同的格式/取整/显式tail用例，未更改Engine、AudioGraph、ArrangementIR、Revision或Job schema版本。

- 支持44.1/48kHz、stereo、bridge16/24bit；正式与candidate PCM保持48k24。
- 硬性拒绝超过300秒、12轨、20,000事件、96MiB输出、320MiB预计裸媒体缓冲的请求。缓冲估算为float32 PCM加两份WAV；300秒48k24为288,000,088 bytes。该预算不包含所有Tone节点、浏览器与运行时开销。
- producer新预算为`max(1MiB, WAV必需字节)`。旧Canonical 2GiB和Candidate 512MiB字段范围仍可反序列化；服务与客户端将本次sink cap下调到推导值。旧预算不足时明确失败，不静默扩充。
- Worker继续通过权威StoragePressureGate，artifact与temp各预留推导上界，考虑提升时同时两份文件。客户端请求前按两个root的真实磁盘余量和minimum-free复核；同设备保留两份，异设备各一份。磁盘/项目配额仍是现有确定性规则，无模型参与。
- HTTP读body前预留唯一槽位；超时、取消、无效回执、超限临时文件都清理本Job render.wav/.partial，保留最终旧作品。Python和Node校验hash改为流式读取。

## 错误恢复与审查

本轮实际验收和一次独立审查发现并关闭三个问题：重叠body绕过单槽、关闭页面时页面异常抢先于超时标签、建页时已经取消但后来注册listener漏掉事件。每项都先记录RED，再修复并跑GREEN；[审查记录](2026-10-19-p1a-review.md)保留触发条件。一次修复复审后，限定范围无阻塞。

## 可复查入口

- [计划](../superpowers/plans/2026-10-19-p1a-render-capacity.md)、[原始JSON](2026-10-19-p1a-render-capacity.json)。
- 执行：`mkdir -p artifacts/p1a`，然后`node scripts/run_p1a_render_capacity.mjs artifacts/p1a/NEW_RUN`。该命令要求已有Node/项目依赖、Playwright Chromium、.venv、FFprobe；不自动安装或下载，不读取.env；输出目录必须不存在。
- 当前本地保留：`artifacts/p1a/2026-10-19-verified/`，含WAV、谱面、服务信息、回执、FFprobe及RSS原始采样；不提交大媒体。
- 完整unit：`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider --ignore-glob='**/._*' services/api/tests/unit`。
- TS：`node node_modules/vitest/vitest.mjs run --exclude '**/._*' packages/audio-engine services/render-worker`；`node node_modules/typescript/bin/tsc -p tsconfig.json --noEmit`。

## 下一条边界

本轮是WAV渲染与校验提升验收，未声称完成五分钟Master+全部Stems+MP3+MIDI+Manifest的完整Bundle，也没有重跑真实数据库/UI恢复或pinned Docker Worker。v1乐器与尾音行为保留；原有微小渲染差异见P0，不保证逐字节重渲染一致。

钢琴音源准备仍采用P0的小包候选记录：未下载任何样本。进入音源Task前，要确认准确压缩包内的LICENSE、WAV/SFZ根音/loop/velocity层、校验和、解包工具与解压预算；不能把网页CC0说明当作包内逐文件许可已核查。P1-A2先解决v1/v2合同与动态导出输入，之后才接音源与可听A/B。


## 收尾与存储账本

保留P0和本轮verified证据、历史真实作品及依赖。仅删除本任务两次失败运行173,019,226 bytes和专属/tmp Mypy缓存27,812,064 bytes；最终证据目录保留86,534,909 bytes（含86,400,044-byte WAV）。三个probe服务PID均已退出，临时音频0。Docker镜像、BuildKit、数据库卷和共享VM均未操作；当前已安装依赖与render dist留给下一条纵切。见[清理JSON](2026-10-19-p1a-storage-hygiene.json)。宿主render入口构建和Node语法检查通过；清理后重验保留WAV的SHA256/FFprobe及音频窄回归。
