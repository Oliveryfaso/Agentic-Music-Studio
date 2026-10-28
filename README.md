# Motif Forge

简体中文 · [English](README.en.md)

**面向独立创作者的本地器乐工作台：审核编曲计划、比较候选，把选中的草案继续编辑并导出。**

先用不需要 API Key 的模板体验创作流程，也可以导入已有音频。计划、人工选择、保存版本和执行记录留在同一个工程中，方便修改、撤销和查看失败原因。

[![Status](https://img.shields.io/badge/status-personal_Beta-6B7280)](docs/IMPLEMENTATION_STATUS.md)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

[演示](#演示) · [快速开始](#快速开始) · [第一次试用](#第一次试用) · [核心能力](#核心能力) · [配置自己的 API Key](#配置自己的-api-key) · [验证与限制](#验证与限制) · [文档与贡献](#文档与贡献)

> 当前面向本机单用户试用。默认模板不理解任意自然语言；启用 Key 也不代表默认古典、爵士已具备整曲模型规划。先走通免费路径，再按已支持的入口使用模型。

## 演示

以下是 **2026-10-28 已实现的器材工作室界面**：暖灰工作面、石墨控制区和烧橙强调色。截图由真实浏览器渲染，使用公开合成数据、mock API 和静音媒体；导出列表只是示例元数据，不代表真实生成、音质或下载验收，也不表示已有 Beta 实例已升级。[素材来源](docs/images/screenshots-20261028.json)。

**Studio：编辑与混音同一个保存版本。**

![暖灰与烧橙 Studio 的合成双钢琴混音界面，媒体静音](docs/images/studio.png)

<details>
<summary>作品首页与导出页示例</summary>

![作品首页的合成示例](docs/images/workbench.png)

![导出页的合成文件列表，未验证实际下载](docs/images/export.png)

</details>

真实公开作品试听与操作录屏仍待补齐。这些是实现界面的截图，不能代替音乐质量证明。

## 快速开始

### 新演示环境首跑

先准备 Node.js **22.12+**、npm、PATH 中的 `python3` **3.12–3.13**、Docker CLI / Compose / Buildx 和 `rsync`，并启动 Docker daemon。数据目录需要宿主机和 VM 都能访问；完整环境边界见下方。

不需要 DeepSeek Key。**已有作品升级请先看[运行手册](docs/PERSONAL_BETA_RUNBOOK.md)**，不要用新 clone 接管旧服务。

```bash
git clone https://github.com/Oliveryfaso/Agentic-Music-Studio.git
cd Agentic-Music-Studio
npm ci
scripts/start_motif_forge.sh --no-open
```

启动器会在缺少时创建 `.env`、初始化默认数据根 `../.motif-forge-data`，启动本项目后端与前端并等待就绪。首次可能构建镜像；启动会执行 Compose 配置中的数据库迁移。它不会安装或替换 Node / Python，也不启停 Colima。

**成功标志：** 终端显示 `Motif Forge is ready: http://127.0.0.1:5173`。在运行服务的同一台电脑打开 [http://127.0.0.1:5173](http://127.0.0.1:5173)；API 就绪地址是 `http://127.0.0.1:8000/health/ready`。本机地址不能用于访问另一台电脑上的实例。

正常结束：

```bash
scripts/stop_motif_forge.sh
```

停止器按运行记录核对归属，保留数据库卷、媒体、镜像和容器，不操作其他项目。`Ctrl+C` 只停止前端，后台服务仍需上面的停止命令。

完整新环境首装仍待验；[S1–S7 历史验证](docs/evals/S7_EVAL_REPORT.md)不代表所有新版本与环境都已通过。

## Prerequisites · 运行前准备

- 已验证的本机运行环境是 **macOS / Apple Silicon + Colima**。Ubuntu CI 通过不等于其他系统的完整首装已验。
- 使用宿主机和 Docker VM 都可访问的专用可写数据目录。首次安装、拉取镜像与构建需要网络和磁盘空间；这里没有通用最低内存承诺。

只读检查，不启动服务：

```bash
scripts/start_motif_forge.sh --help
scripts/start_motif_forge.sh --check
```

新 clone 缺依赖、`.env` 或数据根时，`--check` 会明确报告缺失，不能把它当成无需准备就必过的步骤。安装、端口和存储排障见[开发指南](docs/DEVELOPMENT.md)。

## 第一次试用

**使用路径示例：一个短背景音乐草案 → 审核模板计划、比较两个方向 → 保存可编辑版本并导出。** 这不是已生成作品展示，也不是模板理解任意描述的承诺。当前界面主要使用中文。

1. 在首页「从想法开始」输入作品名称「雨后漫步」，点击「创建作品」，会直接进入「新建编曲」。顶部「新建作品」可跳到这个入口。
2. 保留 `Classical Chamber`，标题填「雨后漫步」，用途填「短片背景音乐」，情绪填「平静，温暖」，时长填 `60` 秒，其余先留默认。未启用模型时点击「使用免费模板规划」。
3. 阅读计划，填写审批身份和明确确认说明后批准；试听 A/B 候选并选择一个。规则分不等于音乐审美评分。
4. 在 Studio 修改音符或混音参数，保存新版本。试听播放的是**已渲染的保存版本**，未保存草稿不会即时改变声音。
5. 打开导出页，等待文件就绪后下载；重新打开作品检查保存版本。导出与试听应对应同一保存版本。

## 核心能力

| 你要做的事 | 当前实现 |
| --- | --- |
| 审核创作方向 | 需求表单 → 结构化计划 → 人工审批 → 两个候选 → 明确选择 |
| 继续修改作品 | Timeline、Piano Roll、Mixer、草稿保存、不可变版本与 Undo / Redo；已支持的模型编辑有范围和确认边界 |
| 管理已有素材 | WAV / MP3 / FLAC 与 Stem 导入、BPM / 调性确认、可选保持音高时间对齐；保留原始导入，需确认素材权利 |
| 导出同一版本 | Master WAV、试听 MP3、Stem、MIDI 和工程文件；导出计划绑定保存版本，部分失败保留已完成项 |
| 查看任务与恢复 | Inspector 展示持久进度、人工决定、任务和用量；缺失用量不冒充零 |

模型负责有界提案，确定性代码负责音乐时序、校验、渲染和预算。工程结构与合同见[项目指南](docs/PROJECT_GUIDE.md)，不需要先读懂全部架构才能试用。

## 配置自己的 API Key

**这是可选步骤，不是免费模板的前提。** 默认古典 / 爵士整曲规划尚未实现付费模型路径；已实现的钢琴有界局部编辑有少量实测，不能外推为通用自然语言整曲创作。

1. 打开主导航「设置」，或 Studio 的「配置 API Key」。在 [DeepSeek 官方平台](https://platform.deepseek.com/api_keys)获取自己的 Key。
2. 在运行 Motif 的电脑终端进入仓库，执行隐藏输入命令：

   ```bash
   python3 scripts/configure_deepseek.py
   ```

   默认保存在 `~/.config/motif-forge/deepseek.env`，目录 / 文件权限为 `0700` / `0600`，不写入仓库；网页不接收或显示密钥。保存后**尚未启用**。
3. 先完成或取消当前任务。以下仅用于上面的默认演示实例；个人 Beta 或自定义数据 / runtime 参数必须沿用原配置：

   ```bash
   scripts/stop_motif_forge.sh
   scripts/start_motif_forge.sh --enable-deepseek --no-open
   ```

4. 回到「设置」刷新配置状态，再按需主动「测试连接」。它只向官方模型列表接口发一次鉴权请求，不生成作品；成功不代表余额、指定模型或 Worker 已验证。

仅在 `.env` 填 Key **不会启用模型**。显式开启后 Key 交给 API 和恢复调度器；Docker 管理者可能读取容器环境。模型操作会向 DeepSeek 发送有界音乐结构与描述，并可能计费，提交前应看当前运行状态。

停用时正常关闭同一实例，再不带启用选项重启。`--clear` 仅删除本机配置文件，不清除运行进程中的 Key，也不代替供应商吊销。不要把 Key 放进 `VITE_*`、URL 或日志。完整步骤、固定镜像 Beta 的接口匹配和清除命令见[API Key 设置](docs/API_KEY_SETTINGS.md)。[LangSmith](docs/LANGSMITH.md) 默认关闭，外部追踪需另行配置。

## 验证与限制

- **默认音色与真实钢琴是两个档位。** 默认使用轻量合成音色，不代表完整采样库。新建入口是 Classical Chamber 与 Jazz Harmony & Improvisation；历史电子风格保留旧作品兼容。
- **审核素材有限。** 当前仅四个 8–16 小节主旋律摘录；固定 2019 钢琴包有 26 个样本，不是完整曲库。合法原归档与兼容工具的显式准备流程见[审核音源准备](docs/REVIEWED_DATA_PREPARATION.md)，不自动下载或安装。
- **证据有边界。** 少量真实钢琴模型编辑 / 保存 / Undo / 同版导出有[实测记录](docs/evidence/2026-10-22-beta-real-model-loop.md)；不代表任意长曲、曲谱、风格或主观音质达标。[历史 Eval](docs/evals/S7_EVAL_REPORT.md) 是内部案例统计，不是作品音质通过率。
- **仍有待验项。** 全新安装到首次成曲、当前版真实 Key 完整链、恢复后的应用播放 / 导出和固定镜像冷重建仍未全部完成；存储 / 执行隔离候选也待完整联调。已通过的隔离 PostgreSQL / 媒体恢复不等于完整应用恢复。
- **产品范围。** 当前是本机单用户器乐工作台；桌面适合精细编辑，移动端侧重查看、试听与审批。专业 DAW、多人协作、公开托管、自动人声分离不在当前完成声明中。

<details>
<summary>已有审核钢琴 Beta：与默认演示的区别</summary>

需预置审核音源、宿主 / VM 共享和匹配的固定本地镜像，不是新 clone 后一条命令可安装的档位。仓库所带[发布 pin 模板](scripts/personal-beta-release.v1.json)不等于某台机器当前部署版本，也不提供镜像。

已有实例应沿用原数据根和 runtime 回执。仅更新源码或网页不会自动更新其 API、镜像或 pin；先按[个人 Beta 运行手册](docs/PERSONAL_BETA_RUNBOOK.md)和[实施状态](docs/IMPLEMENTATION_STATUS.md)核对，不把未部署候选当成已上线。

</details>

## 文档与贡献

修改前端可先走宿主机测试，不必重建 Docker：

```bash
npm ci
npm run test:web
npm run build:web
npm run test:audio
```

[CI](.github/workflows/ci.yml) 在 main / Pull Request 上运行无 Key 的 Python、Web / 音频回归和构建，不启动真实数据库或调用模型。需要真实外部服务的用例按条件跳过；绿色 CI 不是完整首装、音乐质量或恢复验收。

| 文档 | 用途 |
| --- | --- |
| [开发与排障](docs/DEVELOPMENT.md) | 后端环境、测试、端口、截图与常见问题 |
| [API Key 设置](docs/API_KEY_SETTINGS.md) | 隐藏输入、显式启用、状态检查与清除 |
| [审核音源准备](docs/REVIEWED_DATA_PREPARATION.md) | 固定归档、工具兼容与准备边界 |
| [个人 Beta 运行手册](docs/PERSONAL_BETA_RUNBOOK.md) | 既有实例、资源、固定镜像与维护 |
| [隔离恢复工具](docs/ISOLATED_RECOVERY.md) | 默认预演、可信归档与恢复限制 |
| [实施状态](docs/IMPLEMENTATION_STATUS.md) / [后续路线](docs/NEXT_DEVELOPMENT_ROADMAP.md) | 已部署、候选与未验事项 |
| [项目指南](docs/PROJECT_GUIDE.md) / [决策记录](docs/DECISION_LOG.md) | 产品与架构合同 |

问题报告请附运行档位、版本、复现步骤和已脱敏错误码，不附密钥或私人音频。源码位于 `apps/web`、`services/api`、`services/render-worker` 与 `packages/audio-engine`。

## 许可证

项目代码采用 [Apache License 2.0](LICENSE)。音源、导入素材与第三方组件的许可分别核对，代码许可不是所有素材的使用授权。

```text
Copyright 2026 Oliver

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0
```

再分发时保留 [LICENSE](LICENSE)；修改源文件时按第 4 条标注更改。
