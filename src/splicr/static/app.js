"use strict";

const byId = (id) => document.getElementById(id);

const elements = {
  form: byId("synthesis-form"),
  transcript: byId("transcript"),
  transcriptStats: byId("transcript-stats"),
  documentFile: byId("document-file"),
  dropZone: byId("document-drop-zone"),
  importStatus: byId("import-status"),
  removeNumericCitations: byId("remove-numeric-citations"),
  splitStrategy: byId("split-strategy"),
  previewButton: byId("preview-chunks"),
  chunkPreview: byId("chunk-preview"),
  previewSummary: byId("preview-summary"),
  previewDocument: byId("preview-document"),
  chunkList: byId("chunk-list"),
  provider: byId("provider"),
  model: byId("model"),
  modelOptions: byId("model-options"),
  voice: byId("voice"),
  tone: byId("tone"),
  vocalStyle: byId("vocal-style"),
  pace: byId("pace"),
  paceOutput: byId("pace-output"),
  paceTicks: byId("pace-ticks"),
  nonverbal: byId("nonverbal-frequency"),
  nonverbalOutput: byId("nonverbal-output"),
  nonverbalTicks: byId("nonverbal-ticks"),
  instructions: byId("instructions"),
  deliveryFieldset: document.querySelector(".delivery-fieldset"),
  submit: byId("submit-button"),
  connection: byId("connection-state"),
  connectionLabel: byId("connection-label"),
  globalMessage: byId("global-message"),
  emptyJob: byId("empty-job"),
  jobDetails: byId("job-details"),
  jobStatus: byId("job-status"),
  jobId: byId("job-id"),
  jobProgress: byId("job-progress"),
  jobProgressText: byId("job-progress-text"),
  jobProgressPercent: byId("job-progress-percent"),
  jobActivity: byId("job-activity"),
  jobActivityTitle: byId("job-activity-title"),
  jobActivityDetail: byId("job-activity-detail"),
  jobActivityExcerpt: byId("job-activity-excerpt"),
  positionFill: byId("position-fill"),
  documentPositionText: byId("document-position-text"),
  jobError: byId("job-error"),
  mediaPlayer: byId("media-player"),
  playerState: byId("player-state"),
  playerTime: byId("player-time"),
  jobAudio: byId("job-audio"),
  playbackRate: byId("playback-rate"),
  refreshAudio: byId("refresh-audio"),
  downloadAudio: byId("download-audio"),
  resumeJob: byId("resume-job"),
  cancelJob: byId("cancel-job"),
  retryJob: byId("retry-job"),
  refreshJobs: byId("refresh-jobs"),
  jobList: byId("job-list"),
  errorModal: byId("error-modal"),
  errorCode: byId("error-code"),
  errorDetail: byId("error-detail"),
  errorGuidance: byId("error-guidance"),
  closeErrorModal: byId("close-error-modal"),
  modalResume: byId("modal-resume"),
  modalCancel: byId("modal-cancel"),
  modalExport: byId("modal-export"),
};

const state = {
  providers: [],
  currentProvider: null,
  paceValues: ["very_slow", "slow", "normal", "fast", "very_fast"],
  nonverbalValues: ["never", "rare", "occasional", "frequent", "very_frequent"],
  activeJobId: null,
  activeJob: null,
  pollGeneration: 0,
  previewIsFresh: false,
  lastErrorKey: null,
  audioSnapshotJobId: null,
  audioSnapshotChunks: 0,
};

const errorGuidance = {
  AUTHENTICATION_ERROR: "Check that the provider API key is present, active, and authorized for this model.",
  INVALID_API_KEY: "Replace the configured provider key, then resume the checkpointed job.",
  RATE_LIMITED: "The provider is receiving too many requests. Wait briefly, then resume.",
  QUOTA_EXCEEDED: "The provider quota or billing limit was reached. Resolve it with the provider before resuming.",
  INVALID_REQUEST: "Review the model, voice, and direction settings. The completed chunks are still safe.",
  PROVIDER_UNAVAILABLE: "The speech provider is temporarily unavailable. Resume when service is restored.",
  NETWORK_ERROR: "Check this machine’s connection to the provider, then resume.",
  OUTPUT_LIMIT_EXCEEDED: "The configured output limit was reached. Export the completed audio or cancel this job.",
  CHECKPOINT_CORRUPT: "A saved chunk could not be validated. Keep this error detail when troubleshooting.",
  PROVIDER_AUTHENTICATION: "Check or rotate the provider API key, then resume the checkpointed job.",
  PROVIDER_RATE_LIMIT: "Wait for provider quota to recover, then resume from the saved chunks.",
  PROVIDER_REQUEST_REJECTED: "Review the current chunk, model, voice, and delivery settings before resuming.",
  PROVIDER_TIMEOUT: "Check connectivity and provider status, then resume the job.",
  OUTPUT_SIZE_LIMIT: "Raise the configured output limit or export the completed prefix and cancel.",
  INVALID_PROVIDER_AUDIO: "The provider returned incompatible audio; retry or select another provider.",
  CHECKPOINT_IO: "Check free disk space and the data-directory permissions before resuming.",
  INTERNAL_ERROR: "Inspect the server log. Completed chunks remain checkpointed and exportable.",
};

function humanize(value) {
  return String(value)
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function setConnection(kind, label) {
  elements.connection.classList.remove("ready", "error");
  if (kind) elements.connection.classList.add(kind);
  elements.connectionLabel.textContent = label;
}

function setMessage(message, isError = false) {
  elements.globalMessage.textContent = message;
  elements.globalMessage.classList.toggle("error", isError);
  elements.globalMessage.setAttribute("role", isError ? "alert" : "status");
}

function formatErrorDetail(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (!item || !item.msg) return String(item);
        const location = Array.isArray(item.loc)
          ? item.loc.filter((part) => part !== "body").join(".")
          : "";
        return location ? `${humanize(location)}: ${item.msg}` : item.msg;
      })
      .join("; ");
  }
  if (detail && typeof detail.message === "string") return detail.message;
  return null;
}

async function requestJson(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, { ...options, headers });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body && body.detail;
    const message = formatErrorDetail(detail) || `Request failed (${response.status})`;
    const error = new Error(message);
    error.status = response.status;
    error.code = (body && body.error_code) || (detail && detail.code) || null;
    throw error;
  }
  return body;
}

function replaceSelectOptions(select, values, selectedValue, labelFor = humanize) {
  const options = values.map((value) => {
    const option = document.createElement("option");
    const optionValue = typeof value === "string" ? value : value.id || value.name;
    if (!optionValue) throw new Error("A select option is missing its id or name.");
    option.value = optionValue;
    option.textContent = labelFor(value);
    return option;
  });
  select.replaceChildren(...options);
  if (selectedValue && options.some((option) => option.value === selectedValue)) {
    select.value = selectedValue;
  }
}

function replaceDataList(list, values) {
  const options = values.map((value, index) => {
    const option = document.createElement("option");
    option.value = String(index);
    option.label = humanize(value);
    return option;
  });
  list.replaceChildren(...options);
}

function configureRange(input, output, dataList, values, selectedValue, fallbackValue) {
  const safeValues = values.length ? values : [fallbackValue];
  const selectedIndex = safeValues.indexOf(selectedValue);
  input.min = "0";
  input.max = String(Math.max(0, safeValues.length - 1));
  input.value = String(selectedIndex >= 0 ? selectedIndex : safeValues.indexOf(fallbackValue));
  if (Number(input.value) < 0) input.value = "0";
  input.disabled = safeValues.length < 2;
  replaceDataList(dataList, safeValues);
  const label = humanize(safeValues[Number(input.value)]);
  output.textContent = label;
  input.setAttribute("aria-valuetext", label);
  return safeValues;
}

function configureProvider(providerName, selected = {}) {
  const provider = state.providers.find((item) => item.name === providerName);
  if (!provider) return;
  state.currentProvider = provider;
  elements.provider.value = provider.name;

  const capabilities = provider.capabilities || {};
  const models = (capabilities.models || []).length
    ? capabilities.models
    : [provider.default_model];
  const modelOptions = models.map((model) => {
    const option = document.createElement("option");
    option.value = model;
    return option;
  });
  elements.modelOptions.replaceChildren(...modelOptions);
  elements.model.value = selected.model || provider.default_model;

  replaceSelectOptions(
    elements.voice,
    capabilities.voices || [],
    selected.voice || provider.default_voice,
    (voice) => `${voice.id}${voice.traits.length ? ` · ${voice.traits.join(", ")}` : ""}`,
  );
  replaceSelectOptions(
    elements.tone,
    capabilities.tone_presets || ["neutral"],
    selected.controls && selected.controls.tone,
  );
  replaceSelectOptions(
    elements.vocalStyle,
    capabilities.vocal_styles || ["natural"],
    selected.controls && selected.controls.vocal_style,
  );

  state.paceValues = configureRange(
    elements.pace,
    elements.paceOutput,
    elements.paceTicks,
    capabilities.speech_paces || [],
    selected.controls && selected.controls.pace,
    "normal",
  );
  state.nonverbalValues = configureRange(
    elements.nonverbal,
    elements.nonverbalOutput,
    elements.nonverbalTicks,
    capabilities.nonverbal_frequencies || [],
    selected.controls && selected.controls.nonverbal_frequency,
    "never",
  );

  elements.instructions.disabled = capabilities.supports_custom_instructions === false;
  elements.instructions.value = selected.instructions || "";
  elements.model.disabled = false;
  elements.voice.disabled = false;
  elements.deliveryFieldset.disabled = false;
  elements.previewButton.disabled = false;
  elements.submit.disabled = false;
}

function updateRange(input, output, values) {
  const value = values[Number(input.value)] || values[0];
  const label = humanize(value);
  output.textContent = label;
  input.setAttribute("aria-valuetext", label);
}

function updateTranscriptStats() {
  const text = elements.transcript.value;
  const words = text.trim() ? text.trim().split(/\s+/u).length : 0;
  const bytes = new TextEncoder().encode(text).length;
  elements.transcriptStats.textContent = `${words.toLocaleString()} words · ${bytes.toLocaleString()} bytes`;
}

function markPreviewStale() {
  state.previewIsFresh = false;
  if (!elements.chunkPreview.hidden) {
    elements.chunkPreview.classList.add("is-stale");
    elements.previewSummary.textContent = "Document or split settings changed — preview again";
    elements.previewButton.textContent = "Refresh preview";
  }
}

function buildControls() {
  return {
    tone: elements.tone.value,
    pace: state.paceValues[Number(elements.pace.value)],
    vocal_style: elements.vocalStyle.value,
    nonverbal_frequency: state.nonverbalValues[Number(elements.nonverbal.value)],
  };
}

function buildJobPayload() {
  const instructions = elements.instructions.value.trim();
  const provider = elements.provider.value;
  if (!provider || !state.providers.some((item) => item.name === provider)) {
    throw new Error("Select a valid TTS provider before continuing.");
  }
  const model = elements.model.value.trim();
  const voice = elements.voice.value;
  return {
    text: elements.transcript.value,
    provider,
    model: model || null,
    voice: voice || null,
    instructions: instructions || null,
    controls: buildControls(),
    split_strategy: elements.splitStrategy.value,
    remove_numeric_citations: elements.removeNumericCitations.checked,
  };
}

function setImportStatus(message, isError = false) {
  elements.importStatus.textContent = message;
  elements.importStatus.classList.toggle("error", isError);
}

async function importDocument(file) {
  if (!file) return;
  const form = new FormData();
  form.append("file", file, file.name);
  elements.dropZone.classList.add("is-importing");
  elements.dropZone.setAttribute("aria-busy", "true");
  elements.documentFile.disabled = true;
  setImportStatus(`Importing ${file.name}…`);
  try {
    const imported = await requestJson("/v1/documents/import", {
      method: "POST",
      body: form,
    });
    if (!imported || typeof imported.text !== "string") {
      throw new Error("The importer did not return document text.");
    }
    elements.transcript.value = imported.text;
    updateTranscriptStats();
    markPreviewStale();
    const format = imported.format ? humanize(imported.format) : "Document";
    const metadata = imported.metadata || {};
    const extras = [];
    if (metadata.title) extras.push(metadata.title);
    if (Number.isFinite(metadata.heading_count)) {
      extras.push(`${metadata.heading_count.toLocaleString()} headings`);
    }
    const suffix = extras.length ? ` · ${extras.join(" · ")}` : "";
    setImportStatus(`${imported.filename || file.name} imported as ${format}${suffix}`);
    elements.transcript.focus();
  } catch (error) {
    setImportStatus(`Could not import ${file.name}: ${error.message}`, true);
  } finally {
    elements.dropZone.classList.remove("is-importing");
    elements.dropZone.removeAttribute("aria-busy");
    elements.documentFile.disabled = false;
    elements.documentFile.value = "";
  }
}

function activateChunk(index, active) {
  const selector = `[data-chunk-index="${index}"]`;
  document.querySelectorAll(selector).forEach((node) => {
    node.classList.toggle("is-active", active);
  });
}

function bindChunkActivation(node, index) {
  node.addEventListener("mouseenter", () => activateChunk(index, true));
  node.addEventListener("mouseleave", () => activateChunk(index, false));
  node.addEventListener("focus", () => activateChunk(index, true));
  node.addEventListener("blur", () => activateChunk(index, false));
}

function createChunkSegment(text, chunk, displayIndex) {
  const segment = document.createElement("span");
  segment.className = "chunk-segment";
  segment.dataset.chunkIndex = String(displayIndex);
  segment.tabIndex = 0;
  segment.textContent = text;
  segment.setAttribute(
    "aria-label",
    `Chunk ${displayIndex + 1}, ${chunk.word_count || 0} words, ${humanize(chunk.boundary || "semantic")} boundary`,
  );
  bindChunkActivation(segment, displayIndex);
  return segment;
}

function renderChunkPreview(preview) {
  const chunks = Array.isArray(preview.chunks) ? preview.chunks : [];
  const source = typeof preview.text === "string" ? preview.text : elements.transcript.value;
  const totalWords = Number(preview.total_words) || chunks.reduce((sum, chunk) => sum + (Number(chunk.word_count) || 0), 0);
  const totalBytes = Number(preview.total_bytes) || new TextEncoder().encode(source).length;
  elements.previewSummary.textContent = `${chunks.length.toLocaleString()} chunks · ${totalWords.toLocaleString()} words · ${totalBytes.toLocaleString()} bytes`;

  const ordered = chunks
    .map((chunk, displayIndex) => ({ chunk, displayIndex }))
    .sort((left, right) => Number(left.chunk.start_char) - Number(right.chunk.start_char));
  let cursor = 0;
  const rangesAreValid = ordered.every(({ chunk }) => {
    const start = Number(chunk.start_char);
    const end = Number(chunk.end_char);
    const valid = Number.isInteger(start) && Number.isInteger(end) && start >= cursor && end > start && end <= source.length;
    if (valid) cursor = end;
    return valid;
  });

  const documentNodes = [];
  if (rangesAreValid) {
    cursor = 0;
    ordered.forEach(({ chunk, displayIndex }) => {
      const start = Number(chunk.start_char);
      const end = Number(chunk.end_char);
      if (start > cursor) documentNodes.push(document.createTextNode(source.slice(cursor, start)));
      documentNodes.push(createChunkSegment(source.slice(start, end), chunk, displayIndex));
      cursor = end;
    });
    if (cursor < source.length) documentNodes.push(document.createTextNode(source.slice(cursor)));
  } else {
    chunks.forEach((chunk, displayIndex) => {
      if (displayIndex) documentNodes.push(document.createTextNode("\n\n"));
      documentNodes.push(createChunkSegment(String(chunk.text || ""), chunk, displayIndex));
    });
  }
  elements.previewDocument.replaceChildren(...documentNodes);

  const listItems = chunks.map((chunk, displayIndex) => {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.chunkIndex = String(displayIndex);

    const number = document.createElement("span");
    number.className = "chunk-number";
    number.textContent = String(displayIndex + 1).padStart(2, "0");

    const boundary = document.createElement("span");
    boundary.className = "chunk-boundary";
    boundary.textContent = humanize(chunk.boundary || "semantic");

    const meta = document.createElement("span");
    meta.className = "chunk-meta";
    meta.textContent = `${Number(chunk.word_count || 0).toLocaleString()} words · ${Number(chunk.byte_count || 0).toLocaleString()} bytes`;

    button.append(number, boundary, meta);
    bindChunkActivation(button, displayIndex);
    button.addEventListener("click", () => {
      const segment = elements.previewDocument.querySelector(`[data-chunk-index="${displayIndex}"]`);
      if (segment) {
        segment.scrollIntoView({ block: "center", behavior: "smooth" });
        segment.focus({ preventScroll: true });
      }
    });
    item.append(button);
    return item;
  });
  elements.chunkList.replaceChildren(...listItems);
  elements.chunkPreview.hidden = false;
  elements.chunkPreview.classList.remove("is-stale");
  elements.previewButton.textContent = "Refresh preview";
  state.previewIsFresh = true;
}

async function previewChunks() {
  if (!elements.transcript.value.trim()) {
    setMessage("Import or paste a document before previewing chunks.", true);
    elements.transcript.focus();
    return;
  }
  elements.previewButton.disabled = true;
  setMessage("Planning document chunks…");
  try {
    const preview = await requestJson("/v1/speech/preview", {
      method: "POST",
      body: JSON.stringify(buildJobPayload()),
    });
    renderChunkPreview(preview);
    setMessage("Chunk plan ready. Hover or focus any chunk to trace it through the document.");
  } catch (error) {
    setMessage(`Could not preview chunks: ${error.message}`, true);
  } finally {
    elements.previewButton.disabled = false;
  }
}

function safeSameOriginPath(value) {
  const url = new URL(value, window.location.origin);
  if (url.origin !== window.location.origin) {
    throw new Error("The audio URL did not belong to this SPLICR service.");
  }
  return `${url.pathname}${url.search}`;
}

function formatTime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const rounded = Math.floor(seconds);
  const minutes = Math.floor(rounded / 60);
  const remainder = String(rounded % 60).padStart(2, "0");
  return `${minutes}:${remainder}`;
}

function elapsedSince(value) {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return "";
  return formatTime(Math.max(0, (Date.now() - timestamp) / 1000));
}

function updatePlayerTime() {
  elements.playerTime.textContent = `${formatTime(elements.jobAudio.currentTime)} / ${formatTime(elements.jobAudio.duration)}`;
}

function clearAudioSource() {
  elements.mediaPlayer.hidden = true;
  elements.downloadAudio.hidden = true;
  elements.downloadAudio.removeAttribute("href");
  elements.modalExport.hidden = true;
  elements.modalExport.removeAttribute("href");
  if (elements.jobAudio.dataset.source) {
    elements.jobAudio.pause();
    elements.jobAudio.removeAttribute("src");
    delete elements.jobAudio.dataset.source;
    elements.jobAudio.load();
  }
}

function setAudioSource(value, isPartial) {
  const path = safeSameOriginPath(value);
  if (elements.jobAudio.dataset.source !== path) {
    elements.jobAudio.src = path;
    elements.jobAudio.dataset.source = path;
  }
  elements.jobAudio.playbackRate = Number(elements.playbackRate.value);
  elements.mediaPlayer.hidden = false;
  elements.playerState.textContent = isPartial ? "In-progress audio" : "Completed audio";
  elements.downloadAudio.href = path;
  elements.downloadAudio.textContent = isPartial ? "Export completed audio" : "Download WAV";
  elements.downloadAudio.hidden = false;
  elements.modalExport.href = path;
  elements.modalExport.hidden = false;
}

function guidanceFor(code) {
  const normalized = String(code || "UNKNOWN").toUpperCase();
  return errorGuidance[normalized] || "Review the details below. You can resume after correcting the cause, export completed audio, or cancel the job.";
}

function closeErrorDialog() {
  if (typeof elements.errorModal.close === "function" && elements.errorModal.open) {
    elements.errorModal.close();
  } else {
    elements.errorModal.removeAttribute("open");
  }
}

function showErrorDialog(job, detail, code) {
  const errorKey = `${job.id}:${job.status}:${code}:${detail}`;
  elements.errorCode.textContent = code;
  elements.errorDetail.textContent = detail;
  elements.errorGuidance.textContent = guidanceFor(code);
  elements.modalResume.hidden = !["paused", "failed"].includes(job.status);
  elements.modalResume.textContent = job.status === "failed" ? "Retry job" : "Resume job";
  elements.modalCancel.hidden = job.status === "cancelled" || job.status === "completed";
  if (state.lastErrorKey === errorKey || elements.errorModal.open) return;
  state.lastErrorKey = errorKey;
  if (typeof elements.errorModal.showModal === "function") {
    elements.errorModal.showModal();
  } else {
    elements.errorModal.setAttribute("open", "");
  }
}

function renderJob(job) {
  const hadAudioForJob =
    state.audioSnapshotJobId === job.id && Boolean(elements.jobAudio.dataset.source);
  const previousAudioChunks =
    state.audioSnapshotJobId === job.id ? state.audioSnapshotChunks : 0;
  state.activeJobId = job.id;
  state.activeJob = job;
  elements.emptyJob.hidden = true;
  elements.jobDetails.hidden = false;
  elements.jobId.textContent = job.id;

  elements.jobStatus.className = `status-badge ${job.status}`;
  elements.jobStatus.textContent = humanize(job.status);

  const totalChunks = Math.max(0, Number(job.total_chunks) || 0);
  const completedChunks = Math.max(0, Number(job.completed_chunks) || 0);
  const chunkProgress = totalChunks ? completedChunks / totalChunks : 0;
  const progress = Math.max(0, Math.min(1, Number(job.progress) || chunkProgress || 0));
  const percent = Math.round(progress * 100);
  const reportedChunkIndex = Number(job.current_chunk_index);
  const hasReportedChunkIndex =
    job.current_chunk_index !== null &&
    job.current_chunk_index !== undefined &&
    Number.isInteger(reportedChunkIndex);
  const fallbackChunkNumber = Math.min(completedChunks + 1, totalChunks || 1);
  const activeChunkNumber = hasReportedChunkIndex
    ? Math.max(1, Math.min(reportedChunkIndex + 1, totalChunks || reportedChunkIndex + 1))
    : fallbackChunkNumber;
  elements.jobProgress.value = progress;
  elements.jobProgress.textContent = `${percent}%`;
  elements.jobProgressPercent.textContent = `${percent}%`;
  elements.jobProgressText.textContent =
    job.status === "running"
      ? `${completedChunks} complete · chunk ${activeChunkNumber} in progress`
      : `${completedChunks} of ${totalChunks} chunks`;

  if (["queued", "running"].includes(job.status)) {
    const elapsed = elapsedSince(job.updated_at);
    elements.jobActivity.hidden = false;
    elements.jobActivityTitle.textContent =
      job.status === "running"
        ? `Synthesizing chunk ${activeChunkNumber} of ${totalChunks}`
        : `Queued · ${totalChunks} chunks planned`;
    elements.jobActivityDetail.textContent = [
      job.status === "running"
        ? `Working with ${humanize(job.provider || "provider")}`
        : "Waiting for the synthesis worker",
      elapsed ? `${elapsed} elapsed` : "",
    ]
      .filter(Boolean)
      .join(" · ");
    const excerpt = String(job.current_excerpt || "").trim();
    elements.jobActivityExcerpt.textContent = excerpt;
    elements.jobActivityExcerpt.hidden = !excerpt;
  } else {
    elements.jobActivity.hidden = true;
    elements.jobActivityExcerpt.hidden = true;
    elements.jobActivityExcerpt.textContent = "";
  }

  const currentChar = Number(job.current_char);
  const totalChars = Number(job.total_chars);
  if (Number.isFinite(currentChar) && Number.isFinite(totalChars) && totalChars > 0) {
    const positionPercent = Math.max(0, Math.min(100, (currentChar / totalChars) * 100));
    elements.positionFill.style.width = `${positionPercent}%`;
    elements.documentPositionText.textContent = `${currentChar.toLocaleString()} of ${totalChars.toLocaleString()} characters · ${Math.round(positionPercent)}% through document`;
  } else {
    elements.positionFill.style.width = `${percent}%`;
    elements.documentPositionText.textContent = `${percent}% through document by completed chunks`;
  }

  const detail = job.error_detail || job.error || "";
  const code = String(job.error_code || "UNKNOWN");
  elements.jobError.hidden = !detail;
  elements.jobError.textContent = detail ? `${code}: ${detail}` : "";

  elements.resumeJob.hidden = job.status !== "paused";
  elements.cancelJob.hidden = !["queued", "running", "paused"].includes(job.status);
  elements.retryJob.hidden = job.status !== "failed";

  const audioUrl = job.audio_url || job.partial_audio_url;
  if (audioUrl) {
    try {
      const isPartial = !job.audio_url;
      const shouldRefreshPartial =
        isPartial && hadAudioForJob && completedChunks !== previousAudioChunks;
      setAudioSource(audioUrl, isPartial);
      state.audioSnapshotJobId = job.id;
      state.audioSnapshotChunks = completedChunks;
      if (shouldRefreshPartial) refreshCurrentAudio();
    } catch (error) {
      setMessage(error.message, true);
    }
  } else {
    clearAudioSource();
    state.audioSnapshotJobId = job.id;
    state.audioSnapshotChunks = completedChunks;
  }

  if (detail && ["paused", "failed"].includes(job.status)) {
    showErrorDialog(job, detail, code);
  }
}

async function loadRecentJobs() {
  try {
    const jobs = await requestJson("/v1/speech/jobs?limit=20");
    if (!jobs.length) {
      const empty = document.createElement("li");
      empty.className = "job-list-empty";
      empty.textContent = "No jobs yet.";
      elements.jobList.replaceChildren(empty);
      return;
    }

    const items = jobs.map((job) => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";

      const title = document.createElement("span");
      title.className = "job-list-title";
      title.textContent = `${job.provider} · ${job.voice}`;

      const status = document.createElement("span");
      status.className = "job-list-status";
      status.textContent = humanize(job.status);

      const meta = document.createElement("span");
      meta.className = "job-list-meta";
      const date = new Date(job.created_at);
      meta.textContent = `${job.completed_chunks}/${job.total_chunks} chunks · ${date.toLocaleString()}`;

      button.append(title, status, meta);
      button.addEventListener("click", () => {
        state.pollGeneration += 1;
        configureProvider(job.provider, job);
        markPreviewStale();
        renderJob(job);
        if (["queued", "running"].includes(job.status)) startMonitoring(job.id);
      });
      item.append(button);
      return item;
    });
    elements.jobList.replaceChildren(...items);
    if (!state.activeJobId) {
      const recoverable = jobs.find((job) => ["queued", "running", "paused"].includes(job.status));
      if (recoverable) {
        configureProvider(recoverable.provider, recoverable);
        renderJob(recoverable);
        if (["queued", "running"].includes(recoverable.status)) startMonitoring(recoverable.id);
      }
    }
    return jobs;
  } catch (error) {
    setMessage(`Could not load recent jobs: ${error.message}`, true);
    return [];
  }
}

function startMonitoring(jobId) {
  const generation = ++state.pollGeneration;
  let transientFailures = 0;

  const poll = async () => {
    if (generation !== state.pollGeneration) return;
    try {
      const job = await requestJson(`/v1/speech/jobs/${encodeURIComponent(jobId)}`);
      if (generation !== state.pollGeneration) return;
      transientFailures = 0;
      renderJob(job);
      if (["queued", "running"].includes(job.status)) {
        window.setTimeout(poll, 1000);
      } else {
        await loadRecentJobs();
      }
    } catch (error) {
      if (generation !== state.pollGeneration) return;
      transientFailures += 1;
      const permanentClientError =
        error.status >= 400 &&
        error.status < 500 &&
        ![408, 409, 425, 429].includes(error.status);
      if (permanentClientError || transientFailures >= 5) {
        setMessage(`Job monitoring stopped: ${error.message}`, true);
        return;
      }
      const delay = Math.min(1000 * 2 ** (transientFailures - 1), 10_000);
      setMessage(`Live update interrupted; retrying in ${Math.round(delay / 1000)}s…`);
      window.setTimeout(poll, delay);
    }
  };

  void poll();
}

async function submitJob(event) {
  event.preventDefault();
  if (!elements.transcript.value.trim()) {
    setMessage("Import or paste a document before creating a job.", true);
    elements.transcript.focus();
    return;
  }

  elements.submit.disabled = true;
  setMessage("Creating speech job…");
  try {
    const job = await requestJson("/v1/speech/jobs", {
      method: "POST",
      body: JSON.stringify(buildJobPayload()),
    });
    setMessage("Job accepted. Progress is checkpointed after every completed chunk.");
    renderJob(job);
    startMonitoring(job.id);
    await loadRecentJobs();
  } catch (error) {
    setMessage(error.message, true);
  } finally {
    elements.submit.disabled = false;
  }
}

async function mutateCurrentJob(action) {
  if (!state.activeJobId) return;
  const isRetry = action === "retry";
  try {
    const job = await requestJson(
      `/v1/speech/jobs/${encodeURIComponent(state.activeJobId)}/${action}`,
      { method: "POST", body: "{}" },
    );
    closeErrorDialog();
    state.lastErrorKey = null;
    renderJob(job);
    if (["queued", "running"].includes(job.status)) startMonitoring(job.id);
    await loadRecentJobs();
    setMessage(isRetry ? "Job queued to retry from its saved checkpoints." : `Job ${action} request accepted.`);
  } catch (error) {
    setMessage(`Could not ${action} job: ${error.message}`, true);
  }
}

async function resumeCurrentJob() {
  const action = state.activeJob && state.activeJob.status === "failed" ? "retry" : "resume";
  await mutateCurrentJob(action);
}

async function cancelCurrentJob() {
  if (!state.activeJobId) return;
  const confirmed = window.confirm("Cancel this job? Completed audio checkpoints will not be presented as a finished result.");
  if (!confirmed) return;
  await mutateCurrentJob("cancel");
}

function refreshCurrentAudio() {
  const source = elements.jobAudio.dataset.source;
  if (!source) return;
  const currentTime = elements.jobAudio.currentTime;
  const wasPlaying = !elements.jobAudio.paused;
  const separator = source.includes("?") ? "&" : "?";
  elements.jobAudio.src = `${source}${separator}refresh=${Date.now()}`;
  elements.jobAudio.addEventListener(
    "loadedmetadata",
    () => {
      if (Number.isFinite(elements.jobAudio.duration)) {
        elements.jobAudio.currentTime = Math.min(currentTime, elements.jobAudio.duration);
      }
      if (wasPlaying) void elements.jobAudio.play().catch(() => {});
    },
    { once: true },
  );
  elements.jobAudio.load();
}

async function boot() {
  updateTranscriptStats();
  try {
    state.providers = await requestJson("/v1/providers");
    if (!state.providers.length) throw new Error("No TTS providers are configured.");
    replaceSelectOptions(elements.provider, state.providers, state.providers[0].name, (item) => humanize(item.name));
    elements.provider.disabled = false;
    configureProvider(state.providers[0].name);
    setConnection("ready", "Service ready");
    setMessage("");
    await loadRecentJobs();
  } catch (error) {
    setConnection("error", "Unavailable");
    setMessage(`SPLICR could not initialize: ${error.message}`, true);
  }
}

elements.transcript.addEventListener("input", () => {
  updateTranscriptStats();
  markPreviewStale();
});
elements.documentFile.addEventListener("change", () => void importDocument(elements.documentFile.files[0]));
elements.dropZone.addEventListener("click", () => elements.documentFile.click());
elements.dropZone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    elements.documentFile.click();
  }
});
["dragenter", "dragover"].forEach((type) => {
  elements.dropZone.addEventListener(type, (event) => {
    event.preventDefault();
    elements.dropZone.classList.add("is-dragging");
  });
});
["dragleave", "drop"].forEach((type) => {
  elements.dropZone.addEventListener(type, (event) => {
    event.preventDefault();
    elements.dropZone.classList.remove("is-dragging");
  });
});
elements.dropZone.addEventListener("drop", (event) => void importDocument(event.dataTransfer.files[0]));
elements.splitStrategy.addEventListener("change", markPreviewStale);
elements.removeNumericCitations.addEventListener("change", markPreviewStale);
elements.previewButton.addEventListener("click", () => void previewChunks());
elements.provider.addEventListener("change", () => {
  configureProvider(elements.provider.value);
  markPreviewStale();
});
elements.model.addEventListener("input", markPreviewStale);
elements.voice.addEventListener("change", markPreviewStale);
elements.tone.addEventListener("change", markPreviewStale);
elements.vocalStyle.addEventListener("change", markPreviewStale);
elements.instructions.addEventListener("input", markPreviewStale);
elements.pace.addEventListener("input", () => {
  updateRange(elements.pace, elements.paceOutput, state.paceValues);
  markPreviewStale();
});
elements.nonverbal.addEventListener("input", () => {
  updateRange(elements.nonverbal, elements.nonverbalOutput, state.nonverbalValues);
  markPreviewStale();
});
elements.form.addEventListener("submit", submitJob);
elements.resumeJob.addEventListener("click", () => void resumeCurrentJob());
elements.cancelJob.addEventListener("click", () => void cancelCurrentJob());
elements.retryJob.addEventListener("click", () => void mutateCurrentJob("retry"));
elements.refreshJobs.addEventListener("click", () => void loadRecentJobs());
elements.closeErrorModal.addEventListener("click", closeErrorDialog);
elements.modalResume.addEventListener("click", () => void resumeCurrentJob());
elements.modalCancel.addEventListener("click", () => void cancelCurrentJob());
elements.playbackRate.addEventListener("change", () => {
  elements.jobAudio.playbackRate = Number(elements.playbackRate.value);
});
elements.refreshAudio.addEventListener("click", refreshCurrentAudio);
elements.jobAudio.addEventListener("timeupdate", updatePlayerTime);
elements.jobAudio.addEventListener("loadedmetadata", updatePlayerTime);
elements.jobAudio.addEventListener("durationchange", updatePlayerTime);
elements.jobAudio.addEventListener("error", () => {
  if (elements.jobAudio.dataset.source) {
    setMessage("Audio could not be loaded. Refresh it after another chunk completes.", true);
  }
});

void boot();
