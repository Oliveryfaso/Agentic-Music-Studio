# Personal Beta B1：本机运行基础通过，浏览器与B2待验

2026-10-21；MF-P16/P17/P18/P21。基线6e5e7c5，Guide last d68b900且diff空；不改变已认可编配/Graph/IR/DSP，不合main、不公开部署。

## 真实结果

用户明确批准后，仅追加审核钢琴包的精确只读共享，保留既有数据共享，在批准维护窗正常停启同一Colima实例一次。原27容器ID全部保留，原4个running恢复，17个inactive未启动；原6个restart循环不被误报为本任务修复。Docker daemon/global context/其他配置保持。没有删除、重建或迁移VM、复制音源或改整盘共享。

专用API/media/renderer镜像均已构建；API和media各157公开文件与当前源码一致，renderer3bundle与当前源码独立编译一致，5个原共享镜像ID不变。构建遇到公共依赖下载502/ECONNRESET，在原有限依赖重试内恢复，没有更换代理或音源。

实测发现构建成功仍有运行缺陷：外盘0700程序文件进入root所有镜像，UID10001读取dist和package.json得到EACCES。新增实际默认用户边界测试RED，Dockerfile只将公开dist目录0755及package.json/JS0644，保留非root；只重建renderer后GREEN。7项既有构建检查、renderer构建124音频测试通过；一次fresh限定独审0确认发现。宿主仓库、包、数据权限未改。探索性context权限实验未集成，不作最终通过证据。

标准个人Beta启动已运行真实Compose/当前renderer/host Vite，端口全部loopback。资源预检assets_verified/resource_ready均true、renderer_admission=matched/live_checks=passed；容器层精确包只读、固定pin和API四谱目录一致。模型Key显式为空、tracing关闭，没有复制现有.env/密钥。

正常API导入审核C02（201），请求显式roots手工伴奏（202），经过现有Parent/Dispatcher/Redis/Celery/renderer得到两个真实试听Artifact。只读数据库佐证两Jobs各attempt1成功、Outbox各published及queued/started/completed事件；没有手工完成Job或直接业务写库。候选停在waiting_piano_approval、head未推进，AI Run0。这是基础规则链路，不是自然语言模型或音乐审美验收。

真实URL/Project/Revision/thread/Artifact和原前端失败fixture保存在本机任务交接，不发布共享容器清单、私有配置或音频。故意未知thread的只读GET实际为404 AI_RUN_NOT_FOUND；不是历史失败Job，也不沿用准备说明中猜测的错误码。

## 接续边界

原前端session继续真实页面加载/A-B实际播放/错误恢复/确认及导出检查，开发主线不替代浏览器验收。随后B2仍需同环境自然语言连续修改、精确Undo、关开重读、同Revision导出和独立目标还原。默认禁用模型不能当成AI全链完成；凭据启用另按明确授权边界处理。本轮不推断整机重启或丢失所有权回执后的自动恢复。

环境有意保留给原前端：精确所有权回执、数据库卷、未决候选与当前镜像全部保留。阶段卫生先冻结keep set再盘点；共享BuildKit归属不明，不做全局prune或删除共享缓存。运行状态与字节盘点在私有交接保存，不把未清缓存说成已回收。

新增付费调用0/费用0；旧累计估计上界¥0.059998，非账单，同一累计¥10不重置。[机器证据](2026-10-21-beta-b1-runtime.json)。
