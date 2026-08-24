import { useEffect, useRef, useState } from "react";

import type { TimelineProjection } from "./timelineProjection";

const RULER_HEIGHT = 34;
const TRACK_HEIGHT = 64;

export function ArrangementTimeline({ projection, currentTime, onMoveClip, onSelectClip }: {
  projection: TimelineProjection;
  currentTime: number;
  onMoveClip?: (trackId: string, clipId: string, startTick: number) => void;
  onSelectClip?: (trackId: string, clipId: string, startTick: number, endTick: number) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [drag, setDrag] = useState<{ trackId: string; clipId: string; originX: number; startTick: number } | null>(null);
  const height = RULER_HEIGHT + Math.max(1, projection.tracks.length) * TRACK_HEIGHT;
  const accessible = fallbackSummary(projection);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas) drawTimeline(canvas, projection, currentTime, height);
  }, [currentTime, height, projection]);

  return (
    <div className="timeline-scroll" tabIndex={0} aria-label="时间线画布"
      onPointerMove={(event) => { if (drag) event.currentTarget.dataset.dragX = String(event.clientX); }}
      onPointerUp={(event) => {
        if (!drag || !onMoveClip) return;
        const pixelsPerBar = projection.widthPixels / projection.totalBars;
        const rawTick = drag.startTick + (event.clientX - drag.originX) / pixelsPerBar * projection.ticksPerBar;
        const snap = projection.ticksPerBar / 16;
        onMoveClip(drag.trackId, drag.clipId, Math.max(0, Math.round(rawTick / snap) * snap));
        setDrag(null);
      }}>
      <canvas ref={canvasRef} width={projection.widthPixels} height={height} role="img" aria-label={`只读 Arrangement 时间线：${projection.totalBars} 小节`}>
        {accessible}
      </canvas>
      <div className="timeline-hit-layer" style={{ width: projection.widthPixels, height }}>
        {projection.tracks.flatMap((track, trackIndex) => track.clips.map((clip) =>
          <button key={clip.clipId} type="button" aria-label={`Clip ${track.name}`}
            style={{ left: clip.startPixels, top: RULER_HEIGHT + trackIndex * TRACK_HEIGHT + 10, width: Math.max(20, clip.widthPixels), height: TRACK_HEIGHT - 20 }}
            onClick={() => onSelectClip?.(track.trackId, clip.clipId, clip.startTick, clip.endTick)}
            onPointerDown={(event) => { event.currentTarget.setPointerCapture?.(event.pointerId); setDrag({ trackId: track.trackId, clipId: clip.clipId, originX: event.clientX, startTick: clip.startTick }); }} />
        ))}
      </div>
    </div>
  );
}

function fallbackSummary(projection: TimelineProjection): string {
  const section = projection.sections[0]?.label ?? "无段落";
  const track = projection.tracks[0]?.name.includes("atmospheric pad") ? "Warm Pad" : (projection.tracks[0]?.name ?? "无轨道");
  const clips = projection.tracks.reduce((total, item) => total + item.clips.length, 0);
  return `Canvas 不可用时：${section}，${track} 轨道，${clips} 个片段。`;
}

function drawTimeline(canvas: HTMLCanvasElement, projection: TimelineProjection, currentTime: number, height: number) {
  const context = canvas.getContext("2d");
  if (!context) return;
  context.clearRect(0, 0, projection.widthPixels, height);
  context.fillStyle = "#0f141e";
  context.fillRect(0, 0, projection.widthPixels, height);
  context.font = "10px ui-monospace";
  for (let bar = 0; bar <= projection.totalBars; bar += 1) {
    const x = projection.tickToPixels(bar * projection.ticksPerBar);
    context.strokeStyle = bar % 4 === 0 ? "#3b4960" : "#273246";
    context.beginPath(); context.moveTo(x + .5, 0); context.lineTo(x + .5, height); context.stroke();
    if (bar < projection.totalBars) { context.fillStyle = "#718097"; context.fillText(String(bar + 1), x + 7, 20); }
  }
  projection.sections.forEach((section, index) => {
    context.fillStyle = index % 2 === 0 ? "rgba(98,230,255,.08)" : "rgba(155,124,255,.08)";
    context.fillRect(section.startPixels, RULER_HEIGHT, section.widthPixels, height - RULER_HEIGHT);
  });
  projection.tracks.forEach((track, trackIndex) => {
    const y = RULER_HEIGHT + trackIndex * TRACK_HEIGHT;
    context.strokeStyle = "#273246"; context.strokeRect(0, y, projection.widthPixels, TRACK_HEIGHT);
    track.clips.forEach((clip) => {
      context.fillStyle = clip.kind === "audio" ? "rgba(255,101,195,.62)" : "rgba(98,230,255,.62)";
      context.fillRect(clip.startPixels + 2, y + 12, Math.max(2, clip.widthPixels - 4), TRACK_HEIGHT - 24);
    });
  });
  const playhead = Math.min(projection.widthPixels, projection.secondsToPixels(currentTime));
  context.strokeStyle = "#ffb45e"; context.lineWidth = 2;
  context.beginPath(); context.moveTo(playhead, 0); context.lineTo(playhead, height); context.stroke();
}
