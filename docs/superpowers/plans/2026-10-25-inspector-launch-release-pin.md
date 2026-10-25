# Inspector 个人 Beta 启动镜像固定

阶段：MF-P18/P21，本地发布持久性缺口；隔离分支基于已部署a3bfb1a，不带674备份/日志或0031。

目标：保持 --personal-beta、--check、--no-open 旧参数，避免正常启动选回旧API。只改发布选择与启动前检查，不扩成部署框架，不重建/启停当前容器。

1. 先将实际无daemon Compose测试改为API应选已部署Inspector，复现当前默认local反例；增加错ID、缺镜像、迁移头/manifest不符时不up的模拟命令用例。
2. 新公开JSON记录已验证API ref、image ID、镜像应用源码commit与兼容Alembic revision。stdlib helper只解析manifest和本地迁移文件，不导入/执行迁移、不连接DB；输出公开固定选择。
3. personal-beta Compose固定API及schema迁移器为同一已审镜像，避免全局tag选择未知迁移器；其他服务沿用原全局tag。启动器核对实际config两者均为manifest派生的不可变ID，再只读inspect发布tag的ID；任何缺失/漂移在up前拒绝，不pull/build/自动改pin。
4. 保留受控API-only回退overlay作为最后一层，不新增跳过pin的正常启动开关。镜像appCommit不是启动器HEAD约束。
5. 定向与兼容测试、实际离线Compose解析、Ruff/bash语法，一次独审及必要窄复核，本地独立commit；当前R服务、243冻结、Guide和原回退说明不动。

实际数据库schema不由这个离线检查证明；正常冷启动仍依赖既有migrate完成条件及健康门。真实冷重建和退出/恢复均未在本片执行。
