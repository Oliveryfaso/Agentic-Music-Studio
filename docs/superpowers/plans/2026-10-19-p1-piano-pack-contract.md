# P1 钢琴包合同与引擎适配准备

2026-10-19；Stage P1 包合同子门；MF-P02/P05/P10/P15/P16/P17/P18/P21。起点823c4e7b46b9c54ac36aab30600c6f4aefe65fc4，工作区clean，PROJECT_GUIDE无差异。使用已批准P1计划与用户本次明确的包核查/适配测试授权，保留手动模型设置。采用executing-plans/TDD；本轮只推进现有renderer的纯音源合同/voice适配准备，不激活用户入口或跳过A2/DB门。

## 范围和判断

1. 官方小包固定URL、5MiB下载硬限、列目录；只读text，绝不执行包内代码。既有bsdtar能列目录但读取member报Unsupported filter 3 for 40202，未安装7z/py7zr。读取包内许可/映射因此暂受阻，真实包保持quarantine，不发布可用manifest，不从文件名猜root/力度层/loop。官方CC0说明不能替代包内证据。
2. 落地versioned instrument-pack.v1与显式受限voice计划，以及既有Web Audio/Tone可消费的受控BufferSource适配函数。manifest绑定pack/version/许可文本hash/源archivehash/样本hash与字节、格式/frames、rootMidi、key+velocity zones、显式loop和release；只接受本地包内安全路径。验证语法/内容不等于完成许可审批。
3. 使用现有builtin click/自制短PCM工程fixture验证力度层边界、跨八度playbackRate、增益、每voice release和并发上限；sample缺失/hash不匹配/越界loop fail closed。此fixture不是钢琴录音，不用于钢琴音质结论。
4. 本子门踏板和release-trigger样本均暂不支持，输入时明确拒绝；普通note-off release采用有界淡出，不能把它宣传为真实踏板/释放噪声。后续P1-C的二态踏板仍是待实施门。
5. v1 compiler/contracts/jobs/aliases均不修改，未知版本和缺包不降级或silently换音。新函数只由测试/准备probe消费，尚未接v2 AudioGraph/Revision/Job/UI；真实Bundle仍依赖A2，持久v2仍依赖B及DB双读迁移门。

## 资源与验证

P1-A1五分钟3轨/880事件进程树RSS采样最高2.15GiB；320MiB仅裸媒体缓冲预算，不能当真实RSS封顶。新包约4.34MiB下载，目录声明样本约9.5MiB（精确总数由audit记录）；本子门单样本<=4MiB、总编码<=16MiB、解码float32<=64MiB、<=64样本、<=64zones、<=32voices、<=2秒release。每次离线短probe<=2秒、无扬声器、无模型/DB/VM。

步骤：先新增TS行为用例看到缺失API/行为RED，再实现最小validator/selector/planner/scheduler，运行音频suite+tsc；用独立headless短离线context验证octave频率/力度能量/release停止，不加载真实包。保留现有v1回归。必要时一次独立只读审查；更新状态/证据，清理本Task输出，本地checkpoint不push。

## 账本

Ruling：先做无持久化包合同与适配测试，不先激活v2产品链路 — 用户本次明确优先核查音源与补测试，A2/B仍是生产依赖 — 代价是本轮不能交付真实钢琴预览或完整导出。
Ruling：解压能力不足时隔离真实包，继续本地合规fixture — 不为读取许可安装未经授权软件或猜映射 — 代价是源包包内许可、root/层数/loop仍待已有兼容解压器或明确安装授权。


## 执行结果

本轮合同/适配子门由48条音频TS、tsc、宿主构建和自制click短离线probe验证。一次独立审查、一次有界修复：非零起点5ms gate的浮点误拒、NaN误放行和描述字段误拒均先RED后GREEN。仍未读取真实小包许可/SFZ，不接真实包，不激活用户链路；需另行允许1,861,928-byte官方解压器后继续具体审核。审查的probe Minor重评为影响本轮证据可信度并在同次修复关闭；无其他待修Minor。音源准入是未完成资产门，不把代码测试成功当许可通过。
