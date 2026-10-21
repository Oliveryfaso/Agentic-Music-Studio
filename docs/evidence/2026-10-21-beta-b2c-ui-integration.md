# P2.3 / B2c 前端合同消费者集成收尾

2026-10-21；MF-P06/P13/P18/P21。基线a83decb13a078c512a3a7d6482eeb8de60ba6b17，原前端session交付，主线唯一集成。Guide最后d68b900且无diff，未hash。范围仅5个已审前端文件及本次计划/验收文档；不扩新功能、不改后端/音乐/模型/配置/main/Guide。

## 已集成

- Studio消费既有workspace目录。用户点击才恢复原base+thread；区分空/多/旧版本/不可读/上限/缺字段，显式错误thread不换成其他候选。读取中或终态后尚未重新确认目录时禁新生成；旧base保留锁、脏草稿保护恢复与离页。
- 模型本地配置三态独立于音源；not_configured只禁语义生成，单轨规则入口保留，双轨不虚构规则修改能力。已渲染当前候选的审批不依赖模型配置；本轮不执行审批。
- root撤回按钮禁用与handler早返，说明“初始版本没有上一版可撤回”。原非root Undo测试fixture补真实parent，不移除其恢复Revision断言。

精确原补丁38168bytes，SHA256 71c489d29283eba597a9efb087e2721661670fe744aa02557ec1bf552954ae93；base、文件清单、apply适用均验证。未混入原session的overlay配置、机器路径、缓存或证据脚本。原前端一次独审发现2 Important/1 Minor，已修且唯一窄复核全部关闭；本次不重复启动审查循环或重做其RED。

## 本主线实际验证

1. 在已应用补丁的真实仓库源码（无replacement overlay）跑21项新定向+39项相关回归，60/60；完整TypeScript通过。阶段组合Web回归47文件164/164，单worker，相关测试与整套结果分别保留，不相加作独立样本。
2. git diff --check通过；没有运行新的PG迁移/后端全矩阵/模型/音频渲染。a83decb已有的真实PG和后端读合同证据沿用，不冒充本次重测。
3. 首次普通HTTP读取15173被拒绝，原Web PID60190不存在、15173无监听，原launcher工具session已无记录；API18000仍ready。未断言消失原因。保留首轮失败，按已授权范围仅恢复自有Web：原私有operation锁/owner receipt/同一源码/15173/API代理18000，保留旧Web记录，更新可供原停止器识别的PID/root/lstart。新Web PID66647。没有调用Compose或改变API/旧项目/Colima状态，未安装依赖。普通沙箱ps权限失败后，经受审核只读PID核验确认原PID不存在；没有绕过浏览器审批。
4. 普通HTTP GET证明现有15173入口返回HTML和三份变更的Vite转换模块；记录三份源码/响应指纹与新增合同标记。它证明入口提供当前代码，**不能证明浏览器已渲染、实际播放、下载或键盘交互**。未重新发起DevTools、创建替代浏览器、访问被拒应用或换调试通道。
5. 同一Web代理6个真实GET：音源available=true、模型not_configured；原前端/B2a/B2b三个head保持；原候选thread `piano-42bfd5ef55b0fb2e80e3a4aff946c355`仍waiting_piano_approval；固定B2a导出plan `384ee00643d28ac4914bfecbee81c3c9eaba6fa3b147055b4144ae5fb8f18a83` 返回ready、11文件及同一Revision a381dbd2。没有GET媒体bytes、下载文件、生成/审批/放弃/保存/重导出POST。

0新增模型调用/费用；旧累计估计上界¥0.059998、同一¥10窗口，非账单，未重置。未新增凭据配置或对外暴露端口。没有Docker构建/镜像更新/全局cache或volume清理。

## 手动验收（在用户 Mac 原浏览器，约3–5分钟）

1. 打开[原保存版](http://127.0.0.1:15173/projects/239f66ff-816a-4b3a-a352-500dbd67c11b/studio/16a5835b-a627-57f6-aa84-8abb49443c51)，确认“恢复这版试听”和独立的音源/模型状态。
2. 点恢复，确认仍为16a5835b版本，地址增加原thread `piano-42bfd5ef55b0fb2e80e3a4aff946c355`，不新建试听。
3. 仅播放/暂停/切换A/B，核对实际发声、进度和单一播放器占用。这是免费规则链路，不能代替此前真实AI样本的音乐质量验收。不点保留/放弃/保存。
4. 打开[既有同版导出](http://127.0.0.1:15173/projects/4b2781b7-1517-485e-b9b2-c2bac87de828/exports/a381dbd2-76ca-4f31-bcbe-c299a3e9a3fc?export_plan=384ee00643d28ac4914bfecbee81c3c9eaba6fa3b147055b4144ae5fb8f18a83)，查看ready/11项，可下载既有文件；不点击重新导出，返回Studio仍为a381dbd2。

自动浏览器原生审批仍unknown，无可转发ID，不重发或绕过。播放/下载/键盘与小屏、用户听感仍待真浏览器/用户结果。全个人Beta自然语言连续创作验收也没有由此替代。本轮停在这些验收关口，不循环增工程范围。

## 证据与收尾

工作区 research/beta-contracts-ui-integration-20261021：intake、原patch、60项/164项/typecheck日志、原始连接拒绝、Web恢复记录、live-web-contracts.json、手动步骤、提交/远端读回及部署版本对应回执。

本轮保留全部小型补丁/日志/服务运行记录及活动Web所需缓存，盘点确认没有可安全删除的过期本轮产物，删除0bytes。没有新增数据库/音频/镜像，未删除任何作品、卷、音源、导出或未决候选；共享builder不动。服务保留给用户验收，仍由原owner receipt停止流程管理。main/Guide不动，正常dev提交推送后核对远端SHA；页面版本以源码/转换回执为准，不声称浏览器UAT通过。
