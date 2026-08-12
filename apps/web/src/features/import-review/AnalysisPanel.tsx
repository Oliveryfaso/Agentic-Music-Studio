import type { AnalysisPayload } from "./featurePayloads";

interface AnalysisPanelProps {
  analysis: AnalysisPayload;
}

const BPM_CONFIDENCE_THRESHOLD = 0.65;
const KEY_CONFIDENCE_THRESHOLD = 0.25;

export function AnalysisPanel({ analysis }: AnalysisPanelProps) {
  const bpmLow = analysis.bpm === null || analysis.bpm_confidence < BPM_CONFIDENCE_THRESHOLD;
  const keyLow = analysis.key_tonic === null || analysis.key_confidence < KEY_CONFIDENCE_THRESHOLD;

  return (
    <section className="panel analysis-panel" aria-labelledby="analysis-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">DETERMINISTIC ANALYSIS</p>
          <h2 id="analysis-title">音乐分析</h2>
        </div>
        <span className={`status-pill ${bpmLow || keyLow ? "warning" : "available"}`}>
          {bpmLow || keyLow ? "需确认" : "可信"}
        </span>
      </div>

      <div className="metric-grid">
        <Metric label="BPM" value={analysis.bpm?.toFixed(1) ?? "未知"} confidence={analysis.bpm_confidence} low={bpmLow} />
        <Metric
          label="调性"
          value={analysis.key_tonic ? `${analysis.key_tonic} ${analysis.key_mode === "major" ? "大调" : "小调"}` : "未知"}
          confidence={analysis.key_confidence}
          low={keyLow}
        />
        <div className="metric-card quiet">
          <span>分析范围</span>
          <strong>{analysis.analyzed_seconds.toFixed(1)} s</strong>
          <small>{analysis.analysis_version}</small>
        </div>
      </div>

      {(bpmLow || keyLow) && (
        <div className="notice warning-notice" role="status">
          <span className="notice-icon" aria-hidden="true">!</span>
          <div>
            <strong>低置信度结果不会自动用于对齐</strong>
            <p>请在对应的导入 Run 中确认或覆盖 BPM / 调性；规则节点会在确认前保持原始音频不变。</p>
          </div>
        </div>
      )}
    </section>
  );
}

function Metric({ label, value, confidence, low }: { label: string; value: string; confidence: number; low: boolean }) {
  const percentage = Math.round(confidence * 100);
  return (
    <div className={`metric-card ${low ? "is-low" : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <div className="confidence-row">
        <span>置信度</span>
        <b>{percentage}%</b>
      </div>
      <div className="confidence-track" aria-label={`${label}置信度 ${percentage}%`}>
        <span style={{ width: `${percentage}%` }} />
      </div>
    </div>
  );
}
