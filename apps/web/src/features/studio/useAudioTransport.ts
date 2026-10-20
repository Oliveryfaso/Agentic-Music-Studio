import { useCallback, useEffect, useRef, useState } from "react";

export function useAudioTransport(durationSeconds: number, sourceIdentity: string | null = null) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const frameRef = useRef<number | null>(null);
  const generation = useRef(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [mediaError, setMediaError] = useState(false);

  const cancelFrame = useCallback(() => {
    if (frameRef.current !== null) {
      cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    }
  }, []);

  const followClock = useCallback(() => {
    const audio = audioRef.current;
    frameRef.current = null;
    if (!audio || audio.paused || audio.ended) return;
    setCurrentTime(audio.currentTime);
    frameRef.current = requestAnimationFrame(followClock);
  }, []);

  const play = useCallback(async () => {
    const audio = audioRef.current;
    if (!audio) return;
    const attempt = ++generation.current;
    setMediaError(false);
    try {
      await audio.play();
      if (attempt !== generation.current || audioRef.current !== audio) return;
      setIsPlaying(!audio.paused);
      cancelFrame();
      if (!audio.paused) frameRef.current = requestAnimationFrame(followClock);
    } catch {
      if (attempt !== generation.current || audioRef.current !== audio) return;
      setMediaError(true);
      setIsPlaying(false);
      cancelFrame();
    }
  }, [cancelFrame, followClock]);

  const pause = useCallback(() => {
    ++generation.current;
    audioRef.current?.pause();
    setIsPlaying(false);
    cancelFrame();
  }, [cancelFrame]);

  const stop = useCallback(() => {
    pause();
    if (audioRef.current) audioRef.current.currentTime = 0;
    setCurrentTime(0);
  }, [pause]);

  const seek = useCallback((seconds: number) => {
    const bounded = Math.min(Math.max(0, seconds), durationSeconds);
    if (audioRef.current) audioRef.current.currentTime = bounded;
    setCurrentTime(bounded);
  }, [durationSeconds]);

  useEffect(() => {
    ++generation.current;
    const audio = audioRef.current;
    audio?.pause();
    if (audio) audio.currentTime = 0;
    setCurrentTime(0);
    setIsPlaying(false);
    setMediaError(false);
    cancelFrame();
    return () => {
      ++generation.current;
      cancelFrame();
      audio?.pause();
    };
  }, [sourceIdentity, cancelFrame]);

  return {
    audioRef, isPlaying, currentTime, mediaError, play, pause, stop, seek,
    mediaProps: {
      onTimeUpdate: () => setCurrentTime(audioRef.current?.currentTime ?? 0),
      onPause: () => { ++generation.current; setIsPlaying(false); cancelFrame(); },
      onPlay: () => {
        const audio = audioRef.current;
        if (!audio || audio.paused) return;
        audio.ownerDocument.querySelectorAll("audio").forEach(other => { if (other !== audio) other.pause(); });
        setIsPlaying(true);
        setMediaError(false);
        cancelFrame();
        frameRef.current = requestAnimationFrame(followClock);
      },
      onEmptied: () => { ++generation.current; setCurrentTime(0); setIsPlaying(false); setMediaError(false); cancelFrame(); },
      onEnded: stop,
      onError: () => { ++generation.current; setMediaError(true); setIsPlaying(false); cancelFrame(); },
    },
  };
}
