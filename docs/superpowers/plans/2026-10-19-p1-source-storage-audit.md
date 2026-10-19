# P1 音源文本核查与PG存储阻塞收口

Stage P1 supporting resource audit；2026-10-19；MF-P05/P10/P15/P16/P17/P18/P21。起点d312dbc，Guide无diff，工作区clean。本Task只更新事实和证据，无产品代码/Schema/迁移/依赖修改；沿用手动模型设置。

用户批准小型音源下载；不扩展为7-Zip工具运行许可。复用已隔离小包并重验hash，使用现有系统/Conda bsdtar核对许可、SFZ与WAV可读性。成功成员要求退出0且bytes精确相符；WAV失败单独记录，不放行manifest，不把click当钢琴。

用户终端也复现Colima EROFS，先只读核对符号链接、真实卷、挂载/映像可写状态、归属/flags/空间，纠正只归因sandbox的解释。不读取密钥或配置内容，不强制重挂/删VM/改安全权限。共享UnityWorkspace普通弹出重挂也可能影响其他任务，先给精确修复目标与待确认动作。

验收：可复查审计脚本、文本sha与字段断言、原始相关卷元数据；一次独立证据审查。文档事实变化不重跑未改动的产品全suite。清理不操作外部作品/数据库/镜像/共享卷；保留小型审计证据和唯一音源归档。本地文档checkpoint，不push。
