import { useEffect, useMemo, useRef } from "react";

import type { WaveformPayload } from "./featurePayloads";

interface WaveformCanvasProps {
  waveform: WaveformPayload;
}

export function WaveformCanvas({ waveform }: WaveformCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const duration = waveform.source_frames / waveform.sample_rate_hz;
  const accessibleSummary = useMemo(
    () =>
      `${formatDuration(duration)}，${waveform.source_channels} 声道，${waveform.sample_rate_hz.toLocaleString()} Hz，${waveform.peaks.length} 个波形采样桶`,
    [duration, waveform],
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const draw = () => drawWaveform(canvas, waveform);
    draw();
    window.addEventListener("resize", draw);
    return () => window.removeEventListener("resize", draw);
  }, [waveform]);

  return (
    <section className="panel waveform-panel" aria-labelledby="waveform-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">SOURCE SIGNAL</p>
          <h2 id="waveform-title">导入波形</h2>
        </div>
        <span className="status-pill available">可用</span>
      </div>
      <div className="waveform-frame">
        <canvas ref={canvasRef} role="img" aria-label={`音频波形：${accessibleSummary}`} />
        <div className="waveform-ruler" aria-hidden="true">
          <span>0:00</span>
          <span>{formatDuration(duration / 2)}</span>
          <span>{formatDuration(duration)}</span>
        </div>
      </div>
      <p className="assistive-copy">{accessibleSummary}</p>
    </section>
  );
}

function drawWaveform(canvas: HTMLCanvasElement, waveform: WaveformPayload): void {
  const width = Math.max(canvas.clientWidth, 320);
  const height = Math.max(canvas.clientHeight, 220);
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.floor(width * ratio);
  canvas.height = Math.floor(height * ratio);
  const context = canvas.getContext("2d");
  if (!context) return;
  context.scale(ratio, ratio);
  context.clearRect(0, 0, width, height);

  const gradient = context.createLinearGradient(0, 0, width, height);
  gradient.addColorStop(0, "#62e6ff");
  gradient.addColorStop(0.58, "#9b7cff");
  gradient.addColorStop(1, "#ff65c3");
  context.strokeStyle = gradient;
  context.lineWidth = Math.max(1, 1.1 * ratio);
  context.globalAlpha = 0.92;
  context.beginPath();

  const center = height / 2;
  const amplitude = height * 0.42;
  const step = width / waveform.peaks.length;
  waveform.peaks.forEach((peak, index) => {
    const x = index * step;
    const top = center - (peak.maximum / 32768) * amplitude;
    const bottom = center - (peak.minimum / 32768) * amplitude;
    context.moveTo(x, top);
    context.lineTo(x, bottom);
  });
  context.stroke();

  context.globalAlpha = 0.35;
  context.strokeStyle = "#93a1b3";
  context.lineWidth = 1;
  context.beginPath();
  context.moveTo(0, center + 0.5);
  context.lineTo(width, center + 0.5);
  context.stroke();
}

function formatDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.max(0, Math.round(seconds % 60));
  return `${minutes}:${remainder.toString().padStart(2, "0")}`;
}
