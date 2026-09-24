/** Decorative score, not a visualization of generated audio or live progress. */
export function MotifScore() {
  return <div className="motif-score" aria-hidden="true">
    <div className="score-caption"><span>A LITTLE IDEA, IN MOTION</span><span>01 — 04</span></div>
    <svg viewBox="0 0 440 184" fill="none">
      <path d="M0 28H440M0 60H440M0 92H440M0 124H440M0 156H440M44 12V172M132 12V172M220 12V172M308 12V172M396 12V172" stroke="currentColor" strokeOpacity=".12" />
      <g fill="var(--accent)"><rect x="18" y="49" width="56" height="18" rx="4"/><rect x="83" y="33" width="39" height="18" rx="4"/><rect x="137" y="65" width="78" height="18" rx="4"/><rect x="230" y="49" width="55" height="18" rx="4"/><rect x="304" y="17" width="103" height="18" rx="4"/></g>
      <g fill="var(--violet)" opacity=".6"><rect x="18" y="105" width="104" height="18" rx="4"/><rect x="137" y="121" width="78" height="18" rx="4"/><rect x="230" y="105" width="177" height="18" rx="4"/></g>
      <g fill="var(--warm)" opacity=".7"><rect x="18" y="153" width="22" height="6" rx="3"/><rect x="62" y="153" width="22" height="6" rx="3"/><rect x="106" y="153" width="22" height="6" rx="3"/><rect x="150" y="153" width="22" height="6" rx="3"/><rect x="194" y="153" width="22" height="6" rx="3"/><rect x="238" y="153" width="22" height="6" rx="3"/><rect x="282" y="153" width="22" height="6" rx="3"/><rect x="326" y="153" width="22" height="6" rx="3"/><rect x="370" y="153" width="22" height="6" rx="3"/></g>
    </svg>
    <div className="score-legend"><span>动机</span><span>和声</span><span>节奏</span><em>留一点空间，给下一个灵感。</em></div>
  </div>;
}
