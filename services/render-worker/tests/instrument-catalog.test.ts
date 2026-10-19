import { createHash } from "node:crypto";
import { mkdtemp, mkdir, writeFile, rm, symlink } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { describe, expect, it } from "vitest";
import { fixture } from "../../../packages/audio-engine/tests/fixtures/instrument-fixture.js";
import { loadReviewedInstrumentCatalog } from "../src/instrument-catalog.js";
import { createBuiltinClickWav, LoopbackRenderServer } from "../src/runtime.js";
const sha = (x: Uint8Array | string) => createHash("sha256").update(x).digest("hex");
async function setup() {
  const root = await mkdtemp(join(tmpdir(),"motif-pack-catalog-"));
  const { pack: original, bytes } = await fixture();
  const license = "Self-authored test fixture, dedicated CC0.";
  const pack = {...original,license:{...original.license,textSha256:sha(license)}};
  await mkdir(join(root,"samples"));
  await writeFile(join(root,"samples/own-click.wav"),bytes);
  await writeFile(join(root,"cc0.txt"),license);
  const manifest = JSON.stringify(pack);
  await writeFile(join(root,"instrument-pack.json"),manifest);
  return {root,bytes,pack,manifestSha256:sha(manifest)};
}
describe("reviewed instrument catalog",()=>{
  it("loads the pinned manifest/license and verifies actual PCM before serving exact IDs",async()=>{
    const f=await setup();
    try{
      const c=await loadReviewedInstrumentCatalog(f);
      expect(c.manifest.packId).toBe(f.pack.packId);
      expect(c.sample("soft")).toEqual(f.bytes);
      expect(c.sample("../../cc0.txt")).toBeUndefined();
      const mutable=c.sample("soft")!;mutable[0]=0;
      expect(c.sample("soft")).toEqual(f.bytes);
    }finally{await rm(f.root,{recursive:true,force:true});}
  });
  it("rejects a changed manifest rather than accepting its self-described hashes",async()=>{
    const f=await setup();
    try{
      await writeFile(join(f.root,"instrument-pack.json"),JSON.stringify({...f.pack,maxVoices:8}));
      await expect(loadReviewedInstrumentCatalog(f)).rejects.toThrow("INSTRUMENT_MANIFEST_HASH_MISMATCH");
    }finally{await rm(f.root,{recursive:true,force:true});}
  });
  it("rejects changed license text",async()=>{
    const f=await setup();
    try{
      await writeFile(join(f.root,"cc0.txt"),"changed");
      await expect(loadReviewedInstrumentCatalog(f)).rejects.toThrow("INSTRUMENT_LICENSE_HASH_MISMATCH");
    }finally{await rm(f.root,{recursive:true,force:true});}
  });
  it("rejects a sample symlink even when the outside bytes match",async()=>{
    const f=await setup();const outside=await mkdtemp(join(tmpdir(),"motif-pack-outside-"));
    try{
      await writeFile(join(outside,"own.wav"),f.bytes);await rm(join(f.root,"samples/own-click.wav"));
      await symlink(join(outside,"own.wav"),join(f.root,"samples/own-click.wav"));
      await expect(loadReviewedInstrumentCatalog(f)).rejects.toThrow("INSTRUMENT_FILE_UNSAFE");
    }finally{await rm(f.root,{recursive:true,force:true});await rm(outside,{recursive:true,force:true});}
  });
  it("rejects modified sample bytes before producing a usable catalog",async()=>{
    const f=await setup();
    try{
      const changed=new Uint8Array(f.bytes);changed[changed.length-1]!^=1;
      await writeFile(join(f.root,"samples/own-click.wav"),changed);
      await expect(loadReviewedInstrumentCatalog(f)).rejects.toThrow("INSTRUMENT_SAMPLE_HASH_MISMATCH");
    }finally{await rm(f.root,{recursive:true,force:true});}
  });
  it("serves samples only for the registered nonce and exact sample ID",async()=>{
    const f=await setup();const server=new LoopbackRenderServer("/unused",createBuiltinClickWav());
    try{
      const c=await loadReviewedInstrumentCatalog(f);server.registerInstrumentPack("d".repeat(32),c);await server.start();
      const url=server.origin+"/instrument-packs/"+"d".repeat(32);
      expect((await fetch(url+"/soft.wav")).status).toBe(200);
      expect(new Uint8Array(await (await fetch(url+"/soft.wav")).arrayBuffer())).toEqual(f.bytes);
      expect((await fetch(url+"/unknown.wav")).status).toBe(404);
      expect((await fetch(server.origin+"/instrument-packs/"+"e".repeat(32)+"/soft.wav")).status).toBe(404);
    }finally{await server.close();await rm(f.root,{recursive:true,force:true});}
  });
});
