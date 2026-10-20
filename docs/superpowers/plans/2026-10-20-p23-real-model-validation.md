# P2.3 真实模型验收执行计划

BASE a841c1189780006c795f4d4efc6ee28d1d24889e；Guide最后d68b900、start clean。MF-P04/P05/P06/P10/P11/P13/P15/P16/P17/P18/P20/P21。按已批准9例计划执行，不新增产品功能；现有原谱、旧26Job与离线样例不重跑/覆盖。

用户已批准从本次授权起Motif后续测试累计人民币10元，历史4次/7228tokens/公开峰价上界0.023852元完整保留（非账单）；本轮仍最多7次/CNY1，不因累计限提高而扩调。官方API与deepseek-v4-flash保留，实际响应预期deepseek-flash；服务/配置/价格/数据范围变化先暂停确认。

1. [ ] 只读核对价格、Settings白名单；任务专用持久money JSONL先预留再发，每次0.096元，未知/失败保留可能费用，usage后等本地验证才放行下一条。max7、总12000/输出3072/输入8000UTF8bytes/单并发/max_attempt1/repair0；离线测试和独立闸门审查在首次调用前。
2. [ ] 缓存PG镜像创建精确自有tmpfs库/凭据，迁移0030；实际built UI/API/正式Worker/Parent恢复路径。零调用守卫先验；只发送有界音符、范围、音乐文字和Schema，不上传音频/XML/私人文件或完整工程；无充值订阅/新长期凭据。
3. [ ] 逐条Q1–Q7，无网络重试、不按失败补满；异常先暂停。首次真实usage及时写共享状态并报告。保留/放弃/范围外/原轨/恢复/Undo与模型意图分开评。
4. [ ] 真实音频本地渲染，保留原增益和固定增益等LUFS两组，人工质量待听，不用模型自评代替；canonical不改。导出native离线附件并沿可靠Library单文件流程交付。
5. [ ] usage及保守估计费用双账（本次授权累计/历史全账）与失败证据、评审记录；自有API/browser/renderer/PG/凭据关闭，保留媒体hash，安全dev checkpoint，不碰main/Guide/强推/部署。

停止：HTTP/timeout/schema/和声/范围失败，usage或原始model缺失/变化、配置/价格/数据范围变化、未解决预留、下一次将越7次/CNY1/CNY10时停止后续网络调用。批次账本仅任务验收外闸，产品每Run PG预算不改。必要后续测试也不自动多调本轮7次。

## 实际验收发现的恢复阻塞

Q1/Q4真实调用各一次已完成，本轮累计2367+2130=4497tokens，峰价上界0.013824元（非账单）；在原始IR/hash、试听/保留/放弃检查之后，语义append持久Undo实际返回UNDO_NOT_AVAILABLE。停止后确认piano_parent_restore只白名单手动AppendPianoTrackCommand，遗漏已支持逆命令的AgentAppendPianoTrackCommand。MF-P04/P06/P10/P11/P13/P18/P20/P21范围内作最小恢复修复：三曲无模型回归先RED，加入该命令但保留当前head/精确parent/full快照条件；窄测试+已有真实PG恢复复核后继续剩余用例，不重复已付费Q1/Q4或旧Job；新生产修复独立审查一次。

## 最终执行回执

7次/14473tokens/峰价估计上界0.041030元，不是账单；历史旧账保留。实际19新Job、11完整导出文件、888产品Python与33任务门禁通过。Undo一行修复经有效三曲RED→GREEN14、真实PG/UI零外发恢复、独立审查。当前未确认V4.1替代服务，永久pause；Q4音区指令失败、人耳质量待验；不刷成功。身份pre/post门禁及独立审查完成，当前approval=null阻止外发。完整离线包保留，Library首传失败，轻量传输与Git回执单列。owned PG/凭据清除，共享资源不动。
