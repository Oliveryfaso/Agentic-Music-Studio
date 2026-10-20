# P2.3 Q4 音区保持修复与单独小批验证

BASE ccbbe4003872594ea383d30a0cbfdfea150905cf，工作树clean；Guide最后d68b900且不改、不hash。MF-P04/P05/P06/P10/P11/P13/P15/P16/P18/P20/P21。用户已接受DeepSeek官方V4.1-Flash-1017替代服务；本次新批最多2次请求/每次预留0.096元/总预留≤0.20元，计入新授权起累计10元。先附件收尾（原包未改、第三次明确上传失败），再离线修复/审查，最后针对性真实验证，不重跑七例。

## 问题与最小合同

原真实Q4明确要求“保留原和弦与音区”，但第10/12bar octave3→2。现有代码只固定和声，未固定音区。本轮“保持音区”具体定义为选区每小节的计划octave参数不变，不锁死每个音高/节奏；原轨、和声及范围外仍原合同。显式保持语句由确定性规则识别，矛盾/不能核实先拒绝，不让模型判断约束是否适用。已保存Flash计划与当前NoteEvents/Track身份逐bar相等证明octave来源，不从单根音猜register；无可证来源在构造Provider前失败。

模型收到fixed_register矩阵；新prompt v4说明保持，结构plan未变。收到结果及重新产生候选前硬检查，不改写octave、不得生成后转调或静默repair。违反返回PIANO_REGISTER_CHANGED、无Plan保存/候选/媒体Job，保留原谱与实际usage/失败样本。历史Record/Revision/MP3不改；旧记录可读，旧违例不会被新材料化流程重新批准。可保留register_policy版本字段，不新增IR/DB/请求Schema或Graph。明确要求提高音区仍可走原有允许路径。

## 执行步骤

1. [ ] 从原保存结果复制有来源/hash的Q4回归夹具，真实旧反例经实际Provider+Service离线transport先RED，证明旧代码接受违例；补有效输出不改写、缓存违例、未知来源、歧义/冲突、明确提高的界限。
2. [ ] 最小应用层音区来源/约束与Provider context/postcondition，Prompt新写v4；无自动重试/模型fallback/转八度修饰。窄测试→相关真实PG边界/完整规定检查。
3. [ ] 新批账本与已接受模型映射单独保存，链接旧7次0.041030元（非账单）账本最终digest；不改旧policy/pause/历史4次0.023852元。先离线测试与一次独立审查（最多一次限定修复复核），Critical/当前路径Important阻塞。
4. [ ] 正式门禁通过后优先仅发1次原Q4请求，最多2是硬上限非目标。复用原Q1音乐计划作为明确标注的隔离测试输入，0新append模型；保持原请求名deepseek-v4-flash、response deepseek-flash、官方声明V4.1-Flash-1017与已确认映射。逐次pre/post身份与价格/范围/usage验证、持久fsync预留；失败即保留并停，不刷成功。必要新增2次总预留0.192元，不因累计10元而扩大。
5. [ ] 实际API/隔离PG/Parent/正式Worker仅新Q4候选2个Job或拒绝0Job，核对逐baroctave/和声、原轨/范围外与原始模型计划，保留旧失败和音频；新结果另命名。保存actual usage/保守估计/累计、清理精确自有资源，更新合同/状态/证据，正常开发分支push；main/Guide/旧音频/游戏共享服务不动。

停止：服务/映射/价格/数据范围改变，raw model或usage缺失/错误，HTTP/schema/和声/音区/预算/范围失败，未解决预留，下一次越2次/0.20元或累计10元。无充值/订阅/新长期密钥/额度轮询。请求仍≤8000UTF8bytes、3072output、12000total、non-thinking、attempt1/repair0。Library新重试已明确失败，无ID；保留旧包，不以新生成音频掩盖失败。


## 实际结案

新真实1次/2187tokens/公开峰价上界¥0.005586，批准后累计¥0.046616非账单；新旧批次均永久pause。Q4源octave2/3/2/3真实保持，无Plan改写；2正式Worker真实+2离线，908Python/37门禁/fresh独审通过。Library本次唯一重试失败无ID，旧包和新四段本地试听保留，审美待人耳。PG/生成DSN/renderer/browser关闭、共享容器不变，清理34599371逻辑bytes、24保留hash一致。Git正常开发分支checkpoint和远端读取结果记录于当前会话及workspace checkpoint.json，不在此预填commit ID。
