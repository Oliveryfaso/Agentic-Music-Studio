import { loadReviewedInstrumentCatalog } from "./instrument-catalog.js";
import { ChromiumRenderExecutor } from "./executor.js";
import { createRenderServiceServer } from "./server.js";

const tempRoot = process.env.MOTIF_FORGE_TEMP_ROOT ?? "/tmp/motif-forge";
const port = Number(process.env.MOTIF_FORGE_RENDER_PORT ?? "8090");
const packRoot=process.env.MOTIF_FORGE_REVIEWED_PIANO_ROOT;
const manifestPin=process.env.MOTIF_FORGE_REVIEWED_PIANO_MANIFEST_SHA256;
if(Boolean(packRoot)!==Boolean(manifestPin)) throw new Error("INSTRUMENT_PACK_CONFIGURATION_INVALID");
const catalog=packRoot && manifestPin ? await loadReviewedInstrumentCatalog({root:packRoot,manifestSha256:manifestPin}) : undefined;
const executor = new ChromiumRenderExecutor(tempRoot,catalog);
await executor.start();
const service = createRenderServiceServer(executor);
await service.start("0.0.0.0", port);
process.stdout.write(`render service ready on port ${port}\n`);

const shutdown = async (): Promise<void> => {
  await service.close();
  await executor.close();
};
process.once("SIGTERM", () => void shutdown());
process.once("SIGINT", () => void shutdown());
