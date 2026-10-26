# 个人 Beta：API Key 配置体验

revision 2 只关闭集成审查两个 Important：继承的 shell Key 不能覆盖已校验的私有文件；清除复用父目录拒链/权限规则，目录不存在仍幂等。先补合成反例 RED，再最小修复及窄复核，原补丁与报告保留。

覆盖 MF-P01/P13/P16/P18/P20/P21。基线 81b1cffc8bf8d20686a80bac6d6ae1cf242df9c4。

现状：没有设置路由或运行时 Secret 保存 API；Settings 在后端启动时读 SecretStr；普通及 Beta Compose 显式清空 Key，仅填 .env 无效。

最小方案：主导航和 Studio 缺配置提示进入设置页。复用环境 Secret：隐藏输入脚本写用户私有 ~/.config/motif-forge/deepseek.env（XDG_CONFIG_HOME 可覆盖），验证目录 0700/文件 0600，避免外置盘权限限制。启动器 --enable-deepseek 显式选用最后的 Compose 覆盖，仅 API/resume-dispatcher 获得 Key。网页不接收密钥。设置页 GET 仅检查本地配置；手动 POST 仅向固定官方 /models 发一次鉴权检查，不提交作品/生成请求，不重试或跟随重定向。检测结果仅当前页面，刷新恢复“已配置但未测试”，不冒充余额或模型生成通过。

不采用网页 Secret 库和热更新：现有无认证、跨进程 Secret 同步或受支持存储；也不提供会被 Compose 清空的虚假 .env 指引。LangSmith 不变。费用及结构化作品数据外发说明保留，关闭和清除需重启同一实例，不自动操作已有服务。

先 RED：配置状态/零自动外部请求/手动成功及脱敏失败、缺配置短路、连接拒绝；隐藏输入/0600/符号链接拒绝/替换清除；mock 启动参数与隔离范围。最小实现后相关 Python/Web 测试、类型、构建和一次独审。无新依赖、真实 Key、模型调用、Docker、数据库或用户 Revision 写入。README 由主线维护，本补丁仅新增相关设置说明。
