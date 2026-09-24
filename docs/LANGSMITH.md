# 可选 LangSmith 追踪

LangSmith 是开发者查看运行与模型调用的辅助工具。Motif Forge 的业务事实、checkpoint、用量、恢复和内置 Graph 仍以本地 PostgreSQL 为准；追踪关闭或服务不可用不会使作品操作失败或触发业务重试。

## 开启

1. 在 LangSmith 创建 API Key，选择自己的 workspace。
2. 将以下配置写入仓库根目录**未跟踪的 `.env` 文件**，替换占位值。避免重复同名配置，不要粘贴到 README、聊天记录或前端变量中。

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=replace_with_your_private_key
LANGSMITH_PROJECT=motif-forge-local
```

3. 如果本地 API 镜像尚未包含追踪实现，先定向构建一次：

```bash
scripts/build_compose_images.sh api
```

4. 重启使容器读取环境：

```bash
scripts/stop_motif_forge.sh
scripts/start_motif_forge.sh
```

已有当前镜像时，之后切换追踪只需启停，不必重新构建。停止命令会停默认 Colima，其他共用项目也会暂停。

在作品中发起或继续一次任务，然后到对应 LangSmith Project 检查新记录。默认无 DeepSeek Key 时仍可能有 Graph trace，但不应期待真实模型调用记录。一个持久 Run 可能经历多次 start / resume；用 Run、Project 和 Thread 标识关联，不以一行 trace 的耗时代表整首音乐制作时间。

## 记录什么

- 受限的 Graph 操作名称、版本、Run / Project / Thread ID 与 service tag。
- 模型 transport attempt 的名称、耗时、finish reason、token 计数与脱敏错误。
- 原生 LangGraph 调用的追踪关系，供开发诊断。

Compose 只把追踪 Key 交给 API、Dispatcher 和 Resume Dispatcher。输入/输出在 SDK 与 Compose 边界隐藏；Prompt、模型推理、审批断言、checkpoint state、媒体、存储路径、Authorization 和响应正文不上传。

当前没有宣称 Celery、FFmpeg、Chromium 的完整分布式 trace。内置 Inspector 的安全持久证据与 LangSmith 的开发追踪是互补视图，不应互相替代。

## 关闭、密钥和费用

将 `LANGSMITH_TRACING=false`，或移除 Key，再按上面的正常启停命令重启。内置 Graph Inspector 继续可用。

泄露的 Key 应在 LangSmith 撤销并重新创建，不要继续复制使用。不要将密钥放入 `VITE_*` 或提交到 Git；检查配置时只确认“是否存在”，不要打印完整环境。

LangSmith 与 DeepSeek 分别计费，开启 tracing 本身不会增加一次 DeepSeek 调用。免费额度、保留期和超额计费可能变化，以 [LangSmith 官方价格与保留规则](https://docs.langchain.com/langsmith/pricing-plans)为准。启用前查看 workspace 的用量和支出限制；普通作品集演示无需开启追踪。
