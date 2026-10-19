# P2.2 — 自然语言钢琴伴奏与局部改写

2026-10-19；BASE/Guide `5dbbc6aabf08b9a6e2d4fbfece810afc23fe5564`，开始时工作区、Guide clean。用户已直接授权实施、使用原DSAPI Flash，真实测试成功/失败/重试累计不超过人民币10元，以及验收后正常推开发分支，不合main、不部署。旧P2.1已完成；本计划不能以重验旧交付代替。

覆盖 MF-P02/P04/P05/P06/P11/P13/P15/P16/P17/P18/P21。仅同一审核Mutopia528旋律、最多两轨同审核钢琴。自然语言追加全16bar伴奏，保留后指定新增轨连续1–4bar再改写；原谱/非目标区精确保留。模型每次只输出一个 `accompaniment-plan.v1`，逐小节和弦、16分网格、音区、力度、有限时值与摘要，确定性编译音符；不接收模型UUID/路径/任意命令。规则伴奏仍可用作基线。

## 实施顺序

1. 领域TDD：有界Plan/compiler、agent append与局部变更命令、L2、精确Undo、原谱与范围外保护。领域协作者只写新增piano_plan模块及其unit/Eval。
2. Provider与持久化：复用DeepSeekJsonClient、持久请求预算与现Parent的piano分支；单动作单请求、明确非thinking、JSON、无自动schema/transport retry，无静默回退。先持久已校验计划再安排试听；重放恢复不会再次花费。遇到网络已提交但未持久结果，只允许明确失败/unknown，不自动再付费。新持久请求/状态如有不兼容必须版本/迁移与旧读兼容。
3. UI/API：扩展现有piano-preview入口显式semantic目标与小节范围，显示模型摘要/来源/状态；沿用真实A/B、hash绑定保留/放弃、刷新恢复、保存重开/Undo/导出。无LLM时明确失败，可单独选择原有规则路径。
4. 集成：新一次性PG、Mock窄测与代表性重放/恢复；built UI和真实受限Flash追加、保存、9–12bar改写、保留、重开、Undo/导出。音频共享编译器/音源/Worker不换。
5. 一次fresh独立审查、至多一次作者修复/限定复核；更新Status/TECH/实际能力与合同、存储关闭门、checkpoint/正常push并核远端。旧默认古典/爵士宏观Planner仍只收Synth的缺口明确记账，不将本任务专用Planner假报为全风格修复。

## 调用与费用合同

实际配置白名单读取：configured=true、endpoint=https://api.deepseek.com、model=deepseek-v4-flash。不打印/读取导出密钥。2026-10-19官方中文价格页 https://api-docs.deepseek.com/zh-cn/quick_start/pricing/ 说明旧模型名仍可调用，由V4.1-Flash-1017服务。保留现配置请求名，记录响应实际模型。高峰CNY/M token：cachehit0.04、miss2、output8；空闲半价。预算只用高峰、最坏全部token按输出8估算，不依赖cache、时段或汇率。

每Run最多1提交/12000总tokens/3072output，输入UTF8字节保守界限8000；max_attempts=1，零隐式Critic/repair。阶段真实验收最多8提交（失败/重试也计），最坏预留8*12000*8/1e6=0.768元，低于用户10元。先workspace阶段账本逐次预留，返回usage后按官方高峰价计算保守费用；无usage保留最坏预留并停止继续真实调用，不写0。实际账单未查询则标示“按公开费率计算/上界”，不冒充账户扣款。真实模型调用之前所有mock测试显式无key。

## 最少验收

密度、音区、力度与选区有可测差异；拒绝原谱target/越界/多轨/非法schema/不支持意图。持久预算unknown/exhaustion无第二HTTP；重复请求/代表性恢复一次提交/一次候选。实际PG/UI试听与hash审批、非目标精确、重开Undo、一次导出。工程/规则通过不等于审美质量通过。保留固定16bar谱、单力度层、无踏板的边界，不宣布全部P2/P3或默认两风格旧生成已完成。

## 进度

- 实施、真实Flash与built UI/PG/Chromium链、一次独立审查及唯一修复复核已完成；两项Important关闭，Minor按Roadmap延后。局部修改最终明确保留可信原和声，只改节奏/音区/gate/力度。
- 最终747 Python、102 Web、61 Audio、6 PG/Inspector、Mypy131源与两build通过；累计4调用/7228tokens，含首轮语义反例，峰值价费用上界¥0.023852。
- 自有运行时和生成凭据已关闭，accepted媒体保留；最终文档与存储核验完成，checkpoint/push结果由本任务最终交接回执记录。
