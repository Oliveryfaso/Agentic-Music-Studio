import type { ArrangementIR } from "../../shared/openapi";

export interface TimelineClip {
  clipId: string;
  startTick: number;
  endTick: number;
  startPixels: number;
  widthPixels: number;
  kind: "note" | "audio";
}

export interface TimelineTrack {
  trackId: string;
  name: string;
  role: string;
  gainDb: number;
  clips: TimelineClip[];
}

export interface TimelineSection {
  sectionId: string;
  label: string;
  startTick: number;
  endTick: number;
  startPixels: number;
  widthPixels: number;
  energy: number;
}

export interface TimelineProjection {
  ticksPerBar: number;
  totalBars: number;
  widthPixels: number;
  durationSeconds: number;
  tracks: TimelineTrack[];
  sections: TimelineSection[];
  tickToPixels: (tick: number) => number;
  tickToSeconds: (tick: number) => number;
  secondsToPixels: (seconds: number) => number;
}

export function projectTimeline(ir: ArrangementIR, pixelsPerBar = 112): TimelineProjection {
  const meter = ir.time_signature_map?.[0] ?? { numerator: 4, denominator: 4 };
  const bpm = ir.tempo_map?.[0]?.bpm ?? 120;
  const ticksPerBar = ir.ppq * meter.numerator * (4 / meter.denominator);
  const lastSectionTick = Math.max(0, ...ir.sections.map((section) => section.end_tick));
  const lastClipTick = Math.max(0, ...ir.tracks.flatMap((track) => track.clips.map((clip) => clip.start_tick + clip.duration_tick)));
  const maxTick = Math.max(ticksPerBar, lastSectionTick, lastClipTick);
  const totalBars = Math.max(1, Math.ceil(maxTick / ticksPerBar));
  const widthPixels = totalBars * pixelsPerBar;
  const tickToPixels = (tick: number) => Math.max(0, tick) / ticksPerBar * pixelsPerBar;
  const tickToSeconds = (tick: number) => Math.max(0, tick) / ir.ppq * (60 / bpm);
  const secondsToPixels = (seconds: number) => tickToPixels(Math.max(0, seconds) * bpm / 60 * ir.ppq);

  return {
    ticksPerBar,
    totalBars,
    widthPixels,
    durationSeconds: tickToSeconds(maxTick),
    tickToPixels,
    tickToSeconds,
    secondsToPixels,
    sections: ir.sections.map((section) => ({
      sectionId: section.section_id,
      label: section.label,
      startTick: section.start_tick,
      endTick: section.end_tick,
      startPixels: tickToPixels(section.start_tick),
      widthPixels: Math.max(2, tickToPixels(section.end_tick - section.start_tick)),
      energy: section.energy,
    })),
    tracks: ir.tracks.map((track) => ({
      trackId: track.track_id,
      name: track.name,
      role: track.role,
      gainDb: track.gain_db,
      clips: [...track.clips].sort((left, right) => left.start_tick - right.start_tick).map((clip) => ({
        clipId: clip.clip_id,
        startTick: clip.start_tick,
        endTick: clip.start_tick + clip.duration_tick,
        startPixels: tickToPixels(clip.start_tick),
        widthPixels: Math.max(3, tickToPixels(clip.duration_tick)),
        kind: clip.clip_type,
      })),
    })),
  };
}
