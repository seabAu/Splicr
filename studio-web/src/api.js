export class ApiError extends Error {
  constructor(message, { status = null, code = null, detail = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

function errorMessage(body, fallback) {
  const detail = body?.detail;
  if (typeof detail === "string") return detail;
  if (detail?.message) return detail.message;
  if (Array.isArray(detail)) {
    return detail.map((item) => item.msg || JSON.stringify(item)).join("; ");
  }
  return body?.message || fallback;
}

function reportServerFailure(path, options, error, responseBody) {
  if (typeof window === "undefined" || path.startsWith("/v1/errors")) return;
  if (error.status !== null && error.status < 500) return;
  const payload = {
    code: error.code || (error.status ? `http_${error.status}` : "network_error"),
    category: error.status ? "http" : "network",
    message: error.message,
    severity: "error",
    retryable: error.status === null || error.status === 408 || error.status === 429 || error.status >= 500,
    status_code: error.status,
    method: options.method || "GET",
    endpoint: path,
    response: responseBody && typeof responseBody === "object" ? responseBody : null,
    context: { client: "react-studio" },
  };
  void fetch("/v1/errors/client", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }).catch(() => {});
}

export async function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  let response;
  try {
    response = await fetch(path, {
      cache: options.method && options.method !== "GET" ? "default" : "no-store",
      credentials: "same-origin",
      ...options,
      headers,
    });
  } catch (cause) {
    const error = new ApiError(`Could not reach the local SPLICR service: ${cause.message}`);
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("splicr:api-error", { detail: error }));
    }
    reportServerFailure(path, options, error, null);
    throw error;
  }
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("json") ? await response.json() : await response.text();
  if (!response.ok) {
    if (response.status === 401) {
      const next = `${window.location.pathname}${window.location.search}`;
      window.location.assign(`/auth?next=${encodeURIComponent(next)}`);
    }
    const error = new ApiError(errorMessage(body, `Request failed (${response.status})`), {
      status: response.status,
      code: body?.detail?.code || body?.error_code || null,
      detail: body,
    });
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("splicr:api-error", { detail: error }));
    }
    reportServerFailure(path, options, error, body);
    throw error;
  }
  return body;
}

export const api = {
  providers: () => request("/v1/providers"),
  projects: () => request("/v1/studio/projects"),
  project: (id) => request(`/v1/studio/projects/${encodeURIComponent(id)}`),
  batches: () => request("/v1/studio/batches"),
  batch: (id) => request(`/v1/studio/batches/${encodeURIComponent(id)}`),
  createBatch: (payload) =>
    request("/v1/studio/batches", { method: "POST", body: JSON.stringify(payload) }),
  reorderBatch: (id, itemIds) =>
    request(`/v1/studio/batches/${encodeURIComponent(id)}/order`, {
      method: "PUT",
      body: JSON.stringify({ item_ids: itemIds }),
    }),
  removeBatchItem: (id, itemId) =>
    request(`/v1/studio/batches/${encodeURIComponent(id)}/items/${encodeURIComponent(itemId)}`, {
      method: "DELETE",
    }),
  batchAction: (id, action) =>
    request(`/v1/studio/batches/${encodeURIComponent(id)}/${action}`, { method: "POST" }),
  components: () => request("/v1/studio/components"),
  configureEngineComponent: (id, pythonPath) =>
    request(`/v1/studio/components/engines/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: JSON.stringify({ python_path: pythonPath }),
    }),
  clearEngineComponent: (id) =>
    request(`/v1/studio/components/engines/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  refreshEdgeVoices: () =>
    request("/v1/studio/components/engines/edge/voices/refresh", {
      method: "POST",
    }),
  voices: (engineId = "") =>
    request(`/v1/studio/voices${engineId ? `?engine_id=${encodeURIComponent(engineId)}` : ""}`),
  voiceDesignJobs: () => request("/v1/studio/voice-design/jobs"),
  voiceDesignJob: (id) =>
    request(`/v1/studio/voice-design/jobs/${encodeURIComponent(id)}`),
  createVoiceDesign: (payload) =>
    request("/v1/studio/voice-design/jobs", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  retryVoiceDesign: (id) =>
    request(`/v1/studio/voice-design/jobs/${encodeURIComponent(id)}/retry`, {
      method: "POST",
    }),
  cancelVoiceDesign: (id) =>
    request(`/v1/studio/voice-design/jobs/${encodeURIComponent(id)}/cancel`, {
      method: "POST",
    }),
  createReferenceVoice: ({ file, label, engineId, referenceText, description, kind = "cloned" }) => {
    const body = new FormData();
    body.append("file", file);
    body.append("label", label);
    body.append("engine_id", engineId);
    body.append("reference_text", referenceText);
    body.append("description", description);
    body.append("kind", kind);
    return request("/v1/studio/voices/reference", { method: "POST", body });
  },
  createVoicePreset: (payload) =>
    request("/v1/studio/voices/presets", { method: "POST", body: JSON.stringify(payload) }),
  updateVoice: (id, payload) =>
    request(`/v1/studio/voices/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  deleteVoice: (id) =>
    request(`/v1/studio/voices/${encodeURIComponent(id)}`, { method: "DELETE" }),
  pronunciations: () => request("/v1/studio/pronunciations"),
  pronunciationStatus: () => request("/v1/studio/pronunciation/status"),
  pronunciationSearch: (query, limit = 150) =>
    request(`/v1/studio/pronunciation/search?query=${encodeURIComponent(query)}&limit=${limit}`),
  pronunciationWord: (word) =>
    request(`/v1/studio/pronunciation/word?word=${encodeURIComponent(word)}`),
  pronunciationPreview: (respelling) =>
    request("/v1/studio/pronunciation/preview", {
      method: "POST",
      body: JSON.stringify({ respelling }),
    }),
  savePronunciation: (word, respelling) =>
    request(`/v1/studio/pronunciations/${encodeURIComponent(word)}`, {
      method: "PUT",
      body: JSON.stringify({ word, respelling }),
    }),
  deletePronunciation: (word) =>
    request(`/v1/studio/pronunciations/${encodeURIComponent(word)}`, { method: "DELETE" }),
  substitutions: () => request("/v1/studio/substitutions"),
  saveSubstitution: (source, replacement) =>
    request("/v1/studio/substitutions", {
      method: "POST",
      body: JSON.stringify({ source, replacement }),
    }),
  deleteSubstitution: (source) =>
    request(`/v1/studio/substitutions?source=${encodeURIComponent(source)}`, {
      method: "DELETE",
    }),
  jobs: () => request("/v1/speech/jobs"),
  job: (id) => request(`/v1/speech/jobs/${encodeURIComponent(id)}`),
  timelineTakes: () => request("/v1/studio/timeline/takes"),
  timeline: (id, waveformBuckets = 940, audioArtifactId = "") =>
    request(
      `/v1/studio/timeline/jobs/${encodeURIComponent(id)}?waveform_buckets=${waveformBuckets}${audioArtifactId ? `&audio_artifact_id=${encodeURIComponent(audioArtifactId)}` : ""}`,
    ),
  timelineSpanUrl: (id, start, end, audioArtifactId = "") =>
    `/v1/studio/timeline/jobs/${encodeURIComponent(id)}/span?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}${audioArtifactId ? `&audio_artifact_id=${encodeURIComponent(audioArtifactId)}` : ""}`,
  reviseTimelineSegment: (id, segmentIndex, text) =>
    request(
      `/v1/studio/timeline/jobs/${encodeURIComponent(id)}/segments/${segmentIndex}/revise`,
      { method: "POST", body: JSON.stringify({ text }) },
    ),
  reviseTimelineSentence: (id, segmentIndex, sentenceIndex, text, crossfadeMs = 30) =>
    request(
      `/v1/studio/timeline/jobs/${encodeURIComponent(id)}/segments/${segmentIndex}/sentences/${sentenceIndex}/revise`,
      { method: "POST", body: JSON.stringify({ text, crossfade_ms: crossfadeMs }) },
    ),
  subtitleTimeline: (id, audioArtifactId = "") =>
    request(`/v1/studio/subtitles/jobs/${encodeURIComponent(id)}${audioArtifactId ? `?audio_artifact_id=${encodeURIComponent(audioArtifactId)}` : ""}`),
  exportJobSubtitles: (id, format, audioArtifactId = "") =>
    request(
      `/v1/studio/subtitles/jobs/${encodeURIComponent(id)}/export?format=${encodeURIComponent(format)}${audioArtifactId ? `&audio_artifact_id=${encodeURIComponent(audioArtifactId)}` : ""}`,
      { method: "POST" },
    ),
  finishingCapabilities: () => request("/v1/studio/finishing/capabilities"),
  finishingAssets: () => request("/v1/studio/finishing/assets"),
  uploadFinishingAsset: (file) => {
    const body = new FormData();
    body.append("file", file);
    return request("/v1/studio/finishing/assets", { method: "POST", body });
  },
  finishingJobs: () => request("/v1/studio/finishing/jobs"),
  finishingJob: (id) =>
    request(`/v1/studio/finishing/jobs/${encodeURIComponent(id)}`),
  createFinishingJob: (payload) =>
    request("/v1/studio/finishing/jobs", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  finishingJobAction: (id, action) =>
    request(`/v1/studio/finishing/jobs/${encodeURIComponent(id)}/${action}`, {
      method: "POST",
    }),
  audiogramCapabilities: () => request("/v1/studio/audiograms/capabilities"),
  audiogramSources: () => request("/v1/studio/audiograms/sources"),
  audiogramJobs: () => request("/v1/studio/audiograms/jobs"),
  audiogramJob: (id) =>
    request(`/v1/studio/audiograms/jobs/${encodeURIComponent(id)}`),
  estimateAudiogram: (payload) =>
    request("/v1/studio/audiograms/estimate", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  createAudiogram: (payload) =>
    request("/v1/studio/audiograms/jobs", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  audiogramJobAction: (id, action) =>
    request(`/v1/studio/audiograms/jobs/${encodeURIComponent(id)}/${action}`, {
      method: "POST",
    }),
  conversionCapabilities: () => request("/v1/studio/conversions/capabilities"),
  conversionSources: () => request("/v1/studio/conversions/sources"),
  conversionJobs: () => request("/v1/studio/conversions/jobs"),
  conversionJob: (id) =>
    request(`/v1/studio/conversions/jobs/${encodeURIComponent(id)}`),
  uploadConversionInput: (file) => {
    const body = new FormData();
    body.append("file", file);
    return request("/v1/studio/conversions/inputs", { method: "POST", body });
  },
  createConversion: (payload) =>
    request("/v1/studio/conversions/jobs", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  conversionJobAction: (id, action) =>
    request(`/v1/studio/conversions/jobs/${encodeURIComponent(id)}/${action}`, {
      method: "POST",
    }),
  transcriptionCapabilities: () => request("/v1/studio/transcriptions/capabilities"),
  transcriptionSources: () => request("/v1/studio/transcriptions/sources"),
  transcriptionJobs: () => request("/v1/studio/transcriptions/jobs"),
  transcriptionJob: (id) =>
    request(`/v1/studio/transcriptions/jobs/${encodeURIComponent(id)}`),
  createTranscription: (payload) =>
    request("/v1/studio/transcriptions/jobs", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  transcriptionJobAction: (id, action) =>
    request(`/v1/studio/transcriptions/jobs/${encodeURIComponent(id)}/${action}`, {
      method: "POST",
    }),
  publishingChannel: () => request("/v1/studio/publishing/channel"),
  savePublishingChannel: (payload) =>
    request("/v1/studio/publishing/channel", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  publishingSources: () => request("/v1/studio/publishing/sources"),
  publishingEpisodes: () => request("/v1/studio/publishing/episodes"),
  publishingChapters: (takeId, audioArtifactId = "") =>
    request(`/v1/studio/publishing/takes/${encodeURIComponent(takeId)}/chapters${audioArtifactId ? `?audio_artifact_id=${encodeURIComponent(audioArtifactId)}` : ""}`),
  exportPublishingTranscript: (takeId) =>
    request(`/v1/studio/publishing/takes/${encodeURIComponent(takeId)}/transcript`, {
      method: "POST",
    }),
  exportPublishingSubtitles: (takeId, format, audioArtifactId = "") =>
    request(
      `/v1/studio/publishing/takes/${encodeURIComponent(takeId)}/subtitles?format=${encodeURIComponent(format)}${audioArtifactId ? `&audio_artifact_id=${encodeURIComponent(audioArtifactId)}` : ""}`,
      { method: "POST" },
    ),
  publishEpisode: (payload) =>
    request("/v1/studio/publishing/episodes", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  preview: (payload) =>
    request("/v1/speech/preview", { method: "POST", body: JSON.stringify(payload) }),
  createJob: (payload) =>
    request("/v1/speech/jobs", { method: "POST", body: JSON.stringify(payload) }),
  previewDialogue: (payload) =>
    request("/v1/studio/dialogue/preview", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  createDialogueJob: (payload) =>
    request("/v1/studio/dialogue/jobs", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  jobAction: (id, action) =>
    request(`/v1/speech/jobs/${encodeURIComponent(id)}/${action}`, { method: "POST" }),
  importDocument: (file) => {
    const body = new FormData();
    body.append("file", file);
    return request("/v1/documents/import", { method: "POST", body });
  },
  profiles: () => request("/v1/profiles"),
  createProfile: (payload) =>
    request("/v1/profiles", { method: "POST", body: JSON.stringify(payload) }),
  updateProfile: (id, payload) =>
    request(`/v1/profiles/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  deleteProfile: (id) =>
    request(`/v1/profiles/${encodeURIComponent(id)}`, { method: "DELETE" }),
  resources: () => request("/v1/api-resources"),
  resource: (id) => request(`/v1/api-resources/${encodeURIComponent(id)}`),
  createResource: (payload) =>
    request("/v1/api-resources", { method: "POST", body: JSON.stringify(payload) }),
  updateResource: (id, payload) =>
    request(`/v1/api-resources/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  deleteResource: (id) =>
    request(`/v1/api-resources/${encodeURIComponent(id)}`, { method: "DELETE" }),
  chatResources: () => request("/v1/chat-resources"),
  chatResource: (id) => request(`/v1/chat-resources/${encodeURIComponent(id)}`),
  createChatResource: (payload) =>
    request("/v1/chat-resources", { method: "POST", body: JSON.stringify(payload) }),
  updateChatResource: (id, payload) =>
    request(`/v1/chat-resources/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  deleteChatResource: (id) =>
    request(`/v1/chat-resources/${encodeURIComponent(id)}`, { method: "DELETE" }),
  verifyChatResource: (id, model = "") =>
    request(`/v1/chat-resources/${encodeURIComponent(id)}/verify${model ? `?model=${encodeURIComponent(model)}` : ""}`, {
      method: "POST",
    }),
  generateDialogueScript: (payload) =>
    request("/v1/studio/dialogue/generate", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  createDialogueScriptJob: (payload) =>
    request("/v1/studio/dialogue/script-jobs", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  dialogueScriptJobs: () => request("/v1/studio/dialogue/script-jobs"),
  dialogueScriptJob: (id) => request(`/v1/studio/dialogue/script-jobs/${encodeURIComponent(id)}`),
  dialogueScriptJobAction: (id, action) =>
    request(`/v1/studio/dialogue/script-jobs/${encodeURIComponent(id)}/${action}`, {
      method: "POST",
    }),
  refineDialogueSelection: (payload) =>
    request("/v1/studio/dialogue/refine", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  errors: ({ after = 0, unreadOnly = false } = {}) =>
    request(`/v1/errors?after=${after}&limit=500&unread_only=${unreadOnly}`),
  error: (id) => request(`/v1/errors/${encodeURIComponent(id)}`),
  markErrorRead: (id) =>
    request(`/v1/errors/${encodeURIComponent(id)}/read`, { method: "POST" }),
  markAllErrorsRead: () => request("/v1/errors/read-all", { method: "POST" }),
  clearErrors: (scope = "read") =>
    request(`/v1/errors?scope=${encodeURIComponent(scope)}`, { method: "DELETE" }),
};
