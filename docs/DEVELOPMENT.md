# 开发、验证与本地排障

正常使用先看 [README 的一键启动](../README.md#快速开始)。这份文档面向修改代码、复现界面和排查环境的开发者。

## 最小开发循环

前端改动不需要重建 Docker。仓库使用现有 npm lockfile，React + TypeScript + Vite：

```bash
npm ci
npm run dev:web
```

另一个终端运行：

```bash
npm run test:web
npm run build:web
```

正式页面通过现有 API 读取数据。只启动 Vite 不会自动提供数据库或音频服务；需要真实创作时使用一键启动，或者显式启动同版本 Compose。

## 界面验证与截图

下面的脚本使用仓库已有的 Playwright / Vite，在独立的 `127.0.0.1:5178` 上渲染真实前端，通过拦截 HTTP 提供隔离示例数据。它不接触实际 API、Docker、模型或用户作品：

```bash
node scripts/run_product_ui_smoke.mjs
# 同时更新 README 中明确标注的演示截图
node scripts/run_product_ui_smoke.mjs --docs
```

需要本机已有 Playwright Chromium；缺少时可用 `npx playwright install chromium` 安装。浏览器缓存可通过 `PLAYWRIGHT_BROWSERS_PATH` 指定。脚本检查桌面/手机、关键审批门、空/加载/错误/部分可用状态、主导航、页面溢出与客户端错误，结束后关闭本次浏览器和 Vite。截图写入被忽略的 `output/playwright/light-studio/`；`--docs` 只将四张精选截图写入 `docs/images/`。

这些检查只能证明呈现与交互，不能证明模型生成、音质、Worker 或真实 PostgreSQL 的新一轮端到端成功。需要真实流程验收时使用相应阶段脚本；不要为了界面改动反复运行整套服务故障矩阵。

## Python 与外置存储

宿主机后端开发需要 Python 3.12 和 [uv](https://docs.astral.sh/uv/)。当前 macOS 外置盘开发约定：媒体与可移动缓存放仓库旁，Python 环境放内部 APFS 临时目录，以避开 exFAT 的 AppleDouble / wheel RECORD 问题。

```bash
export MOTIF_FORGE_DEV_STORAGE_ROOT="$(cd .. && pwd -P)/.motif-forge-data"
scripts/bootstrap_external_storage.sh "$MOTIF_FORGE_DEV_STORAGE_ROOT"
export npm_config_cache="$MOTIF_FORGE_DEV_STORAGE_ROOT/cache/npm"
export PLAYWRIGHT_BROWSERS_PATH="$MOTIF_FORGE_DEV_STORAGE_ROOT/cache/playwright"
export MOTIF_FORGE_ARTIFACT_ROOT="$MOTIF_FORGE_DEV_STORAGE_ROOT/artifacts"
export MOTIF_FORGE_TEMP_ROOT="$MOTIF_FORGE_DEV_STORAGE_ROOT/tmp"
export MOTIF_FORGE_STORAGE_PROFILE=lean
export UV_PROJECT_ENVIRONMENT=/private/tmp/motif-forge-venv
export UV_CACHE_DIR="$MOTIF_FORGE_DEV_STORAGE_ROOT/cache/uv"
export UV_LINK_MODE=copy
uv sync --dev --frozen
uv run pytest
uv run ruff check .
uv run mypy
```

这些路径是已验证的 macOS 开发约定，不是产品硬编码。其他系统应使用自己的可写路径；不要把 PostgreSQL 数据目录直接挂载到 exFAT。若 Chromium 无法从外置盘执行，仅将浏览器缓存移回内部磁盘即可。

`bootstrap_external_storage.sh` 创建所需目录并验证可写性，不覆盖 `.env` 或删除现有数据。默认 Lean 配额为全局 10 GiB、每项目 2 GiB、临时数据 2 GiB；原始导入、当前版本依赖和选定最终 Master 不属于普通清理目标。缓存回收与重建边界见 [存储合同](PROJECT_GUIDE.md)。

## 真实服务与验收

优先用 `scripts/start_motif_forge.sh` 保持 API、Dispatcher 和 Worker 同版本。只在受影响 target 的依赖、运行接线或明确集成验收需要时构建：

```bash
scripts/build_compose_images.sh api
scripts/build_compose_images.sh media-worker
scripts/build_compose_images.sh render-worker
```

这三条是可选择的构建入口，不要求每次全部运行。构建脚本为 macOS 外置盘复制一个不带扩展属性的受限临时 context，再构建与清理该 context，不删除仓库源码。

服务就绪检查：

```bash
scripts/check_compose_runtime.sh
```

API 提供 `/health/live` 与 `/health/ready`；后者检查真实依赖，未就绪返回 503，不暴露连接密钥。

真实 PostgreSQL 测试需显式指定测试连接；未提供时会跳过，不能用 SQLite 代替：

```bash
export MOTIF_FORGE_TEST_POSTGRES_DSN='postgresql://motif_forge:motif_forge@localhost:5432/motif_forge'
scripts/check_postgres_integration.sh
```

该命令使用本地开发数据库执行集成测试，不要指向他人或生产数据库。先确认 Compose 已启动且迁移完成。

音频回归入口为 `npm run test:audio`；真实 Chromium 渲染边界为 `scripts/run_audio_spike.sh`。历史完整导出入口 `scripts/check_s1.sh` 还要求显式 DSN、Artifact Root、Render URL 与人工审批参数，详见脚本及阶段计划。不要把历史固定基线当作所有风格的音质结论。

付费 DeepSeek 验收的入口是 `scripts/run_s2_live_deepseek_smoke.py`：它检查显式 opt-in、模型、单次尝试、token 预算及运行环境，运行前必须阅读 guard 和对应计划。常规单元测试使用 fake Provider，不产生模型费用。可选追踪见 [LangSmith](LANGSMITH.md)。

## 常见问题

### 端口 8090 已占用

先看占用者，不要直接停止全部 Docker 容器：

```bash
docker ps --format 'table {{.Names}}\t{{.Ports}}'
lsof -nP -iTCP:8090 -sTCP:LISTEN
```

旧工作树的 Render Worker 可能仍在运行。核对容器的 Compose 项目与工作目录，只处理确认属于本项目且不再使用的实例。当前作品数据库卷与媒体目录不要删除。

### Colima 显示运行，但 Docker 不响应

确认没有其他工作依赖当前虚拟机后，执行：

```bash
colima stop
scripts/start_motif_forge.sh
```

这是重启，不是删除虚拟机。默认停止脚本同样会停默认 Colima；共享实例会影响其他项目。

### 镜像下载失败或代理不可用

宿主机终端代理不等于 Colima 内 Docker daemon 的代理。按 [Docker 官方说明](https://docs.docker.com/engine/daemon/proxy/)配置 daemon，不把代理凭据提交到仓库。先确认 `docker compose version` 和 `docker buildx version` 可用。

### 页面能打开，但没有作品或音频

- 检查 API readiness 和页面错误信息，不把加载失败理解成作品被删除。
- 确认原存储盘已连接、配置仍指向正确目录。
- 音频有可用、已回收、重建中、缺失四种状态；只对支持的派生产物提供恢复。
- Studio 播放的是已渲染的保存版本，未保存草稿不会即时改变它。

## 数据与资源纪律

源码变化优先走宿主机测试；不因为每次 UI 改动构建容器。不运行广泛的 image / volume / system prune。清理前先确认归属和精确路径，保留数据库卷、素材、正式导出与当前镜像；共享 BuildKit 无法证明归属时不清理。内容哈希只服务已有协议完整性 / 幂等需求，不用于例行核对源码或文档。

开发前阅读顺序仍是：决策记录 → 最终产品合同 → 实施状态 → 路线 → 当前切片计划。正式进展与证据写入实施状态、技术演进，不在 README 中堆积历史阶段日志。
