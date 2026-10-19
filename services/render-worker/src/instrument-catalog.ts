/** Explicitly pinned, previously reviewed local packs. No downloads or arbitrary request paths. */
import { createHash } from "node:crypto";
import { constants } from "node:fs";
import { open, realpath } from "node:fs/promises";
import { resolve } from "node:path";
import { validateInstrumentPack, verifyInstrumentSample, type InstrumentPack } from "../../../packages/audio-engine/src/instruments.js";

export type ReviewedInstrumentCatalog = Readonly<{
  manifest: InstrumentPack;
  manifestSha256: string;
  sample: (sampleId: string) => Uint8Array | undefined;
}>;
const sha = (bytes: Uint8Array): string => createHash("sha256").update(bytes).digest("hex");
async function readLocal(root: string, relative: string, maximum: number): Promise<Uint8Array> {
  const path = resolve(root, relative);
  if (!path.startsWith(root + "/")) throw new Error("INSTRUMENT_FILE_UNSAFE");
  try {
    if (await realpath(path) !== path) throw new Error("INSTRUMENT_FILE_UNSAFE");
    const file = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW);
    try {
      const info = await file.stat();
      if (!info.isFile() || info.size > maximum) throw new Error("INSTRUMENT_FILE_UNSAFE");
      const bytes = new Uint8Array(maximum + 1);
      let offset = 0;
      while (offset < bytes.length) {
        const {bytesRead} = await file.read(bytes, offset, bytes.length - offset, null);
        if (bytesRead === 0) break;
        offset += bytesRead;
      }
      if (offset > maximum) throw new Error("INSTRUMENT_FILE_UNSAFE");
      return bytes.slice(0, offset);
    } finally { await file.close(); }
  } catch { throw new Error("INSTRUMENT_FILE_UNSAFE"); }
}
function freezeManifest(pack: InstrumentPack): InstrumentPack {
  for (const sample of pack.samples) {
    if (sample.loop !== undefined) Object.freeze(sample.loop);
    Object.freeze(sample);
  }
  Object.freeze(pack.samples); Object.freeze(pack.license);
  return Object.freeze(pack);
}
export async function loadReviewedInstrumentCatalog(config: Readonly<{
  root: string; manifestSha256: string;
}>): Promise<ReviewedInstrumentCatalog> {
  // This hash comes from explicit review/configuration, never from the manifest itself or HTTP.
  if (!/^[0-9a-f]{64}$/.test(config.manifestSha256)) throw new Error("INSTRUMENT_MANIFEST_HASH_MISMATCH");
  let root: string;
  try { root = await realpath(config.root); } catch { throw new Error("INSTRUMENT_PACK_UNAVAILABLE"); }
  const bytes = await readLocal(root, "instrument-pack.json", 64 * 1024);
  if (sha(bytes) !== config.manifestSha256) throw new Error("INSTRUMENT_MANIFEST_HASH_MISMATCH");
  const pack = validateInstrumentPack(JSON.parse(new TextDecoder().decode(bytes)) as InstrumentPack);
  const license = await readLocal(root, "cc0.txt", 32 * 1024);
  if (sha(license) !== pack.license.textSha256) throw new Error("INSTRUMENT_LICENSE_HASH_MISMATCH");
  const samples = new Map<string, Uint8Array>();
  for (const sample of pack.samples) {
    const source = await readLocal(root, sample.path, sample.byteSize);
    await verifyInstrumentSample(pack, sample.sampleId, source);
    samples.set(sample.sampleId, source);
  }
  return Object.freeze({manifest: freezeManifest(pack), manifestSha256: config.manifestSha256, sample: (sampleId: string) => {
    const source = samples.get(sampleId);
    return source === undefined ? undefined : new Uint8Array(source);
  }});
}
