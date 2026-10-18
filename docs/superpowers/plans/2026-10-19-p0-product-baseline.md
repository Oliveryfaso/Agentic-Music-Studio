# P0：古典/爵士产品合同与无付费基线

日期：2026-10-19（Asia/Shanghai）。用户已授权本轮 P0 与 P1 实施准备；P1 音乐能力尚不实施。

Stage：P0，保留已完成 S1–S7 历史证据。覆盖 MF-P01/P02/P05/P06/P08/P09/P10/P11/P13/P15/P16/P17/P18/P20/P21。

Spec：用户批准的 `MotifForge产品成熟化研究与分阶段路线-2026-10-18.md`；本轮目标是写入古典/爵士主线、legacy 保留、现实基线和 P1 可执行方案。

## 全局约束

- 起点 `bebef9f1fa84daab56b6577055c379e4c94a029d`；起始 main 工作区 clean。分支 `codex/motif-p0-piano-preparation`。
- 不改模型、音乐语义、数据库、StylePack ID、旧作品或现有录音。无付费 API、无插件安装、无样本下载、无 push/release。
- 不读取 `.env`/凭据；基线脚本只导入纯领域/应用函数，不构造 Settings。模型与 tracing 环境显式禁用。
- Docker/Colima 本轮检查为未运行；优先 host-only。独立 headless Chromium 不连接用户浏览器，不共享 user profile。仅使用 127.0.0.1 临时端口。
- 测试谱和输出写入显式、唯一、项目拥有的外置 `artifacts/p0/` 目录；保留最终基线和哈希。脚本拒绝覆盖已有报告。
- 不能把 synthetic legacy fixture 称为用户旧工程数据库复验；不能把宿主 Chromium 当 pinned 容器 canonical 验收。

## Task 1：仓库与运行环境

Steps：读 AGENTS/Decision/Guide/Status/Roadmap/Skill；确认 HEAD/status；创建独立分支；检查 Docker/Colima、现有 Node/Python/FFmpeg/Chromium。

Expected：原工作区干净；新分支成功；不启动/停止其他项目。记录限制，不安装缺失依赖。

## Task 2：符号与声音基线

Files：`scripts/run_p0_baseline.py`、`scripts/run_p0_render_baseline.mjs`。脚本是测量工具，未接入产品路径。

Inputs：现有 S1 deterministic seed=42 旧版 IR（72 秒）与现有 30 秒代表谱（synth+sampler+EQ+reverb）。

Outputs：不可覆盖的 legacy IR/AudioGraph、symbolic-report、5 个固定谱 PCM24 WAV 和可选真实旧导出重渲染 WAV、ffprobe/哈希、延迟和 process-tree RSS 采样。

Run：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/api/src DEEPSEEK_API_KEY= LANGSMITH_TRACING=false .venv/bin/python scripts/run_p0_baseline.py --output-root "$P0_OUTPUT"`，再 `node scripts/run_p0_render_baseline.mjs "$P0_OUTPUT"`。`P0_OUTPUT` 必须指向本次新的外置 evidence 目录。

Expected：旧 IR canonical roundtrip 不变；72 秒投影；30 秒 cold/warm/单 stem 和 72 秒 legacy 合成均为 48k stereo PCM24，精确 bytes、非静音且峰值不超过 1。重复渲染记录 PCM24 差异，不凭 byteExact 单独判主观音质。

Focused verification：`PYTHONDONTWRITEBYTECODE=1 DEEPSEEK_API_KEY= LANGSMITH_TRACING=false .venv/bin/python -m pytest -p no:cacheprovider services/api/tests/unit/application/test_rendering.py services/api/tests/unit/application/test_generation_export.py services/api/tests/unit/domain/test_revisions.py services/api/tests/unit/audio/test_chromium_render.py -q`。Expected：25 passed。

Current-defect probes：64 MiB 与 300 秒 PCM24 数学冲突、四 stem steps、articulation/cents 改变却 graph 不变、instrument aliases。报告缺陷是现状记录，不写成长期必须保持的产品断言。

Failure routes：缺本地工具/浏览器→停止该 probe 并记录 blocked；渲染超时→关闭本次 page/browser、保留可诊断日志，不静默替换引擎；报告不完整→不标 P0 完全验收；任何新 VM/软件安装不在该 Task 内。

## Task 3：合同与 P1 计划

Files：AGENTS、DECISION_LOG（ADR-019）、PROJECT_GUIDE、IMPLEMENTATION_STATUS、NEXT_DEVELOPMENT_ROADMAP、TECH_EVOLUTION、P1 slice plan、P0 evidence summary。仅改当前决策及冲突入口，历史证据明确标注，不重写历史测试数字。

Expected：当前活动阶段只有 P0/P1 产品改造；古典/爵士为新增主线，电子风格退出默认新建入口是待实施事项；旧 ID/工程/音频与导出兼容不删除；P1 单钢琴、固定 BPM/4/4、两层表达和明确版本门，不顺带做全 tempo map、四 stem 重构、P2 曲库。

## Task 4：检查与恢复点

Run：脚本语法、Ruff（只新 Python probe）、文档链接/相互引用、`git diff --check`、`git diff -- docs/PROJECT_GUIDE.md`；一次独立整批审查。Expected：没有秘密/本机绝对路径进入产品代码；没有媒体/缓存入 Git；记录剩余 blocker；提交本地 checkpoint，不推送。

Storage：keep set=新接受的基线、源码、锁文件、既有全部用户资料。仅清理本轮可再建 bundle（若不再需要）；无 Docker build/cache/volume 操作。

## 执行账本

- Task 1：已完成，分支创建；Docker/Colima 未运行，现有 Node 26.0.0/Python 3.12.13/Chromium 可用。
- Task 2：四个旧版边界文件共 25 passed / 0.45s；六个独立 headless 音频输出通过格式/字节/峰值检查；真实旧导出包 12 个文件校验通过。详见 P0 evidence。
- Ruling：本轮只执行研究报告 P0 与 P1 准备，P1 功能不作为本轮实现目标；避免在未有真实音色基线前扩大合同。错误成本：下一 session 再执行 P1，而非本轮静默增加功能。
- Ruling：先做独立 headless host probe，不启动默认 VM/数据库。另对已知历史验收导出包做只读校验与重渲染；旧用户工程 DB/UI 与 pinned 容器重验仍明确列为未测，不以文件重开替代。错误成本：P0 只能报告测量子门通过。

- Ruling：首次严格 graph roundtrip 断言失败，经定位为 canonical JSON 按 ID 重排 notes/clips；保留 v1 算法，新增事件集合与音频对照，不伪装 graph/hash 完全不变。错误成本：P1 必须补 v2 稳定排序和实际缓存兼容检查。
- Task 3：古典/爵士与 legacy 兼容已写 ADR-019/Guide/Roadmap，详细 P1 计划完成；等待本轮独立审查。

- Task 4：最终 focused gate 25 passed/0.43s；Ruff/Node syntax/diff whitespace/7份本地链接检查通过；无生产音乐/DB/API/UI变更。
- Final review：一次独立只读审查，无 Critical/P0 阻塞。Important 为 P1 单琴导出缺少消费者接线；已在 P1 计划补 Task A2（v2计划/cursor/Bundle/Worker/read API/UI），保留 v1 七步恢复；这是计划修正，不宣称现有产品缺陷已修复。
- Final: minor (deferred)：历史 Master PCM 差异为本轮一次性只读比较，尚未并入可复用 CLI；JSON、两输入哈希及原文件已保留，后续 Task 可复查/集成。
- Ruling：本轮不把单琴导出产品修复临时塞入 P0；补齐 P1 明确依赖即可。错误成本：P1 A2 执行前仍不能用单琴完成旧七步导出；当前旧产品行为不变。
