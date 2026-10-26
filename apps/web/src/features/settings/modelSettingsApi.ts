import type { components } from "../../generated/api-schema";
import { readData, requestJson } from "../../shared/api";

export type ModelSettings = components["schemas"]["ModelSettingsData"];
export async function readModelSettings(): Promise<ModelSettings> {
  return readData(await requestJson("/api/v1/model-settings", { cache: "no-store" }));
}
export async function checkModelConnection(): Promise<ModelSettings> {
  return readData(await requestJson("/api/v1/model-settings/check", {
    method: "POST", headers: { "X-Motif-Configuration-Check": "1" }, cache: "no-store",
  }));
}
