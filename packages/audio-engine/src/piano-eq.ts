export const PIANO_EQ_PROFILE = Object.freeze({
  schema_version: "three-band-eq-profile.v1",
  profile_id: "motif-three-band-static.v1",
  sample_rate_hz: 48000,
  low_frequency_hz: 180,
  mid_frequency_hz: 1000,
  mid_q: 0.8,
  high_frequency_hz: 6000,
  shelf_slope: 1,
} as const);

export type PianoEqProfile = Readonly<typeof PIANO_EQ_PROFILE>;
export type PianoEqSettings = Readonly<{
  schema_version: "piano-eq.v1";
  profile_id: PianoEqProfile["profile_id"];
  bypass: boolean;
  low_gain_db: number;
  mid_gain_db: number;
  high_gain_db: number;
}>;

const SETTINGS_KEYS = ["schema_version", "profile_id", "bypass", "low_gain_db", "mid_gain_db", "high_gain_db"];
const GAIN_KEYS = ["low_gain_db", "mid_gain_db", "high_gain_db"] as const;

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function validatePianoEqProfile(value: unknown): asserts value is PianoEqProfile {
  if (!record(value) || Object.keys(value).length !== Object.keys(PIANO_EQ_PROFILE).length ||
      Object.entries(PIANO_EQ_PROFILE).some(([key, expected]) => !Object.hasOwn(value, key) || value[key] !== expected)) {
    throw new Error("AUDIO_GRAPH_INVALID:eqProfile");
  }
}

export function validatePianoEqSettings(value: unknown): asserts value is PianoEqSettings {
  if (!record(value) || Object.keys(value).length !== SETTINGS_KEYS.length ||
      SETTINGS_KEYS.some(key => !Object.hasOwn(value, key)) ||
      value.schema_version !== "piano-eq.v1" || value.profile_id !== PIANO_EQ_PROFILE.profile_id ||
      typeof value.bypass !== "boolean" || GAIN_KEYS.some(key =>
        typeof value[key] !== "number" || !Number.isFinite(value[key]) || value[key] < -12 || value[key] > 12)) {
    throw new Error("AUDIO_GRAPH_INVALID:eq3");
  }
}

type Band = Readonly<{ type: "lowshelf" | "peaking" | "highshelf"; frequency: number; gain: number }>;

function activeBands(eq: PianoEqSettings, profile: PianoEqProfile): readonly Band[] {
  validatePianoEqProfile(profile);
  validatePianoEqSettings(eq);
  if (eq.bypass) return [];
  const bands: Band[] = [
    { type: "lowshelf", frequency: profile.low_frequency_hz, gain: eq.low_gain_db },
    { type: "peaking", frequency: profile.mid_frequency_hz, gain: eq.mid_gain_db },
    { type: "highshelf", frequency: profile.high_frequency_hz, gain: eq.high_gain_db },
  ];
  return bands.filter(band => band.gain !== 0);
}

function coefficients(band: Band, profile: PianoEqProfile): readonly [number, number, number, number, number, number] {
  const a = 10 ** (band.gain / 40);
  const omega = 2 * Math.PI * band.frequency / profile.sample_rate_hz;
  const c = Math.cos(omega), s = Math.sin(omega);
  if (band.type === "peaking") {
    const alpha = s / (2 * profile.mid_q);
    return [1 + alpha * a, -2 * c, 1 - alpha * a, 1 + alpha / a, -2 * c, 1 - alpha / a];
  }
  // Web Audio shelves use RBJ S=1; their Q parameter has no effect.
  const alpha = s / 2 * Math.sqrt((a + 1 / a) * (1 / profile.shelf_slope - 1) + 2);
  const beta = 2 * Math.sqrt(a) * alpha;
  if (band.type === "lowshelf") {
    return [a * ((a + 1) - (a - 1) * c + beta), 2 * a * ((a - 1) - (a + 1) * c),
      a * ((a + 1) - (a - 1) * c - beta), (a + 1) + (a - 1) * c + beta,
      -2 * ((a - 1) + (a + 1) * c), (a + 1) + (a - 1) * c - beta];
  }
  return [a * ((a + 1) + (a - 1) * c + beta), -2 * a * ((a - 1) + (a + 1) * c),
    a * ((a + 1) + (a - 1) * c - beta), (a + 1) - (a - 1) * c + beta,
    2 * ((a - 1) - (a + 1) * c), (a + 1) - (a - 1) * c - beta];
}

/** Added EQ response only; the historical Tone EQ3 and limiter are separate. */
export function eqResponseDb(eq: PianoEqSettings, profile: PianoEqProfile, frequencyHz: number): number {
  const bands = activeBands(eq, profile);
  if (!Number.isFinite(frequencyHz) || frequencyHz < 0 || frequencyHz > profile.sample_rate_hz / 2)
    throw new Error("PIANO_EQ_FREQUENCY_INVALID");
  const omega = 2 * Math.PI * frequencyHz / profile.sample_rate_hz;
  const magnitudeSquared = (c0: number, c1: number, c2: number): number =>
    (c0 + c1 * Math.cos(omega) + c2 * Math.cos(2 * omega)) ** 2 +
    (c1 * Math.sin(omega) + c2 * Math.sin(2 * omega)) ** 2;
  return bands.reduce((db, band) => {
    const [b0, b1, b2, a0, a1, a2] = coefficients(band, profile);
    return db + 10 * Math.log10(magnitudeSquared(b0, b1, b2) / magnitudeSquared(a0, a1, a2));
  }, 0);
}

/** Connect the native output of the preserved EQ3 to the existing panner. */
export function connectPianoEq(
  context: BaseAudioContext, input: AudioNode, output: AudioNode,
  eq: PianoEqSettings, profile: PianoEqProfile,
): readonly BiquadFilterNode[] {
  const bands = activeBands(eq, profile);
  if (context.sampleRate !== profile.sample_rate_hz) throw new Error("AUDIO_GRAPH_INVALID:eqProfile");
  const filters: BiquadFilterNode[] = [];
  let previous = input;
  for (const band of bands) {
    const filter = context.createBiquadFilter();
    filter.type = band.type;
    filter.frequency.value = band.frequency;
    filter.gain.value = band.gain;
    if (band.type === "peaking") filter.Q.value = profile.mid_q;
    previous.connect(filter);
    filters.push(filter);
    previous = filter;
  }
  previous.connect(output);
  return filters;
}
