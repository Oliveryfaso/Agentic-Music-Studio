import type { TimelineTrack } from "./timelineProjection";

export function TrackHeaders({ tracks }: { tracks: TimelineTrack[] }) {
  return (
    <div className="track-headers" aria-label="轨道列表">
      <div className="timeline-corner"><span>TRACKS</span></div>
      {tracks.map((track) => (
        <article className="track-header" key={track.trackId} title={track.name}>
          <strong>{track.name}</strong>
          <span>{track.role} · {track.gainDb > 0 ? "+" : ""}{track.gainDb} dB</span>
        </article>
      ))}
    </div>
  );
}
