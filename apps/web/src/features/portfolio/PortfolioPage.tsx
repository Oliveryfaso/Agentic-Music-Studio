import { navigate } from "../../app/routes";
import { MotifScore } from "../../app/MotifScore";

const pillars = [
  ["01", "LangGraph Parent Graph", "一个可恢复 Parent Graph 统一生成、审批、物化、渲染与导出，不让模型直接写 Revision。"],
  ["02", "Human approval gate", "结构化 Plan 必须经人类审批；拒绝、重规划、取消和重试都成为持久事实。"],
  ["03", "Deterministic core", "模型只负责提议；ArrangementIR、编辑命令、音频任务和 Bundle 由确定性代码编译。"],
  ["04", "Recovery & cost", "PostgreSQL checkpoint、outbox 与幂等键让 Run 可恢复；模型请求和 token 预算进入账本。"],
  ["05", "Critic & bounded Repair", "证据 Critic 比较结构事实；每个候选最多一次局部 Repair，随后由用户做 A/B 选择。"],
] as const;

export function PortfolioPage() {
  return (
    <section className="portfolio-page" aria-labelledby="portfolio-title">
      <header className="portfolio-hero">
        <div>
          <p className="eyebrow">MEET MOTIF FORGE</p>
          <h1 id="portfolio-title">与 Agent 合作，<br />把音乐做完整。</h1>
          <p>从一句创作想法到多轨作品，让规划、试听、选择和修改连在一起。你能看见 Agent 做了什么，也能在关键时刻决定下一步。</p>
          <div className="portfolio-actions">
            <button className="primary-button" type="button" onClick={() => navigate({ name: "home" })}>进入工作台</button>
            <button className="secondary-inline" type="button" onClick={() => navigate({ name: "evaluation" })}>查看 Eval 证据</button>
          </div>
        </div>
        <MotifScore />
      </header>

      <div className="portfolio-pillars">
        {pillars.map(([number, title, copy]) => (
          <article className="portfolio-card" key={title}><span>{number}</span><h2>{title}</h2><p>{copy}</p></article>
        ))}
      </div>

      <section className="portfolio-architecture">
        <div><p className="eyebrow">PRODUCT LOOP</p><h2>Agent 提议，人类定夺，代码兑现。</h2></div>
        <ol>
          <li><b>Brief</b><span>约束与意图</span></li><li><b>Plan</b><span>模型结构提案</span></li>
          <li><b>Approval</b><span>HITL 中断点</span></li><li><b>Revision</b><span>确定性 IR</span></li>
          <li><b>Studio</b><span>局部编辑</span></li><li><b>Export</b><span>7 步媒体流水线</span></li>
        </ol>
      </section>
    </section>
  );
}
