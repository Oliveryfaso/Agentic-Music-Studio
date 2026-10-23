import type { TimelineTrack } from "./timelineProjection";

export function TrackHeaders({ tracks, selectedTrackId, onSelectTrack }: { tracks: TimelineTrack[]; selectedTrackId?: string; onSelectTrack?: (id:string) => void }) {
  return (
    <div className="track-headers" aria-label="轨道列表">
      <div className="timeline-corner"><span>TRACKS</span></div>
      {tracks.map((track,index) => (
        <article className="track-header" key={track.trackId} title={track.name}>
          <button type="button" aria-label={`选择音轨 ${String(index+1).padStart(2,"0")} ${track.name}`} aria-pressed={selectedTrackId === track.trackId} onClick={() => onSelectTrack?.(track.trackId)}><span>{String(index+1).padStart(2,"0")}</span> <strong>{track.name}</strong></button>
          <span>{track.role} · {track.gainDb > 0 ? "+" : ""}{track.gainDb} dB</span>
        </article>
      ))}
    </div>
  );
}
