import { RefObject } from "react";

export function Transport({
  audioRef, src, duration, currentTime, isPlaying, mediaError, onPlay, onPause, onStop, onSeek, mediaProps,
}: {
  audioRef: RefObject<HTMLAudioElement | null>;
  src: string;
  duration: number;
  currentTime: number;
  isPlaying: boolean;
  mediaError: boolean;
  onPlay: () => Promise<void>;
  onPause: () => void;
  onStop: () => void;
  onSeek: (seconds: number) => void;
  mediaProps: { onTimeUpdate: () => void; onEnded: () => void; onError: () => void };
}) {
  return (
    <section className="studio-transport" aria-label="播放控制">
      <audio ref={audioRef} src={src} preload="metadata" {...mediaProps} />
      <div className="transport-buttons">
        {isPlaying
          ? <button className="primary-button" type="button" onClick={onPause}>暂停</button>
          : <button className="primary-button" type="button" onClick={() => void onPlay()}>播放</button>}
        <button className="secondary-inline" type="button" onClick={onStop}>停止</button>
      </div>
      <label className="transport-seek"><span className="sr-only">播放位置</span><input aria-label="播放位置" type="range" min="0" max={Math.max(duration, 0.01)} step="0.01" value={Math.min(currentTime, duration)} onChange={(event) => onSeek(Number(event.target.value))} /></label>
      <output>{formatTime(currentTime)} / {formatTime(duration)}</output>
      {mediaError && <p className="field-error" role="alert">MP3 无法播放</p>}
    </section>
  );
}

function formatTime(seconds: number): string {
  const safe = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
  return `${Math.floor(safe / 60)}:${Math.floor(safe % 60).toString().padStart(2, "0")}`;
}
