// The one place that knows how to talk to the backend.
//
// The token arrives as ?token=... when the server opens the browser, and
// is kept in sessionStorage so a reload doesn't lose it. It is NOT in
// localStorage: that would persist it beyond the session for no benefit.

const params = new URLSearchParams(window.location.search);
const fromUrl = params.get("token");
if (fromUrl) {
  sessionStorage.setItem("narratorToken", fromUrl);
  // Drop it from the address bar so it isn't in history or a screenshot.
  window.history.replaceState({}, "", window.location.pathname);
}

export const token = () => sessionStorage.getItem("narratorToken") || "";

async function call(path, options = {}) {
  // A FormData body (file uploads) needs the browser to set its own
  // Content-Type with the multipart boundary -- forcing application/json
  // here would send the boundary-less header and the server couldn't
  // parse the body at all.
  const isFormData =
    typeof FormData !== "undefined" && options.body instanceof FormData;
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      "X-Narrator-Token": token(),
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    let detail;
    try {
      detail = (await response.json()).detail;
    } catch {
      detail = await response.text();
    }
    throw new Error(
      typeof detail === "string" ? detail : JSON.stringify(detail)
    );
  }
  return response.json();
}

export const getSchema = () => call("/api/schema");
export const getEngines = () => call("/api/engines");
export const getComponents = () => call("/api/components");
export const installComponent = (key) =>
  call("/api/components/install", {
    method: "POST",
    body: JSON.stringify({ key }),
  });
export const installEngine = (name) =>
  call(`/api/engines/${encodeURIComponent(name)}/install`, {
    method: "POST",
  });
export const getSettings = () => call("/api/settings");
export const setEnvRoot = (path) =>
  call("/api/engines/env-root", {
    method: "POST",
    body: JSON.stringify({ path }),
  });
export const getTakes = () => call("/api/takes");
export const getTimeline = (manifest) =>
  call(`/api/timeline?manifest=${encodeURIComponent(manifest)}`);
export const timelineSpanUrl = (manifest, start, end) =>
  `/api/timeline/span?manifest=${encodeURIComponent(manifest)}` +
  `&start=${start}&end=${end}`;
export async function fetchTimelineSpan(manifest, start, end) {
  // Same shape as fetchVoiceReference -- an <audio> element can't send
  // the auth header, so this fetches the clip as a blob through the
  // normal authed request and hands back an object URL.
  const response = await fetch(timelineSpanUrl(manifest, start, end), {
    headers: { "X-Narrator-Token": token() },
  });
  if (!response.ok) throw new Error("Couldn't extract that span.");
  const blob = await response.blob();
  return URL.createObjectURL(blob);
}
export const respliceSegment = (manifest, chunk, seg, text, retry = 0) =>
  call("/api/timeline/resplice", {
    method: "POST",
    body: JSON.stringify({ manifest, chunk, seg, text, retry }),
  });
export const getTimelineWords = (manifest, text) =>
  call(
    `/api/timeline/words?manifest=${encodeURIComponent(manifest)}` +
      `&text=${encodeURIComponent(text)}`
  );

export const getAudiogramDefaults = () => call("/api/audiogram/defaults");
export const getAudiogramSource = (manifest = "") =>
  call(`/api/audiogram/source?manifest=${encodeURIComponent(manifest)}`);
export const getAudiogramLayout = (cfg, width, height) =>
  call("/api/audiogram/layout", {
    method: "POST",
    body: JSON.stringify({ cfg, width, height }),
  });
export async function fetchAudiogramPreviewPng(cfg, width, height) {
  // A rendered PNG, not JSON -- call() always parses the body as JSON,
  // so this bypasses it and does the fetch directly, same shape as the
  // blob-URL helpers for voice/span playback.
  const response = await fetch("/api/audiogram/preview.png", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Narrator-Token": token(),
    },
    body: JSON.stringify({ cfg, width, height }),
  });
  if (!response.ok) throw new Error("Couldn't render the preview.");
  const blob = await response.blob();
  return URL.createObjectURL(blob);
}
export const getAudiogramCommand = (manifest, width, height, filterOverride) =>
  call(
    `/api/audiogram/command?manifest=${encodeURIComponent(manifest)}` +
      `&width=${width}&height=${height}` +
      `&filter_override=${encodeURIComponent(filterOverride || "")}`
  );
export const getAudiogramEstimate = (manifest, width, height, fps, crop, codec) =>
  call(
    `/api/audiogram/estimate?manifest=${encodeURIComponent(manifest)}` +
      `&width=${width}&height=${height}&fps=${fps}&crop=${crop}` +
      `&codec=${encodeURIComponent(codec)}`
  );
export const getAudiogramPreviewReason = () =>
  call("/api/audiogram/preview-reason");
export const startAudiogramPreviewMotion = (manifest, seconds) =>
  call("/api/audiogram/preview-motion", {
    method: "POST",
    body: JSON.stringify({ manifest, seconds }),
  });
export const startAudiogramExport = (request) =>
  call("/api/audiogram/export", {
    method: "POST",
    body: JSON.stringify(request),
  });
export const getExpressionsReference = (filter = "") =>
  call(`/api/expressions/reference?filter=${encodeURIComponent(filter)}`);
export const validateExpression = (source) =>
  call("/api/expressions/validate", {
    method: "POST",
    body: JSON.stringify({ source }),
  });
export const getLibrary = () => call("/api/library");
export const searchWords = (query, limit = 150) =>
  call(
    `/api/pronunciation/search?query=${encodeURIComponent(query)}&limit=${limit}`
  );
export const wordSound = (word) =>
  call(`/api/pronunciation/word?word=${encodeURIComponent(word)}`);
export const previewRespelling = (word, respelling) =>
  call("/api/pronunciation/preview", {
    method: "POST",
    body: JSON.stringify({ word, respelling }),
  });
export const saveRespelling = (word, respelling) =>
  call("/api/pronunciation/save", {
    method: "POST",
    body: JSON.stringify({ word, respelling }),
  });
export const deleteRespelling = (word) =>
  call(`/api/pronunciation/${encodeURIComponent(word)}`, { method: "DELETE" });
export const convertOptions = () => call("/api/convert/options");

// --- LLM providers and dialogue ---
export const getProviders = () => call("/api/llm/providers");
export const saveProvider = (name, config) =>
  call("/api/llm/providers", {
    method: "POST",
    body: JSON.stringify({ name, config }),
  });
export const deleteProvider = (name) =>
  call(`/api/llm/providers/${encodeURIComponent(name)}`, { method: "DELETE" });
export const verifyProvider = (name, model = "") =>
  call("/api/llm/verify", {
    method: "POST",
    body: JSON.stringify({ name, model }),
  });
export const startScript = (document, provider, model = "", options = {}) =>
  call("/api/dialogue/script", {
    method: "POST",
    body: JSON.stringify({ document, provider, model, options }),
  });
export const renderDialogue = (cfg, turns, voice1, voice2) =>
  call("/api/dialogue/render", {
    method: "POST",
    body: JSON.stringify({ cfg, turns, voice1, voice2 }),
  });
export const dialogueSignoff = (cfg, voice1, voice2, turns = []) =>
  call("/api/dialogue/signoff", {
    method: "POST",
    body: JSON.stringify({ cfg, voice1, voice2, turns }),
  });
export const getVoices = (engine = "") =>
  call(`/api/voices${engine ? `?engine=${encodeURIComponent(engine)}` : ""}`);
export const getVoicesFull = () => call("/api/voices?full=true");
export const renameVoice = (folder, label) =>
  call("/api/voices/rename", {
    method: "POST",
    body: JSON.stringify({ folder, label }),
  });
export const deleteVoice = (folder) =>
  call("/api/voices/delete", {
    method: "POST",
    body: JSON.stringify({ folder }),
  });
export const auditionVoice = (description, take = 1) =>
  call("/api/voices/audition", {
    method: "POST",
    body: JSON.stringify({ description, take }),
  });
export const cloneVoiceUpload = (file, transcript, description, engine) => {
  const body = new FormData();
  body.append("file", file);
  body.append("transcript", transcript);
  body.append("description", description);
  body.append("engine", engine);
  return call("/api/voices/clone", { method: "POST", body });
};
// The reference clip is streamed back as bytes (an <audio> element can't
// send the X-Narrator-Token header the way call() does for every other
// request), so this fetches it through call()'s auth and hands back a
// blob URL the <audio> tag can actually use.
export async function fetchVoiceReference(folder) {
  const tok = encodeURIComponent(folder.split("/").pop());
  const response = await fetch(`/api/voices/reference/${tok}`, {
    headers: { "X-Narrator-Token": token() },
  });
  if (!response.ok) throw new Error(`Couldn't load that reference clip.`);
  const blob = await response.blob();
  return URL.createObjectURL(blob);
}
export const getCustomSpeakers = () => call("/api/voices/custom-speakers");
export const fetchCustomSpeakers = () =>
  call("/api/voices/custom-speakers/fetch", { method: "POST" });
export const saveCustomPreset = (label, speaker, instruct) =>
  call("/api/voices/custom-preset", {
    method: "POST",
    body: JSON.stringify({ label, speaker, instruct }),
  });
export const deleteCustomPreset = (label) =>
  call("/api/voices/custom-preset/delete", {
    method: "POST",
    body: JSON.stringify({ folder: "", label }),
  });
export const refineLine = (request) =>
  call("/api/dialogue/refine", {
    method: "POST",
    body: JSON.stringify(request),
  });
export const startConvert = (body) =>
  call("/api/convert", { method: "POST", body: JSON.stringify(body) });
export const getPodcast = () => call("/api/podcast");
export const savePodcast = (values) =>
  call("/api/podcast", { method: "POST", body: JSON.stringify({ values }) });
export const publishTake = (take, title, notes) =>
  call("/api/publish", {
    method: "POST",
    body: JSON.stringify({ take, title, notes }),
  });
export const getChapters = (take = "") =>
  call(`/api/chapters?take=${encodeURIComponent(take)}`);
export const embedChapters = (take) =>
  call("/api/chapters/embed", {
    method: "POST",
    body: JSON.stringify({ take }),
  });
export const makeTranscript = (document, outDir = "") =>
  call("/api/transcript", {
    method: "POST",
    body: JSON.stringify({ document, out_dir: outDir }),
  });
export const listFiles = (path = "", onlyDirs = false, search = "") =>
  call(
    `/api/files?path=${encodeURIComponent(path)}&only_dirs=${onlyDirs}` +
      (search ? `&search=${encodeURIComponent(search)}` : "")
  );
export const validate = (cfg) =>
  call("/api/validate", { method: "POST", body: JSON.stringify({ cfg }) });
export const startRender = (cfg) =>
  call("/api/render", { method: "POST", body: JSON.stringify({ cfg }) });
export const listJobs = ({ query = "", status = "", kind = "" } = {}) =>
  call(
    `/api/jobs?query=${encodeURIComponent(query)}` +
      `&status=${encodeURIComponent(status)}&kind=${encodeURIComponent(kind)}`
  );
export const clearJobHistory = () =>
  call("/api/jobs/history", { method: "DELETE" });
export const cancelJob = (id) =>
  call(`/api/jobs/${id}/cancel`, { method: "POST" });

// Live log lines. EventSource can't send headers, which is why the token
// goes in the query string here (the server checks it the same way).
export function subscribe(jobId, onUpdate) {
  const source = new EventSource(
    `/api/jobs/${jobId}/events?token=${encodeURIComponent(token())}`
  );
  source.onmessage = (event) => {
    const snapshot = JSON.parse(event.data);
    onUpdate(snapshot);
    if (["done", "failed", "cancelled"].includes(snapshot.status)) {
      source.close();
    }
  };
  // A dropped stream must not look like a hung job, so the caller is told
  // to fall back to polling rather than waiting forever.
  source.onerror = () => {
    source.close();
    onUpdate({ streamFailed: true });
  };
  return () => source.close();
}

// Fallback when the stream drops: same data, just asked for.
export const pollJob = (id, since = 0) =>
  call(`/api/jobs/${id}?since=${since}`);
