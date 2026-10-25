# 双钢琴个人 Beta：运行、现有作品与恢复说明

状态核验日期：2026-10-23；适用已审核谱目、双钢琴与本机个人使用。真实模型两轮编辑/保存/精确Undo/同版完整导出已通过正常API、队列和持久存储；真实浏览器播放、刷新返回和下载仍由原前端线补验，不将HTTP或组件mock写成浏览器通过。用户不必先试听，技术验证和交付仍可继续。

## 当前可用入口与版本

Web：http://127.0.0.1:15173/ 。仅本机可访问，内置页面或另一台设备打不开不等于本机服务故障。

- [现有作品当前保存版 U](http://127.0.0.1:15173/projects/cbc1c479-a90e-4730-9231-d63cf5cd6d81/studio/8afd8b30-aafd-4fbd-94b9-8970d77e7990)。U 已是撤回结果，完整内容等于第一轮R1，parent为第二轮R2；再次Undo会撤销本次撤回，不能用来寻找R1。
- [第一轮 A/B](http://127.0.0.1:15173/projects/cbc1c479-a90e-4730-9231-d63cf5cd6d81/studio/da526cc2-5087-498d-bb97-e2102f982214?piano_preview=piano-e0934a77a235b4704952827852e784a7)：R0→R1，仅第二钢琴5–8小节变疏、轻、短。
- [第二轮 A/B](http://127.0.0.1:15173/projects/cbc1c479-a90e-4730-9231-d63cf5cd6d81/studio/59a26b49-96c5-4172-97ba-4b04abf70781?piano_preview=piano-2652babe2d92b3e253eab6320ae177d1)：R1→R2，仅6–7小节四拍脉冲，保持和声/音区。
- [同 U 固定导出](http://127.0.0.1:15173/projects/cbc1c479-a90e-4730-9231-d63cf5cd6d81/exports/8afd8b30-aafd-4fbd-94b9-8970d77e7990?export_plan=05d24d3ccae18334ed533008641d13a0c0309655aa6e3831a9e8bb4abc03d120)：11文件，包括Master WAV/MP3、双Stem、MIDI、Project JSON及来源/许可/追溯文件。今天全部真实HTTP200、size/SHA与原文件匹配，共17,317,449bytes；这不是浏览器下载按钮已经通过的声明。

两轮线程今天均为 **completed**，已保存，不需重新批准或丢弃。此例R0由规则伴奏产生，两次真实模型请求用于局部修改；不把它称为本轮新的模型加轨或AI整曲创作验证。

## 最小检查与正常启停

当前服务保持运行供验收，无需重启。以下是这台Mac已经验证的本地配置示例；其他目录/设备应由用户明确选择自己的仓库、runtime和持久数据根，不复制所有权receipt来认领既有资源。

```sh
export MOTIF_REPO=/Volumes/KINGSTON/idea/agentic-music-workbench
export MOTIF_BETA_TASK=/Users/oliver/Documents/Codex/2026-10-18/task-2/research/beta-runtime-20261021
export MOTIF_FORGE_RUNTIME_DIR="$MOTIF_BETA_TASK/personal-beta-runtime"
export MOTIF_FORGE_BETA_STORAGE_ROOT=/Volumes/KINGSTON/idea/.motif-forge-data/personal-beta
export DOCKER_CONTEXT=colima
cd "$MOTIF_REPO"
scripts/start_motif_forge.sh --personal-beta --check
```

2026-10-23该命令实际exit0，输出 `Motif Forge launch prerequisites are ready.`。它只检查依赖、审核资源、既有镜像和公开Compose配置，不创建运行栈、不自动管理VM/下载/构建，不加载真实`.env`。其静态资源输出 `renderer_admission=not_checked` 是预期；当天另外的运行API capability已校验真实renderer就绪及固定包身份。

确实需要启动或正常关闭时，维持上面相同变量：

```sh
# 仅在需要启动本任务Beta时；不会自动启动Colima或构建缺失镜像
scripts/start_motif_forge.sh --personal-beta --no-open

# 正常关闭本任务，保留数据；不停止Colima/其他项目
scripts/stop_motif_forge.sh --personal-beta
```

当前任务没有再执行上述启动/关闭。早先正常停启与保留数据的实际证据见[B2b](evidence/2026-10-21-beta-b2b-recovery-restore.md)，不把今天的`--check`冒称一次新冷启动或整机重启。

### Inspector 镜像固定选择（隔离修复候选）

`--personal-beta`的API与其schema迁移器共同使用`scripts/personal-beta-release.v1.json`中的已审核发布：Inspector应用源码a3bfb1a、镜像inspector-a3bfb1a及固定image ID，兼容数据库revision声明为20261020_0030。应用源码commit描述镜像内容，不要求启动器当前HEAD仍是a3bfb1a。

启动器会先核对本地迁移图的唯一head、实际公开Compose选择的API/迁移器镜像和本机image ID，并以不可变ID执行创建，避免tag检查后漂移。缺文件、错误head/配置/ref/ID一律在up前拒绝，不回退local、不pull/build，也不从当前可疑镜像学习新pin。普通非Beta用法不变；原全局MOTIF_FORGE_BETA_IMAGE_TAG仍控制其余Beta服务，不能覆盖固定API或迁移器。MOTIF_FORGE_BETA_RELEASE_IMAGE_ID是启动器从manifest派生的配置，不是跳过检查的用户开关。故障恢复应取回已审核镜像；普通build不保证相同image ID，不能仅靠重新build或把检查到的ID写入manifest刷过检查。

本次只验证离线配置/模拟启动，未重新创建当前容器。迁移head检查不是live DB检查，真实冷重建和数据库兼容仍需正常维护验收。现有API-only回退说明保持：受控直调Compose的最后一层旧image覆盖仍有效；它不是正常启动器绕过pin的开关。

## 模型默认未配置的含义

当前API与resume-dispatcher均空密钥、tracing关闭。界面模型状态应为“未配置”；已保存作品和导出可读，新的自然语言提交需要明确配置。音源可用和远端模型可用是两件事。

用户此前批准的临时测试窗口已完成并清空，未建立长期密钥副本或常驻模型访问。启动器默认选择无秘密的公开模板，不会自动重新接入项目密钥。持久配置是将来用户确实选择日常模型访问时的具体动作，**不是完成本轮文档/现存作品使用的必经审批**。不要在聊天、仓库、日志或新文件中填写密钥，也不要为验证页面状态探测付费模型。

累计人民币10元测试授权仍是同一窗口。本次新增请求/费用0；此前累计观测峰价估计¥0.071874，预算门禁保守曝光¥0.161688（含旧未冲销预留），均非账单。不要重跑历史模型脚本、删state换key重试或重置旧账本。

## 恢复与数据保留

- 使用同一个runtime和持久数据根；PostgreSQL卷与外置Artifact根共同构成作品依赖。不要删除卷、移动根或清空Artifact来解决页面/执行器问题。启动失败先保留错误，按明确的缺依赖/配置/资源诊断处理。
- 原三个项目保存head保持，当前验收项目仍是U。读取旧保存版不会产生新的模型请求；已知成功回放与未知请求恢复必须区分，未知结果先读状态，不能重发。
- **旧pending候选超过24h后会从恢复目录排除**。2026-10-21建立的另两个旧候选已到期，数据库仍pending且无批准/丢弃，保存版本不变。它们与上述两个completed模型线程不同；目录没有待确认项不等于保存作品丢失，不擅自续期或重建。
- 隔离空目标备份还原演练已通过容器内API，但当时宿主18100入口未通过；没有证明整机断电、运行中模型崩溃或所有共享任务自动恢复。不用还原操作覆盖现有作品。

本机审核包只读且固定版本/pin；可用范围为界面已审核目录和双钢琴，踏板/release-trigger未支持。不将本次C02八小节证明泛化到任意输入、曲库/风格或多人公开服务。

## 验收分工与下一步

主线已完成正常API/队列/真实模型两轮、版本保护、持久重读、精确Undo、同U全部文件，以及已有8音频严格解码/83个MIDI事件核对。未发现新的产品代码缺陷，不为继续而增加功能。

原前端线继续处理实际播放/切换、刷新/返回/重开、下载、键盘/窄屏的工具依赖；目前没有新补丁待集成。旧原生审批unknown且无可转发ID，不重发/换通道绕过。用户可自行试听给偏好，但不是所有技术工作的先决条件。资源已有核验，本轮没有新增资源需求。

完整现状与边界见[当日收口证据](evidence/2026-10-23-beta-current-closure.md)和[阶段计划](superpowers/plans/2026-10-21-personal-beta-runtime.md)。后续只修真实反例或完成现有门槛，不自动进入新曲库、乐器或P3–P5。
