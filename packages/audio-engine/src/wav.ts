export function encodeStereoPcm16(buffer: AudioBuffer): Uint8Array {
  if (buffer.numberOfChannels !== 2) {
    throw new Error("WAV_CHANNEL_COUNT_UNSUPPORTED");
  }
  const bytesPerSample = 2;
  const dataBytes = buffer.length * buffer.numberOfChannels * bytesPerSample;
  const output = new ArrayBuffer(44 + dataBytes);
  const view = new DataView(output);
  const writeText = (offset: number, text: string): void => {
    for (let index = 0; index < text.length; index += 1) {
      view.setUint8(offset + index, text.charCodeAt(index));
    }
  };
  writeText(0, "RIFF");
  view.setUint32(4, 36 + dataBytes, true);
  writeText(8, "WAVE");
  writeText(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 2, true);
  view.setUint32(24, buffer.sampleRate, true);
  view.setUint32(28, buffer.sampleRate * 2 * bytesPerSample, true);
  view.setUint16(32, 2 * bytesPerSample, true);
  view.setUint16(34, 16, true);
  writeText(36, "data");
  view.setUint32(40, dataBytes, true);
  const left = buffer.getChannelData(0);
  const right = buffer.getChannelData(1);
  let offset = 44;
  for (let frame = 0; frame < buffer.length; frame += 1) {
    for (const sample of [left[frame] ?? 0, right[frame] ?? 0]) {
      const clipped = Math.max(-1, Math.min(1, sample));
      view.setInt16(offset, clipped < 0 ? clipped * 0x8000 : clipped * 0x7fff, true);
      offset += 2;
    }
  }
  return new Uint8Array(output);
}

export function peakAmplitude(buffer: AudioBuffer): number {
  let peak = 0;
  for (let channel = 0; channel < buffer.numberOfChannels; channel += 1) {
    for (const sample of buffer.getChannelData(channel)) {
      peak = Math.max(peak, Math.abs(sample));
    }
  }
  return peak;
}
