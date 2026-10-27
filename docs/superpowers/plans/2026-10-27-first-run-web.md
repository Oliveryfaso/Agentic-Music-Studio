# 新用户首跑前端 v2：保留无Key确定性回退

基线 ec2ff5b4140b574f64ad0ca81c254eaae150b39c；阶段个人Beta首跑，MF-P01/P13/P18/P20/P21。原v1补丁逻辑审查未过、未提交。本次纠正能力理解，不改变后端、README、安装或CI。

准确合同：整曲generate无Key由MissingDeepSeekPlanner路由deterministic_fallback，生成低置信规则计划并等待审批；不是完整自然语言理解。经典谱中的按描述钢琴伴奏/局部修改另属semantic模型路径，已知未配置时仍禁用并显示设置入口。GET model-settings只有运行配置configured/not_configured，不能识别本地文件已保存但实例未启用。请求合同不支持max_model_requests=0，也没有客户端强制免费模式；不能新增虚假模式字段。

最小修复：Brief已知not_configured也开放提交，按钮明确“使用免费模板规划”，保留配置链接、模板限制和计划审批说明；configured保留主动提交及费用提示。读取中/读取失败先重读，不把未知状态称免费。空状态与设置文案同样区分模板与模型。不自动检测Key、不调用外部服务。

保留v1同页body/Key防重、422更正和离页迟到回执归属。请求身份只保留当前页面实例，跨刷新/离开先从作品核对已有任务，不新增持久化协议。

TDD：将错误的无Key禁用测试改为明确免费提交→queued断言，先在v1上观察RED；增加模型专属钢琴操作仍禁用并提示设置的反例覆盖。继续验证读取失败保留输入、未测试可提交、失败手动重试同一身份、422更正及迟到响应保护。跑相关/全Web、类型/构建与只读独审。

隔离Mac Chromium mock增加实际无Key按钮→规则计划审批显示、已启用未测试→失败重试身份相同、真实PianoPanel模型专属状态。播放/导出完成状态仍是独立合成fixture，静音PCM不代表音乐或完整生成E2E。只绑定随机loopback，全部API拦截，零Beta/真Key/模型/付费，结束关闭自有浏览器与Vite。
