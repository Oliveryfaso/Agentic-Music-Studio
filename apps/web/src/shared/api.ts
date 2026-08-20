export type ArtifactAvailability = "available" | "evicted" | "missing" | "rehydrating";

export interface FeatureArtifactData {
  artifact_id: string;
  project_id: string;
  source_audio_artifact_id: string;
  feature_profile: string;
  feature_schema_version: string;
  availability: ArtifactAvailability;
  content_hash: string;
  byte_size: number;
  payload: Record<string, unknown> | null;
}

export interface AudioFeatureSetData {
  source_audio_artifact_id: string;
  features: FeatureArtifactData[];
}

export type DeclaredAudioFormat = "wav" | "mp3" | "flac";
export type RightsDeclaration = "user_owned" | "licensed" | "public_domain" | "cc0" | "cc_by";

export interface CreateProjectData {
  project_id: string;
  active_branch_id: string;
  root_revision_id: string;
  content_hash: string;
  replayed: boolean;
}

export interface ImportAnalysisProjection {
  bpm: number | null;
  bpm_confidence: number | null;
  key_tonic: string | null;
  key_mode: "major" | "minor" | null;
  key_confidence: number | null;
  project_bpm: number | null;
  policy_version: string;
  explanation_code: string | null;
}

export interface ImportRunData {
  thread_id: string;
  run_id: string;
  job_id: string | null;
  phase: "waiting_worker" | "analysis_confirmation_required" | "completed" | "failed";
  artifact_id: string | null;
  source_artifact_id: string | null;
  normalized_artifact_id: string | null;
  revision_id: string | null;
  error_code: string | null;
  replayed: boolean;
  analysis: ImportAnalysisProjection | null;
}

export interface UploadProgress {
  phase: "checksum" | "project" | "upload" | "import";
  uploadedBytes: number;
  totalBytes: number;
  detail: string;
}

export interface ImportStartResult {
  project: CreateProjectData;
  run: ImportRunData;
}

export interface SuccessEnvelope<T> {
  request_id: string;
  status: "succeeded";
  data: T;
  warnings: string[];
  trace_id: string;
}

interface ProblemDetails {
  detail?: string;
  error_code?: string;
  retryable?: boolean;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly retryable: boolean,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const AVAILABILITY = new Set<ArtifactAvailability>([
  "available",
  "evicted",
  "missing",
  "rehydrating",
]);

export function isUuid(value: string): boolean {
  return UUID_PATTERN.test(value);
}

export async function uploadAndStartImport(
  file: File,
  projectName: string,
  rightsDeclaration: RightsDeclaration,
  operationId: string,
  onProgress: (progress: UploadProgress) => void,
  signal?: AbortSignal,
): Promise<ImportStartResult> {
  if (file.size > 256 * 1024 * 1024) {
    throw new ApiError("单个文件不能超过 256 MiB", "UPLOAD_TOO_LARGE", false, 413);
  }
  const format = declaredFormat(file.name);
  onProgress({ phase: "checksum", uploadedBytes: 0, totalBytes: file.size, detail: "计算 SHA-256" });
  const expectedSha256 = await sha256Hex(await file.arrayBuffer());
  signal?.throwIfAborted();

  onProgress({ phase: "project", uploadedBytes: 0, totalBytes: file.size, detail: "创建项目" });
  const project = parseProjectEnvelope(
    await requestJson("/api/v1/projects", {
      method: "POST",
      headers: jsonHeaders(`web-project-${operationId}`),
      body: JSON.stringify({ name: projectName }),
      signal: signal ?? null,
    }),
  ).data;

  const uploadSession = parseUploadSessionEnvelope(
    await requestJson("/api/v1/upload-sessions", {
      method: "POST",
      headers: jsonHeaders(`web-upload-${operationId}`),
      body: JSON.stringify({
        project_id: project.project_id,
        filename: file.name,
        byte_size: file.size,
        declared_format: format,
        rights_declaration: rightsDeclaration,
        expected_sha256: expectedSha256,
      }),
      signal: signal ?? null,
    }),
  ).data;

  let uploadedBytes = 0;
  let partNumber = 1;
  for (let offset = 0; offset < file.size; offset += uploadSession.part_size_bytes) {
    const part = file.slice(offset, Math.min(offset + uploadSession.part_size_bytes, file.size));
    await requestJson(
      `/api/v1/upload-sessions/${encodeURIComponent(uploadSession.upload_id)}/parts/${partNumber}`,
      { method: "PUT", headers: { "Content-Type": "application/octet-stream" }, body: part, signal: signal ?? null },
    );
    uploadedBytes += part.size;
    onProgress({ phase: "upload", uploadedBytes, totalBytes: file.size, detail: `上传分块 ${partNumber}` });
    partNumber += 1;
  }

  const completed = parseCompletedUploadEnvelope(
    await requestJson(`/api/v1/upload-sessions/${uploadSession.upload_id}/complete`, {
      method: "POST",
      signal: signal ?? null,
    }),
  ).data;
  onProgress({ phase: "import", uploadedBytes: file.size, totalBytes: file.size, detail: "启动分析 Graph" });
  const run = parseImportRunEnvelope(
    await requestJson(`/api/v1/projects/${project.project_id}/imports`, {
      method: "POST",
      headers: jsonHeaders(`web-import-${operationId}`),
      body: JSON.stringify({
        branch_id: project.active_branch_id,
        base_revision_id: project.root_revision_id,
        source_artifact_id: completed.source_artifact_id,
      }),
      signal: signal ?? null,
    }),
  ).data;
  return { project, run };
}

export async function readImportRun(threadId: string): Promise<ImportRunData> {
  return parseImportRunEnvelope(
    await requestJson(`/api/v1/imports/${encodeURIComponent(threadId)}`),
  ).data;
}

export interface ConfirmImportAnalysisRequest {
  action: "confirm" | "override" | "skip_alignment" | "cancel";
  source_bpm?: number;
  key_tonic?: string;
  key_mode?: "major" | "minor";
}

export async function confirmImportAnalysis(
  threadId: string,
  decision: ConfirmImportAnalysisRequest,
): Promise<ImportRunData> {
  return parseImportRunEnvelope(
    await requestJson(`/api/v1/imports/${encodeURIComponent(threadId)}/confirm-analysis`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(decision),
    }),
  ).data;
}

export function audioContentUrl(artifactId: string): string {
  return `/api/v1/audio-artifacts/${encodeURIComponent(artifactId)}/content`;
}

export async function listAudioFeatures(sourceArtifactId: string): Promise<AudioFeatureSetData> {
  const value = await requestJson(
    `/api/v1/audio-artifacts/${encodeURIComponent(sourceArtifactId)}/features`,
  );
  return parseFeatureSetEnvelope(value).data;
}

export async function readFeatureArtifact(artifactId: string): Promise<FeatureArtifactData> {
  const value = await requestJson(`/api/v1/feature-artifacts/${encodeURIComponent(artifactId)}`);
  return parseFeatureEnvelope(value).data;
}

export interface RehydrateRunData {
  thread_id: string;
  run_id: string;
  job_id: string | null;
  artifact_id: string;
  phase: "waiting_worker" | "completed" | "failed";
  error_code: string | null;
  replayed: boolean;
}

export async function rehydrateArtifact(artifactId: string): Promise<RehydrateRunData> {
  const value = await requestJson(`/api/v1/artifacts/${encodeURIComponent(artifactId)}/rehydrate`, {
    method: "POST",
    headers: { "Idempotency-Key": `studio-rehydrate-${artifactId}` },
  });
  if (!isRecord(value) || value.status !== "succeeded" || !isRecord(value.data)) {
    throw new ApiError("恢复接口返回了无法识别的数据", "INVALID_RESPONSE", false, 502);
  }
  const data = value.data;
  if (
    typeof data.thread_id !== "string" ||
    typeof data.run_id !== "string" ||
    typeof data.artifact_id !== "string" ||
    !["waiting_worker", "completed", "failed"].includes(String(data.phase))
  ) {
    throw new ApiError("恢复任务缺少必要字段", "INVALID_RESPONSE", false, 502);
  }
  return data as unknown as RehydrateRunData;
}

export async function requestJson(path: string, init?: RequestInit): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError("上传已取消；未完成的分块会按存储策略自动回收", "UPLOAD_CANCELLED", false, 499);
    }
    throw new ApiError("无法连接 Motif Forge API", "API_UNAVAILABLE", true, 0);
  }
  const value = (await response.json().catch(() => null)) as unknown;
  if (!response.ok) {
    const problem = isRecord(value) ? (value as ProblemDetails) : {};
    throw new ApiError(
      typeof problem.detail === "string" ? problem.detail : "请求失败",
      typeof problem.error_code === "string" ? problem.error_code : "HTTP_ERROR",
      problem.retryable === true,
      response.status,
    );
  }
  return value;
}

export function readData<T>(value: unknown): T {
  if (!isRecord(value) || !("data" in value)) {
    throw invalidResponse("API 返回缺少 data 字段");
  }
  return value.data as T;
}

export function parseFeatureSetEnvelope(value: unknown): SuccessEnvelope<AudioFeatureSetData> {
  const envelope = parseEnvelope(value);
  if (!isRecord(envelope.data) || !isUuidString(envelope.data.source_audio_artifact_id)) {
    throw invalidResponse("Feature 列表缺少源 Artifact ID");
  }
  if (!Array.isArray(envelope.data.features)) {
    throw invalidResponse("Feature 列表不是数组");
  }
  return {
    ...envelope,
    data: {
      source_audio_artifact_id: envelope.data.source_audio_artifact_id,
      features: envelope.data.features.map(parseFeatureData),
    },
  };
}

export function parseFeatureEnvelope(value: unknown): SuccessEnvelope<FeatureArtifactData> {
  const envelope = parseEnvelope(value);
  return { ...envelope, data: parseFeatureData(envelope.data) };
}

export function parseImportRunEnvelope(value: unknown): SuccessEnvelope<ImportRunData> {
  const envelope = parseEnvelope(value);
  const data = envelope.data;
  if (
    !isRecord(data) ||
    typeof data.thread_id !== "string" ||
    !data.thread_id.startsWith("import-") ||
    !isUuidString(data.run_id) ||
    !["waiting_worker", "analysis_confirmation_required", "completed", "failed"].includes(String(data.phase)) ||
    !isOptionalUuid(data.job_id) ||
    !isOptionalUuid(data.artifact_id) ||
    !isOptionalUuid(data.source_artifact_id) ||
    !isOptionalUuid(data.normalized_artifact_id) ||
    !isOptionalUuid(data.revision_id) ||
    (data.error_code !== null && typeof data.error_code !== "string") ||
    typeof data.replayed !== "boolean" ||
    (data.analysis !== null && !isRecord(data.analysis))
  ) {
    throw invalidResponse("Import Run 不符合 DTO 合同");
  }
  return {
    ...envelope,
    data: {
      thread_id: data.thread_id,
      run_id: data.run_id,
      job_id: data.job_id,
      phase: data.phase as ImportRunData["phase"],
      artifact_id: data.artifact_id,
      source_artifact_id: data.source_artifact_id,
      normalized_artifact_id: data.normalized_artifact_id,
      revision_id: data.revision_id,
      error_code: data.error_code,
      replayed: data.replayed,
      analysis: data.analysis === null ? null : parseImportAnalysis(data.analysis),
    },
  };
}

function parseImportAnalysis(value: Record<string, unknown>): ImportAnalysisProjection {
  if (
    !isNullableNumber(value.bpm) ||
    !isNullableUnitInterval(value.bpm_confidence) ||
    !isNullableString(value.key_tonic) ||
    (value.key_mode !== null && value.key_mode !== "major" && value.key_mode !== "minor") ||
    !isNullableUnitInterval(value.key_confidence) ||
    !isNullableNumber(value.project_bpm) ||
    typeof value.policy_version !== "string" ||
    !isNullableString(value.explanation_code)
  ) {
    throw invalidResponse("Import Analysis 不符合 DTO 合同");
  }
  return value as unknown as ImportAnalysisProjection;
}

function parseProjectEnvelope(value: unknown): SuccessEnvelope<CreateProjectData> {
  const envelope = parseEnvelope(value);
  const data = envelope.data;
  if (!isRecord(data) || !isUuidString(data.project_id) || !isUuidString(data.active_branch_id) || !isUuidString(data.root_revision_id) || typeof data.content_hash !== "string" || typeof data.replayed !== "boolean") {
    throw invalidResponse("Project 返回不符合合同");
  }
  return { ...envelope, data: data as unknown as CreateProjectData };
}

function parseUploadSessionEnvelope(value: unknown): SuccessEnvelope<{ upload_id: string; part_size_bytes: number }> {
  const envelope = parseEnvelope(value);
  const data = envelope.data;
  if (!isRecord(data) || !isUuidString(data.upload_id) || typeof data.part_size_bytes !== "number" || data.part_size_bytes <= 0) {
    throw invalidResponse("Upload Session 返回不符合合同");
  }
  return { ...envelope, data: { upload_id: data.upload_id, part_size_bytes: data.part_size_bytes } };
}

function parseCompletedUploadEnvelope(value: unknown): SuccessEnvelope<{ source_artifact_id: string }> {
  const envelope = parseEnvelope(value);
  const data = envelope.data;
  if (!isRecord(data) || !isUuidString(data.source_artifact_id)) {
    throw invalidResponse("Upload complete 返回不符合合同");
  }
  return { ...envelope, data: { source_artifact_id: data.source_artifact_id } };
}

function parseEnvelope(value: unknown): SuccessEnvelope<unknown> {
  if (
    !isRecord(value) ||
    value.status !== "succeeded" ||
    !isUuidString(value.request_id) ||
    !isUuidString(value.trace_id) ||
    !Array.isArray(value.warnings)
  ) {
    throw invalidResponse("API Envelope 不符合合同");
  }
  return {
    request_id: value.request_id,
    status: "succeeded",
    data: value.data,
    warnings: value.warnings.filter((item): item is string => typeof item === "string"),
    trace_id: value.trace_id,
  };
}

function parseFeatureData(value: unknown): FeatureArtifactData {
  if (
    !isRecord(value) ||
    !isUuidString(value.artifact_id) ||
    !isUuidString(value.project_id) ||
    !isUuidString(value.source_audio_artifact_id) ||
    typeof value.feature_profile !== "string" ||
    typeof value.feature_schema_version !== "string" ||
    typeof value.availability !== "string" ||
    !AVAILABILITY.has(value.availability as ArtifactAvailability) ||
    typeof value.content_hash !== "string" ||
    typeof value.byte_size !== "number" ||
    (value.payload !== null && !isRecord(value.payload))
  ) {
    throw invalidResponse("Feature Artifact 不符合 DTO 合同");
  }
  return value as unknown as FeatureArtifactData;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isUuidString(value: unknown): value is string {
  return typeof value === "string" && isUuid(value);
}

function isOptionalUuid(value: unknown): value is string | null {
  return value === null || isUuidString(value);
}

function declaredFormat(filename: string): DeclaredAudioFormat {
  const extension = filename.split(".").pop()?.toLowerCase();
  if (extension === "wav" || extension === "mp3" || extension === "flac") return extension;
  throw new ApiError("只支持 WAV、MP3 或 FLAC", "UPLOAD_MEDIA_TYPE_UNSUPPORTED", false, 422);
}

export function jsonHeaders(idempotencyKey: string): Record<string, string> {
  return { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey };
}

async function sha256Hex(bytes: ArrayBuffer): Promise<string> {
  if (!crypto.subtle) {
    throw new ApiError("当前页面不是安全上下文，无法计算上传校验值", "WEB_CRYPTO_UNAVAILABLE", false, 400);
  }
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, "0")).join("");
}

function isNullableNumber(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isFinite(value));
}

function isNullableUnitInterval(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && value >= 0 && value <= 1);
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function invalidResponse(message: string): ApiError {
  return new ApiError(message, "INVALID_RESPONSE", false, 502);
}
