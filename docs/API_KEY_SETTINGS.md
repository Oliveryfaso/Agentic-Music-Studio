# API Key 设置（本机）

界面入口：主导航 **设置**；Studio 提示模型未配置时也可点 **配置 API Key**。

在运行 Motif 的电脑终端进入仓库后：

```sh
python3 scripts/configure_deepseek.py
```

隐藏输入只写入用户私有配置文件 `~/.config/motif-forge/deepseek.env`（设置绝对路径 XDG_CONFIG_HOME 时遵循该目录）。不写外置仓库，避免不支持 POSIX 权限的盘暴露 Secret；目录必须当前用户持有且 0700、文件原子替换且 0600，在写 Key 前验证实际权限。不向服务发送请求，不修改 `.env` 或 LangSmith。格式/权限/符号链接检查失败时退出，不打印密钥。再次运行可在确认后替换；不要把 Key 放进 `VITE_*`、URL、shell 参数或公开诊断输出。

文件保存后**尚未生效**。完成/取消原实例任务，使用原启动/停止方式正常关闭，再沿用完全相同的 runtime、端口和存储参数，加 `--enable-deepseek` 启动。例如个人 Beta：

```sh
scripts/start_motif_forge.sh --personal-beta --enable-deepseek
```

普通本地档位同样支持 `scripts/start_motif_forge.sh --enable-deepseek`。启动器只在显式选项存在时追加私有 env 文件和最后一层 `compose.deepseek.yaml`，把 Key 交给 API 与 resume-dispatcher；其余服务保留空 Key。Beta 其余配置仍来自 `.env.example`。未加选项时继续默认禁用；只填 `.env` 会被 Compose 的空值覆盖。启动器会先清除继承的 `DEEPSEEK_API_KEY`，显式启用时只从刚校验的私有文件注入，避免 shell 旧值切换到其他账户。不要运行会打印完整 Secret 的 `docker compose config` 或分享 `docker inspect`。

不允许把现有唯一服务的改配当作无副作用操作；本补丁交付不自动停止、重建、重启或启用任何实例。服务需要同时更新为本批 API/前端代码后，设置页才有新接口。镜像由主线按现有发布流程更新，不跳过 pin/迁移/所有权检查。

设置页 **刷新配置状态** 只查询本地 API；显示 API 当前进程是否有 Key。**测试连接** 必须显式点击，只由后端向固定官方 `https://api.deepseek.com/models` 发一次 GET 鉴权请求（无生成、无重试/重定向、无作品内容）。失败仅返回固定错误码；远端正文、异常和 Key 不回传或记日志。成功只表示本次鉴权/模型列表接口可达，不证明指定模型生成、余额或另一个 Worker 配置。结果不持久化，刷新或重开回到“已配置 · 未测试”，不拿旧检测冒充新配置已验证。

实际自然语言任务可能计费，并发送描述和必要的结构化乐谱上下文给 DeepSeek；不发送原始音频。连接检查不会开启 LangSmith，也不会触发付费生成。官方模型列表接口参考：[DeepSeek Lists Models](https://api-docs.deepseek.com/api/list-models/)。

停用：关闭同一实例后，不带 `--enable-deepseek` 重启。清除本机文件：

```sh
python3 scripts/configure_deepseek.py --clear
```

清除时复用父目录 0700/所有权/拒绝符号链接规则；目录不存在时保持幂等。删除文件不会清除运行中进程已读取的 Key；需正常重启同一实例。删除文件不等于吊销，如有泄露须到提供商撤销。原作品与已保存试听保留。此档位仍是本机环境配置，不是公共托管的多用户密钥库。
