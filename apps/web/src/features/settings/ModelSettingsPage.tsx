import { useMutation, useQuery } from "@tanstack/react-query";
import { checkModelConnection, readModelSettings } from "./modelSettingsApi";

const labels = {not_configured:"未配置", configured:"已配置 · 未测试", connected:"连接成功", failed:"连接失败"};
const errors = {
  AUTHENTICATION_FAILED:"密钥无效或没有访问权限。请在本机重新配置并重启同一实例。",
  PROVIDER_UNAVAILABLE:"服务暂不可用或限制访问，请稍后手动重试。",
  CONNECTION_FAILED:"无法连接 DeepSeek，请检查本机网络后重试。",
  INVALID_RESPONSE:"DeepSeek 返回格式异常，请稍后重试。",
  ENDPOINT_UNSUPPORTED:"当前配置的服务地址不支持此检测；仅检测 DeepSeek 官方地址。",
};

export function ModelSettingsPage() {
  const config = useQuery({queryKey:["model-settings"],queryFn:readModelSettings,retry:false,staleTime:0});
  const check = useMutation({mutationFn:checkModelConnection,retry:false});
  const value = check.data ?? config.data;
  const busy = config.isFetching || check.isPending;
  const failed = config.isError || check.isError;
  return <section className="portfolio-page model-settings" aria-labelledby="model-settings-title">
    <header className="page-heading"><div><h1 id="model-settings-title">设置</h1></div><a href="/">返回作品</a></header>
    <section aria-labelledby="model-provider-title">
      <h2 id="model-provider-title">DeepSeek API Key</h2>
      <p>自然语言编配与修改。按实际用量可能产生费用；作品浏览、已保存试听和规则伴奏无需 Key。</p>
      <div className="model-settings-status" role="status" aria-live="polite">
        <strong>{config.isError?"无法读取配置状态":check.isPending?"正在测试连接…":check.isError?"检测未完成":value?labels[value.state]:"正在读取配置…"}</strong>
        {value?.state==="connected"&&!failed&&<p>本次鉴权通过；未验证生成能力、余额或 Worker 配置。刷新后需重新检测。</p>}
        {value?.state==="failed"&&!failed&&value.error_code&&<p>{errors[value.error_code]}</p>}
        {failed&&<p>请确认本地服务已更新并运行，再重试。配置文件不会因此被清除。</p>}
        <p>此处读取当前 API 进程配置，保存文件后需重启同一实例才会生效。</p>
      </div>
      <div className="model-settings-actions">
        <button type="button" disabled={busy||config.isError||!config.data||config.data.state==="not_configured"} onClick={()=>check.mutate()}>测试连接</button>
        <button type="button" disabled={busy} onClick={()=>{check.reset();void config.refetch();}}>刷新配置状态</button>
      </div>
      <p>测试仅发送 Key 到 DeepSeek 官方模型列表接口，不发送作品或生成音乐。不会自动测试。</p>
    </section>
    <section aria-labelledby="configure-key-title">
      <h2 id="configure-key-title">配置与启用</h2>
      <ol>
        <li>在运行 Motif 的电脑上，进入项目目录后执行：<pre><code>python3 scripts/configure_deepseek.py</code></pre>按提示隐藏输入 Key。密钥仅保存到本机私有文件，网页不会读取或显示。</li>
        <li>正常关闭原实例，再沿用原启动参数和数据目录，追加 <code>--enable-deepseek</code>。个人 Beta 示例：<pre><code>scripts/start_motif_forge.sh --personal-beta --enable-deepseek</code></pre>不要同时启动第二个实例。已有任务请先完成或取消；Key 文件保存不等于运行服务已更新。</li>
        <li>返回此页，先「刷新配置状态」，再按需「测试连接」。</li>
      </ol>
      <details><summary>数据、费用与安全</summary>
        <p>启用后，主动发起自然语言生成或修改会将描述、必要的结构化乐谱上下文发送至 DeepSeek，并可能计费；不发送原始音频。连接成功不代表生成可用。LangSmith 追踪不会因此开启。</p>
        <p>默认 Compose 会清空 Key，单填 .env 不会启用。不要把 Key 放入 VITE_*、网址或命令参数，也不要分享私有环境文件或包含完整配置的诊断输出。</p>
      </details>
    </section>
    <details><summary>停用或清除 Key</summary>
      <p>沿用原实例参数正常关闭后，不带 --enable-deepseek 重启即可停用。要同时清除本机文件，执行：</p>
      <pre><code>python3 scripts/configure_deepseek.py --clear</code></pre>
      <p>仅删除文件不会移除运行中服务已读取的 Key；需重启同一实例。清除不等于吊销，可到 DeepSeek 账户撤销密钥。作品与已保存音频不受影响。</p>
    </details>
  </section>;
}
