import { useCallback, useEffect, useRef, useState } from "react";

export function useAudioTransport(durationSeconds: number) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const frameRef = useRef<number | null>(null);
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
    if (!audio) return;
    setCurrentTime(audio.currentTime);
    frameRef.current = requestAnimationFrame(followClock);
  }, []);

  const play = useCallback(async () => {
    const audio = audioRef.current;
    if (!audio) return;
    setMediaError(false);
    try {
      await audio.play();
      setIsPlaying(true);
      cancelFrame();
      frameRef.current = requestAnimationFrame(followClock);
    } catch {
      setMediaError(true);
      setIsPlaying(false);
    }
  }, [cancelFrame, followClock]);

  const pause = useCallback(() => {
    audioRef.current?.pause();
    setIsPlaying(false);
    cancelFrame();
  }, [cancelFrame]);

  const stop = useCallback(() => {
    const audio = audioRef.current;
    if (audio) {
      audio.pause();
      audio.currentTime = 0;
    }
    setCurrentTime(0);
    setIsPlaying(false);
    cancelFrame();
  }, [cancelFrame]);

  const seek = useCallback((seconds: number) => {
    const bounded = Math.min(Math.max(0, seconds), durationSeconds);
    if (audioRef.current) audioRef.current.currentTime = bounded;
    setCurrentTime(bounded);
  }, [durationSeconds]);

  useEffect(() => () => {
    cancelFrame();
    audioRef.current?.pause();
  }, [cancelFrame]);

  return {
    audioRef,
    isPlaying,
    currentTime,
    mediaError,
    play,
    pause,
    stop,
    seek,
    mediaProps: {
      onTimeUpdate: () => setCurrentTime(audioRef.current?.currentTime ?? 0),
      onEnded: stop,
      onError: () => { setMediaError(true); setIsPlaying(false); cancelFrame(); },
    },
  };
}
