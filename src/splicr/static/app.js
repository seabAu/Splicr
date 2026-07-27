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
  addResource: byId("add-resource"),
  editResource: byId("edit-resource"),
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
  errorLogButton: byId("error-log-button"),
  errorUnreadBadge: byId("error-unread-badge"),
  errorToastRegion: byId("error-toast-region"),
  errorLogModal: byId("error-log-modal"),
  closeErrorLog: byId("close-error-log"),
  showUnreadErrors: byId("show-unread-errors"),
  showAllErrors: byId("show-all-errors"),
  errorLogCount: byId("error-log-count"),
  markAllErrorsRead: byId("mark-all-errors-read"),
  clearReadErrors: byId("clear-read-errors"),
  clearAllErrors: byId("clear-all-errors"),
  errorLogList: byId("error-log-list"),
  errorDetailsModal: byId("error-details-modal"),
  errorDetailsKicker: byId("error-details-kicker"),
  errorDetailsMessage: byId("error-details-message"),
  errorDetailsFacts: byId("error-details-facts"),
  errorRequestSection: byId("error-request-section"),
  errorResponseSection: byId("error-response-section"),
  errorExceptionSection: byId("error-exception-section"),
  errorContextSection: byId("error-context-section"),
  errorDetailsRequest: byId("error-details-request"),
  errorDetailsResponse: byId("error-details-response"),
  errorDetailsException: byId("error-details-exception"),
  errorDetailsContext: byId("error-details-context"),
  errorDetailsRaw: byId("error-details-raw"),
  closeErrorDetails: byId("close-error-details"),
  doneErrorDetails: byId("done-error-details"),
  copyErrorMessage: byId("copy-error-message"),
  copyAllErrorDetails: byId("copy-all-error-details"),
  markErrorRead: byId("mark-error-read"),
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
  viewJobDiagnostics: byId("view-job-diagnostics"),
  variablesPanel: byId("variables-panel"),
  jobVariablesList: byId("job-variables-list"),
  addJobVariable: byId("add-job-variable"),
  resourceModal: byId("resource-modal"),
  resourceForm: byId("resource-form"),
  resourceModalTitle: byId("resource-modal-title"),
  closeResourceModal: byId("close-resource-modal"),
  cancelResource: byId("cancel-resource"),
  deleteResource: byId("delete-resource"),
  resourceName: byId("resource-name"),
  resourceId: byId("resource-id"),
  resourceAdapter: byId("resource-adapter"),
  resourceBaseUrl: byId("resource-base-url"),
  resourceMethod: byId("resource-method"),
  resourceDefaultModel: byId("resource-default-model"),
  resourceDefaultVoice: byId("resource-default-voice"),
  resourceAuthPlacement: byId("resource-auth-placement"),
  resourceAuthName: byId("resource-auth-name"),
  resourceAuthPrefix: byId("resource-auth-prefix"),
  resourceApiKey: byId("resource-api-key"),
  clearResourceApiKey: byId("clear-resource-api-key"),
  resourceKeyStatus: byId("resource-key-status"),
  toggleResourceKey: byId("toggle-resource-key"),
  resourceHeadersJson: byId("resource-headers-json"),
  resourceQueryJson: byId("resource-query-json"),
  resourceDefaultVariablesJson: byId("resource-default-variables-json"),
  resourceModelsJson: byId("resource-models-json"),
  resourceVoicesJson: byId("resource-voices-json"),
  templateTree: byId("request-template-tree"),
  templateJson: byId("resource-template-json"),
  templateJsonStatus: byId("template-json-status"),
  addTemplateRootField: byId("add-template-root-field"),
  refreshTemplateJson: byId("refresh-template-json"),
  applyTemplateJson: byId("apply-template-json"),
  resourceMaxBytes: byId("resource-max-bytes"),
  resourceMaxCharacters: byId("resource-max-characters"),
  resourceMaxTokens: byId("resource-max-tokens"),
  resourceMaxWords: byId("resource-max-words"),
  resourceChunkBytes: byId("resource-chunk-bytes"),
  resourceChunkCharacters: byId("resource-chunk-characters"),
  resourceChunkWords: byId("resource-chunk-words"),
  resourcePacing: byId("resource-pacing"),
  resourceLimitBasis: byId("resource-limit-basis"),
  resourceTimeout: byId("resource-timeout"),
  resourceRetryAttempts: byId("resource-retry-attempts"),
  resourceRequestsMinute: byId("resource-requests-minute"),
  resourceMaxConcurrency: byId("resource-max-concurrency"),
  resourceResponseMode: byId("resource-response-mode"),
  resourceAudioPointer: byId("resource-audio-pointer"),
  resourceSampleRate: byId("resource-sample-rate"),
  resourceChannels: byId("resource-channels"),
  resourceSampleWidth: byId("resource-sample-width"),
  openProfiles: byId("open-profiles"),
  profilesModal: byId("profiles-modal"),
  closeProfilesModal: byId("close-profiles-modal"),
  profileSaveForm: byId("profile-save-form"),
  profileName: byId("profile-name"),
  profileIncludeJob: byId("profile-include-job"),
  refreshProfiles: byId("refresh-profiles"),
  profilesList: byId("profiles-list"),
};

const state = {
  providers: [],
  currentProvider: null,
  selectedResourceRevision: null,
  paceValues: ["very_slow", "slow", "normal", "fast", "very_fast"],
  nonverbalValues: ["never", "rare", "occasional", "frequent", "very_frequent"],
  activeJobId: null,
  activeJob: null,
  pollGeneration: 0,
  previewIsFresh: false,
  lastErrorKey: null,
  audioSnapshotJobId: null,
  audioSnapshotChunks: 0,
  resourcesEndpointAvailable: true,
  editingResource: null,
  requestTemplateNode: null,
  templateRawDirty: false,
  keyVisibilityTimer: null,
  jobVariables: {},
  errorEvents: new Map(),
  errorToasts: new Map(),
  errorToastTimers: new Map(),
  errorCursor: 0,
  errorUnreadCount: 0,
  errorTotalCount: 0,
  errorFilter: "unread",
  errorHistoryInitialized: false,
  errorPollTimer: null,
  selectedErrorId: null,
  selectedError: null,
  errorDetailsReturnDialog: null,
  errorDetailsReturnFocus: null,
  errorLogReturnFocus: null,
  currentJobErrorEventId: null,
};

const ERROR_POLL_INTERVAL_MS = 3_000;
const ERROR_TOAST_DURATION_MS = 12_000;
const DIAGNOSTIC_STRING_LIMIT = 12_000;
const DIAGNOSTIC_COLLECTION_LIMIT = 60;
const SENSITIVE_FIELD_RE = /(?:authorization|proxy.?authorization|cookie|set.?cookie|api.?key|token|password|passwd|secret|credential|private.?key|access.?key)/i;

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

function redactDiagnosticText(value) {
  return String(value)
    .replace(/\b(Bearer|Basic)\s+[^\s,;]+/gi, "$1 [REDACTED]")
    .replace(/([?&](?:api[_-]?key|token|password|secret|credential)=)[^&#\s]*/gi, "$1[REDACTED]")
    .replace(/((?:api[_-]?key|token|password|secret|credential)\s*[:=]\s*)[^\s,;}]+/gi, "$1[REDACTED]");
}

function boundedDiagnosticString(value) {
  const redacted = redactDiagnosticText(value);
  if (redacted.length <= DIAGNOSTIC_STRING_LIMIT) return redacted;
  return `${redacted.slice(0, DIAGNOSTIC_STRING_LIMIT)}\n[truncated ${redacted.length - DIAGNOSTIC_STRING_LIMIT} characters]`;
}

function isDocumentTextField(key, endpoint) {
  if (String(key).toLowerCase() !== "text") return false;
  return /\/v1\/(?:speech\/(?:jobs|preview)|profiles)(?:\/|$|\?)/.test(String(endpoint || ""));
}

function safeDiagnosticValue(value, options = {}) {
  const key = String(options.key || "");
  const endpoint = String(options.endpoint || "");
  const depth = Number(options.depth || 0);
  const seen = options.seen || new WeakSet();

  if (SENSITIVE_FIELD_RE.test(key)) return "[REDACTED]";
  if (isDocumentTextField(key, endpoint) && typeof value === "string") {
    return `[document text omitted: ${value.length.toLocaleString()} characters]`;
  }
  if (value === null || value === undefined || typeof value === "boolean" || typeof value === "number") {
    return value ?? null;
  }
  if (typeof value === "string") return boundedDiagnosticString(value);
  if (typeof value === "bigint") return String(value);
  if (typeof value === "function" || typeof value === "symbol") return `[${typeof value}]`;
  if (depth >= 8) return "[maximum diagnostic depth reached]";
  if (typeof Blob !== "undefined" && value instanceof Blob) {
    return {
      type: value.type || "application/octet-stream",
      size: value.size,
      name: typeof File !== "undefined" && value instanceof File ? value.name : undefined,
      data: "[binary omitted]",
    };
  }
  if (typeof Headers !== "undefined" && value instanceof Headers) {
    return safeDiagnosticValue(Object.fromEntries(value.entries()), {
      endpoint,
      depth: depth + 1,
      seen,
    });
  }
  if (typeof FormData !== "undefined" && value instanceof FormData) {
    const fields = {};
    for (const [field, item] of value.entries()) {
      fields[field] = safeDiagnosticValue(item, {
        key: field,
        endpoint,
        depth: depth + 1,
        seen,
      });
    }
    return fields;
  }
  if (value instanceof Error) {
    return safeDiagnosticValue(
      { name: value.name, message: value.message, stack: value.stack || null },
      { endpoint, depth: depth + 1, seen },
    );
  }
  if (typeof value !== "object") return boundedDiagnosticString(value);
  if (seen.has(value)) return "[circular reference]";
  seen.add(value);

  if (Array.isArray(value)) {
    const items = value.slice(0, DIAGNOSTIC_COLLECTION_LIMIT).map((item) =>
      safeDiagnosticValue(item, { endpoint, depth: depth + 1, seen }),
    );
    if (value.length > DIAGNOSTIC_COLLECTION_LIMIT) {
      items.push(`[${value.length - DIAGNOSTIC_COLLECTION_LIMIT} additional items omitted]`);
    }
    return items;
  }

  const result = {};
  const entries = Object.entries(value);
  entries.slice(0, DIAGNOSTIC_COLLECTION_LIMIT).forEach(([field, item]) => {
    result[field] = safeDiagnosticValue(item, {
      key: field,
      endpoint,
      depth: depth + 1,
      seen,
    });
  });
  if (entries.length > DIAGNOSTIC_COLLECTION_LIMIT) {
    result._omitted_fields = entries.length - DIAGNOSTIC_COLLECTION_LIMIT;
  }
  return result;
}

function summarizeRequestBody(body, endpoint) {
  if (body === undefined || body === null) return null;
  if (typeof body === "string") {
    try {
      return safeDiagnosticValue(JSON.parse(body), { endpoint });
    } catch (_error) {
      return safeDiagnosticValue(body, { endpoint });
    }
  }
  return safeDiagnosticValue(body, { endpoint });
}

function summarizeResponseBody(body, endpoint) {
  return safeDiagnosticValue(body, { endpoint });
}

function headersForDiagnostics(headers, endpoint) {
  return safeDiagnosticValue(Object.fromEntries(new Headers(headers || {}).entries()), { endpoint });
}

function diagnosticFingerprint(value) {
  let hash = 2166136261;
  const textValue = String(value);
  for (let index = 0; index < textValue.length; index += 1) {
    hash ^= textValue.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36);
}

async function reportClientError(diagnostic) {
  const { source: _ignoredSource, ...clientDiagnostic } = diagnostic;
  const safeDiagnostic = safeDiagnosticValue(
    {
      severity: "error",
      ...clientDiagnostic,
    },
    { endpoint: diagnostic.endpoint },
  );
  safeDiagnostic.code = String(safeDiagnostic.code || "client_error").slice(0, 100);
  safeDiagnostic.category = safeDiagnostic.category
    ? String(safeDiagnostic.category).slice(0, 100)
    : null;
  safeDiagnostic.message = String(safeDiagnostic.message || "Browser request failed").slice(0, 8_000);
  safeDiagnostic.method = safeDiagnostic.method ? String(safeDiagnostic.method).slice(0, 16) : null;
  safeDiagnostic.endpoint = safeDiagnostic.endpoint
    ? String(safeDiagnostic.endpoint).slice(0, 2_000)
    : null;
  try {
    const response = await fetch("/v1/errors/client", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(safeDiagnostic),
    });
    if (!response.ok) throw new Error(`Error reporting failed (${response.status})`);
    const textBody = await response.text();
    const payload = textBody ? JSON.parse(textBody) : null;
    const event = payload && (payload.event || payload.error || payload);
    if (event && event.id) {
      upsertErrorEvent(event, { notify: state.errorHistoryInitialized });
      return event;
    }
  } catch (_error) {
    // The original failure remains actionable even if the local server cannot persist it.
  }

  const fingerprint = diagnosticFingerprint(
    `${safeDiagnostic.method}:${safeDiagnostic.endpoint}:${safeDiagnostic.code}:${safeDiagnostic.message}`,
  );
  const existing = state.errorEvents.get(`client-${fingerprint}`);
  const now = new Date().toISOString();
  const event = {
    id: `client-${fingerprint}`,
    sequence: 0,
    count: Number(existing?.count || 0) + 1,
    first_occurred_at: existing?.first_occurred_at || now,
    last_occurred_at: now,
    read_at: null,
    source: "browser",
    ...safeDiagnostic,
  };
  upsertErrorEvent(event, { notify: true });
  return event;
}

async function requestJson(path, options = {}) {
  const { reportError = true, diagnosticLabel = null, ...fetchOptions } = options;
  const headers = new Headers(fetchOptions.headers || {});
  if (fetchOptions.body && !(fetchOptions.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const method = String(fetchOptions.method || "GET").toUpperCase();
  if (method === "GET" && fetchOptions.cache === undefined) {
    fetchOptions.cache = "no-store";
  }
  const request = {
    headers: headersForDiagnostics(headers, path),
    body: summarizeRequestBody(fetchOptions.body, path),
  };
  let response;
  try {
    response = await fetch(path, { ...fetchOptions, headers });
  } catch (cause) {
    const message = String(cause?.message || cause || "Network request failed");
    const error = new Error(`${diagnosticLabel || "Request"} could not reach the local service: ${message}`);
    error.status = null;
    error.code = "client_network_error";
    error.diagnostic = {
      code: error.code,
      category: "network",
      message: error.message,
      retryable: true,
      status_code: null,
      method,
      endpoint: path,
      request,
      response: null,
      exception: safeDiagnosticValue(cause, { endpoint: path }),
      context: diagnosticLabel ? { action: diagnosticLabel } : null,
    };
    if (reportError && !String(path).startsWith("/v1/errors")) void reportClientError(error.diagnostic);
    throw error;
  }

  const responseText = await response.text();
  let body = null;
  if (responseText) {
    try {
      body = JSON.parse(responseText);
    } catch (_error) {
      body = boundedDiagnosticString(responseText);
    }
  }
  if (!response.ok) {
    if (response.status === 401 && body && body.error_code === "authentication_required") {
      const destination = `${window.location.pathname}${window.location.search}${window.location.hash}`;
      window.location.assign(`/auth?next=${encodeURIComponent(destination)}`);
    }
    const detail = body && body.detail;
    const message =
      formatErrorDetail(detail) ||
      (typeof body === "string" ? body : null) ||
      `Request failed (${response.status})`;
    const error = new Error(message);
    error.status = response.status;
    error.code = (body && body.error_code) || (detail && detail.code) || null;
    error.diagnostic = {
      code: error.code || `http_${response.status}`,
      category: "api_request",
      message,
      retryable: response.status === 408 || response.status === 425 || response.status === 429 || response.status >= 500,
      status_code: response.status,
      method,
      endpoint: path,
      request,
      response: {
        status: response.status,
        status_text: response.statusText,
        headers: headersForDiagnostics(response.headers, path),
        body: summarizeResponseBody(body, path),
      },
      exception: null,
      context: diagnosticLabel ? { action: diagnosticLabel } : null,
    };
    if (reportError && !String(path).startsWith("/v1/errors")) void reportClientError(error.diagnostic);
    throw error;
  }
  return body;
}

function normalizedErrorEvent(value) {
  const endpoint = value && value.endpoint;
  const safeValue = safeDiagnosticValue(value || {}, { endpoint });
  const id = String(safeValue.id || `client-${diagnosticFingerprint(JSON.stringify(safeValue))}`);
  return {
    ...safeValue,
    id,
    sequence: Number(safeValue.sequence || 0),
    source: safeValue.source || "unknown",
    severity: safeValue.severity || "error",
    code: safeValue.code || "unknown_error",
    category: safeValue.category || null,
    message: safeValue.message || "An unknown error occurred.",
    retryable: safeValue.retryable ?? null,
    status_code: safeValue.status_code ?? null,
    method: safeValue.method || null,
    endpoint: safeValue.endpoint || null,
    request: safeValue.request ?? null,
    response: safeValue.response ?? null,
    exception: safeValue.exception ?? null,
    context: safeValue.context ?? null,
    provider: safeValue.provider || null,
    resource_revision: safeValue.resource_revision ?? null,
    job_id: safeValue.job_id || null,
    chunk_index: safeValue.chunk_index ?? null,
    attempt: safeValue.attempt ?? null,
    count: Math.max(1, Number(safeValue.count || 1)),
    first_occurred_at: safeValue.first_occurred_at || safeValue.occurred_at || null,
    last_occurred_at:
      safeValue.last_occurred_at || safeValue.occurred_at || safeValue.first_occurred_at || null,
    read_at: safeValue.read_at || null,
  };
}

function mergeErrorEvent(previous, incoming) {
  if (!previous) return incoming;
  const merged = { ...previous };
  Object.entries(incoming).forEach(([key, value]) => {
    if (value !== null && value !== undefined) merged[key] = value;
  });
  if (incoming.read_at === null && incoming.count > Number(previous.count || 0)) {
    merged.read_at = null;
  }
  return merged;
}

function errorEventTimestamp(event) {
  const timestamp = Date.parse(
    event.last_occurred_at || event.first_occurred_at || event.occurred_at || "",
  );
  return Number.isFinite(timestamp) ? timestamp : 0;
}

function errorEventLabel(event) {
  return humanize(event.code || event.category || "API error");
}

function errorStatusLabel(event) {
  if (event.status_code !== null && event.status_code !== undefined) {
    return String(event.status_code);
  }
  return String(event.code || "ERR").toUpperCase();
}

function createSvgIcon(pathData, viewBox = "0 0 24 24") {
  const namespace = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(namespace, "svg");
  svg.setAttribute("viewBox", viewBox);
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  const path = document.createElementNS(namespace, "path");
  path.setAttribute("d", pathData);
  svg.append(path);
  return svg;
}

function dismissErrorToast(errorId) {
  const toast = state.errorToasts.get(errorId);
  if (toast) toast.remove();
  state.errorToasts.delete(errorId);
  const timer = state.errorToastTimers.get(errorId);
  if (timer) window.clearTimeout(timer);
  state.errorToastTimers.delete(errorId);
}

function showErrorToast(event) {
  if (event.read_at) return;
  let toast = state.errorToasts.get(event.id);
  let title;
  let message;
  if (!toast) {
    toast = document.createElement("article");
    toast.className = "error-toast";
    toast.setAttribute("role", "status");
    toast.dataset.errorId = event.id;

    const copy = document.createElement("div");
    copy.className = "error-toast-copy";
    title = document.createElement("strong");
    message = document.createElement("span");
    copy.append(title, message);

    const view = document.createElement("button");
    view.type = "button";
    view.className = "error-toast-button";
    view.dataset.action = "view";
    view.append(
      createSvgIcon("M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Zm9.5 3.25A3.25 3.25 0 1 0 12 8.75a3.25 3.25 0 0 0 0 6.5Z"),
    );
    view.addEventListener("click", () => void openErrorDetails(event.id, view));

    const dismiss = document.createElement("button");
    dismiss.type = "button";
    dismiss.className = "error-toast-button";
    dismiss.dataset.action = "dismiss";
    dismiss.textContent = "×";
    dismiss.addEventListener("click", () => dismissErrorToast(event.id));

    toast.append(copy, view, dismiss);
    elements.errorToastRegion.append(toast);
    state.errorToasts.set(event.id, toast);
  } else {
    title = toast.querySelector("strong");
    message = toast.querySelector(".error-toast-copy span");
  }

  const countSuffix = Number(event.count || 1) > 1 ? ` ×${event.count}` : "";
  title.textContent = `${errorEventLabel(event)}${countSuffix}`;
  message.textContent = String(event.message || "An unknown error occurred.");
  const view = toast.querySelector('[data-action="view"]');
  const dismiss = toast.querySelector('[data-action="dismiss"]');
  view.setAttribute("aria-label", `View error details: ${errorEventLabel(event)}`);
  view.title = "View error details";
  dismiss.setAttribute("aria-label", `Dismiss notification: ${errorEventLabel(event)}`);
  dismiss.title = "Dismiss notification";

  const currentTimer = state.errorToastTimers.get(event.id);
  if (currentTimer) window.clearTimeout(currentTimer);
  state.errorToastTimers.set(
    event.id,
    window.setTimeout(() => dismissErrorToast(event.id), ERROR_TOAST_DURATION_MS),
  );
}

function updateErrorCounts() {
  const visibleEvents = [...state.errorEvents.values()];
  const localUnread = visibleEvents.filter((event) => !event.read_at).length;
  if (state.errorUnreadCount < localUnread) state.errorUnreadCount = localUnread;
  if (state.errorTotalCount < visibleEvents.length) state.errorTotalCount = visibleEvents.length;
  const unread = Math.max(0, Number(state.errorUnreadCount || 0));
  const total = Math.max(0, Number(state.errorTotalCount || 0));
  elements.errorUnreadBadge.hidden = unread === 0;
  elements.errorUnreadBadge.textContent = unread > 99 ? "99+" : String(unread);
  elements.errorLogButton.setAttribute(
    "aria-label",
    `Open error log, ${unread} unread error${unread === 1 ? "" : "s"}`,
  );
  elements.errorLogCount.textContent = `${unread} unread · ${total} total`;
  elements.markAllErrorsRead.disabled = unread === 0;
  elements.clearReadErrors.disabled = total === unread;
  elements.clearAllErrors.disabled = total === 0;
}

function upsertErrorEvent(value, options = {}) {
  const event = normalizedErrorEvent(value);
  const previous = state.errorEvents.get(event.id);
  const previousCount = Number(previous?.count || 0);
  const previousTime = errorEventTimestamp(previous || {});
  const merged = mergeErrorEvent(previous, event);
  state.errorEvents.set(event.id, merged);
  state.errorCursor = Math.max(state.errorCursor, Number(merged.sequence || 0));
  if (merged.read_at) dismissErrorToast(merged.id);
  if (options.notify && !merged.read_at) {
    const changed = !previous || merged.count > previousCount || errorEventTimestamp(merged) > previousTime;
    if (changed) showErrorToast(merged);
  }
  updateErrorCounts();
  if (elements.errorLogModal.open) renderErrorLog();
  return merged;
}

function relativeErrorTime(value) {
  const timestamp = Date.parse(value || "");
  if (!Number.isFinite(timestamp)) return "Time unavailable";
  const elapsed = Math.max(0, Date.now() - timestamp);
  if (elapsed < 60_000) return "Just now";
  if (elapsed < 3_600_000) return `${Math.floor(elapsed / 60_000)}m ago`;
  if (elapsed < 86_400_000) return `${Math.floor(elapsed / 3_600_000)}h ago`;
  return new Date(timestamp).toLocaleString();
}

function createErrorRowButton(label, iconPath, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "error-row-button";
  button.setAttribute("aria-label", label);
  button.title = label;
  button.append(createSvgIcon(iconPath));
  button.addEventListener("click", onClick);
  return button;
}

function renderErrorLog() {
  elements.showUnreadErrors.classList.toggle("is-active", state.errorFilter === "unread");
  elements.showUnreadErrors.setAttribute(
    "aria-pressed",
    state.errorFilter === "unread" ? "true" : "false",
  );
  elements.showAllErrors.classList.toggle("is-active", state.errorFilter === "all");
  elements.showAllErrors.setAttribute("aria-pressed", state.errorFilter === "all" ? "true" : "false");

  const events = [...state.errorEvents.values()]
    .filter((event) => state.errorFilter === "all" || !event.read_at)
    .sort((left, right) => errorEventTimestamp(right) - errorEventTimestamp(left));
  if (!events.length) {
    const empty = document.createElement("li");
    empty.className = "error-log-empty";
    empty.textContent = state.errorFilter === "all" ? "No errors have been recorded." : "No unread errors.";
    elements.errorLogList.replaceChildren(empty);
    updateErrorCounts();
    return;
  }

  const rows = events.map((event) => {
    const row = document.createElement("li");
    row.className = `error-log-row${event.read_at ? " is-read" : ""}`;
    const summary = document.createElement("div");
    summary.className = "error-log-summary";
    const meta = document.createElement("div");
    meta.className = "error-log-meta";
    const status = document.createElement("span");
    status.className = "error-status-chip";
    status.textContent = errorStatusLabel(event);
    const source = document.createElement("span");
    source.textContent = humanize(event.provider || event.source || "unknown source");
    const time = document.createElement("time");
    time.dateTime = event.last_occurred_at || "";
    time.textContent = relativeErrorTime(event.last_occurred_at);
    meta.append(status, source, time);
    if (event.count > 1) {
      const count = document.createElement("span");
      count.className = "error-count-chip";
      count.textContent = `×${event.count}`;
      meta.append(count);
    }
    const message = document.createElement("strong");
    message.textContent = String(event.message || "An unknown error occurred.");
    message.title = message.textContent;
    summary.append(meta, message);

    const actions = document.createElement("div");
    actions.className = "error-row-actions";
    actions.append(
      createErrorRowButton(
        `View error details: ${errorEventLabel(event)}`,
        "M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Zm9.5 3.25A3.25 3.25 0 1 0 12 8.75a3.25 3.25 0 0 0 0 6.5Z",
        (clickEvent) => void openErrorDetails(event.id, clickEvent.currentTarget, elements.errorLogModal),
      ),
    );
    if (!event.read_at) {
      actions.append(
        createErrorRowButton(
          `Mark ${errorEventLabel(event)} as read`,
          "m5 12 4 4L19 6",
          () => void markErrorEventRead(event.id),
        ),
      );
    }
    row.append(summary, actions);
    return row;
  });
  elements.errorLogList.replaceChildren(...rows);
  updateErrorCounts();
}

async function syncErrorEvents(options = {}) {
  // Re-read the bounded recent window so deduplicated events with a stable ID can update their count.
  const after = 0;
  const wasInitialized = state.errorHistoryInitialized;
  const priorIds = options.reset ? [...state.errorEvents.keys()] : [];
  const payload = await requestJson(
    `/v1/errors?after=${encodeURIComponent(after)}&limit=100&unread_only=false`,
    { reportError: false },
  );
  if (options.reset) {
    state.errorEvents.clear();
    state.errorCursor = 0;
  }
  const events = collectionItems(payload, "events", "items");
  events.forEach((event) => {
    upsertErrorEvent(event, {
      notify: Boolean(options.notify ?? wasInitialized),
    });
  });
  priorIds.forEach((id) => {
    if (!state.errorEvents.has(id)) dismissErrorToast(id);
  });
  state.errorUnreadCount = Math.max(0, Number(payload?.unread_count ?? state.errorUnreadCount));
  state.errorTotalCount = Math.max(0, Number(payload?.total_count ?? state.errorTotalCount));
  state.errorHistoryInitialized = true;
  updateErrorCounts();
  if (elements.errorLogModal.open) renderErrorLog();
  return events;
}

function scheduleErrorPoll() {
  if (state.errorPollTimer) window.clearTimeout(state.errorPollTimer);
  state.errorPollTimer = window.setTimeout(async () => {
    try {
      await syncErrorEvents();
    } catch (_error) {
      // Error-center polling is deliberately silent to avoid recursive error reports.
    } finally {
      scheduleErrorPoll();
    }
  }, ERROR_POLL_INTERVAL_MS);
}

async function openErrorLog() {
  state.errorLogReturnFocus = document.activeElement;
  renderErrorLog();
  showDialog(elements.errorLogModal, elements.showUnreadErrors);
  try {
    await syncErrorEvents({ reset: true, notify: false });
  } catch (error) {
    setMessage(`Could not refresh the error log: ${error.message}`, true);
  }
}

function closeErrorLogDialog(options = {}) {
  closeDialog(elements.errorLogModal);
  if (options.restoreFocus !== false) {
    const target = state.errorLogReturnFocus;
    if (target && target.isConnected) target.focus();
    else elements.errorLogButton.focus();
  }
}

function prettyDiagnosticValue(value) {
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch (_error) {
    return String(value);
  }
}

function hasDiagnosticValue(value) {
  if (value === null || value === undefined || value === "") return false;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "object") return Object.keys(value).length > 0;
  return true;
}

function appendErrorFact(label, value) {
  if (value === null || value === undefined || value === "") return;
  const wrapper = document.createElement("div");
  const term = document.createElement("dt");
  term.textContent = label;
  const description = document.createElement("dd");
  description.textContent = String(value);
  wrapper.append(term, description);
  elements.errorDetailsFacts.append(wrapper);
}

function setDiagnosticSection(section, output, value) {
  const present = hasDiagnosticValue(value);
  section.hidden = !present;
  output.textContent = present ? prettyDiagnosticValue(value) : "";
}

function renderErrorDetails(value) {
  const event = normalizedErrorEvent(value);
  const safeEvent = safeDiagnosticValue(event, { endpoint: event.endpoint });
  state.selectedError = safeEvent;
  state.selectedErrorId = event.id;
  elements.errorDetailsKicker.textContent = `${humanize(event.source)} · ${errorEventLabel(event)}`;
  elements.errorDetailsMessage.textContent = String(event.message || "An unknown error occurred.");
  elements.errorDetailsFacts.replaceChildren();
  [
    ["Error ID", event.id],
    ["Sequence", event.sequence || null],
    ["Source", event.source],
    ["Severity", event.severity],
    ["Code", event.code],
    ["Category", event.category],
    ["Retryable", event.retryable === null ? null : event.retryable ? "Yes" : "No"],
    ["HTTP status", event.status_code],
    ["HTTP method", event.method],
    ["Endpoint", event.endpoint],
    ["Provider", event.provider],
    ["Resource revision", event.resource_revision],
    ["Job ID", event.job_id],
    ["Chunk index", event.chunk_index],
    ["Attempt", event.attempt],
    ["Occurrences", event.count],
    ["First occurrence", event.first_occurred_at],
    ["Last occurrence", event.last_occurred_at],
    ["Read at", event.read_at],
  ].forEach(([label, fact]) => appendErrorFact(label, fact));
  setDiagnosticSection(elements.errorRequestSection, elements.errorDetailsRequest, safeEvent.request);
  setDiagnosticSection(elements.errorResponseSection, elements.errorDetailsResponse, safeEvent.response);
  setDiagnosticSection(elements.errorExceptionSection, elements.errorDetailsException, safeEvent.exception);
  setDiagnosticSection(elements.errorContextSection, elements.errorDetailsContext, safeEvent.context);
  elements.errorDetailsRaw.textContent = prettyDiagnosticValue(safeEvent);
  elements.markErrorRead.hidden = Boolean(event.read_at);
}

async function openErrorDetails(errorId, trigger = document.activeElement, returnDialog = null) {
  const normalizedId = String(errorId || "");
  let existing = state.errorEvents.get(normalizedId);
  let loadedCompleteRecord = false;
  if (!existing && normalizedId) {
    try {
      const detail = await requestJson(`/v1/errors/${encodeURIComponent(normalizedId)}`, {
        reportError: false,
      });
      const event = detail && (detail.event || detail.error || detail);
      if (event && event.id) {
        existing = upsertErrorEvent(event, { notify: false });
        loadedCompleteRecord = true;
      }
    } catch (error) {
      setMessage(`Could not load the diagnostic report: ${error.message}`, true);
      return;
    }
  }
  if (!existing) return;
  state.errorDetailsReturnFocus = trigger;
  state.errorDetailsReturnDialog = returnDialog;
  if (!state.errorDetailsReturnDialog && elements.errorLogModal.open) {
    state.errorDetailsReturnDialog = elements.errorLogModal;
  }
  if (!state.errorDetailsReturnDialog && elements.errorModal.open) {
    state.errorDetailsReturnDialog = elements.errorModal;
  }
  if (state.errorDetailsReturnDialog?.open) closeDialog(state.errorDetailsReturnDialog);
  renderErrorDetails(existing);
  showDialog(elements.errorDetailsModal, elements.closeErrorDetails);
  if (loadedCompleteRecord) return;
  try {
    const detail = await requestJson(`/v1/errors/${encodeURIComponent(normalizedId)}`, {
      reportError: false,
    });
    const event = detail && (detail.event || detail.error || detail);
    if (event && event.id) renderErrorDetails(upsertErrorEvent(event, { notify: false }));
  } catch (error) {
    setMessage(`Could not load the complete diagnostic report: ${error.message}`, true);
  }
}

function closeErrorDetailsDialog() {
  closeDialog(elements.errorDetailsModal);
  const returnDialog = state.errorDetailsReturnDialog;
  const returnFocus = state.errorDetailsReturnFocus;
  state.errorDetailsReturnDialog = null;
  state.errorDetailsReturnFocus = null;
  if (returnDialog && returnDialog.isConnected) {
    showDialog(returnDialog, returnFocus?.isConnected ? returnFocus : undefined);
  } else if (returnFocus?.isConnected) {
    returnFocus.focus();
  } else {
    elements.errorLogButton.focus();
  }
}

async function copyDiagnosticText(value, successMessage = "Diagnostic details copied.") {
  try {
    await navigator.clipboard.writeText(String(value || ""));
    setMessage(successMessage);
  } catch (error) {
    setMessage(`Could not copy diagnostic details: ${error.message}`, true);
  }
}

async function markErrorEventRead(errorId) {
  if (!errorId) return;
  try {
    const payload = await requestJson(`/v1/errors/${encodeURIComponent(errorId)}/read`, {
      method: "POST",
      body: "{}",
      reportError: false,
    });
    const current = state.errorEvents.get(errorId);
    const event = payload && (payload.event || payload.error || payload);
    upsertErrorEvent(
      event?.id ? event : { ...current, id: errorId, read_at: new Date().toISOString() },
      { notify: false },
    );
    state.errorUnreadCount = Math.max(0, state.errorUnreadCount - (current?.read_at ? 0 : 1));
    dismissErrorToast(errorId);
    if (state.selectedErrorId === errorId) renderErrorDetails(state.errorEvents.get(errorId));
    renderErrorLog();
  } catch (error) {
    setMessage(`Could not mark the error as read: ${error.message}`, true);
  }
}

async function markAllErrorEventsRead() {
  try {
    await requestJson("/v1/errors/read-all", { method: "POST", body: "{}", reportError: false });
    const timestamp = new Date().toISOString();
    state.errorEvents.forEach((event, id) => {
      state.errorEvents.set(id, { ...event, read_at: event.read_at || timestamp });
      dismissErrorToast(id);
    });
    state.errorUnreadCount = 0;
    renderErrorLog();
    updateErrorCounts();
  } catch (error) {
    setMessage(`Could not mark all errors as read: ${error.message}`, true);
  }
}

async function clearErrorEvents(scope) {
  const label = scope === "all" ? "all errors" : "read errors";
  if (scope === "all" && !window.confirm("Clear the complete error log? This cannot be undone.")) return;
  try {
    await requestJson(`/v1/errors?scope=${encodeURIComponent(scope)}`, {
      method: "DELETE",
      reportError: false,
    });
    state.errorEvents.forEach((event, id) => {
      if (scope === "all" || event.read_at) {
        state.errorEvents.delete(id);
        dismissErrorToast(id);
      }
    });
    if (scope === "all") {
      state.errorUnreadCount = 0;
      state.errorTotalCount = 0;
      state.errorCursor = 0;
    } else {
      state.errorTotalCount = Math.max(state.errorUnreadCount, state.errorEvents.size);
    }
    renderErrorLog();
    updateErrorCounts();
    setMessage(`${humanize(label)} cleared.`);
  } catch (error) {
    setMessage(`Could not clear ${label}: ${error.message}`, true);
  }
}

function trapDialogFocus(dialog, event) {
  if (event.key !== "Tab" || !dialog.open) return;
  const focusable = [...dialog.querySelectorAll(
    'button:not([disabled]):not([hidden]), a[href]:not([hidden]), input:not([disabled]):not([hidden]), select:not([disabled]):not([hidden]), textarea:not([disabled]):not([hidden]), [tabindex]:not([tabindex="-1"]):not([hidden])',
  )].filter((node) => node.offsetParent !== null);
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function resourceId(resource) {
  return resource && (resource.id || resource.resource_id || resource.name);
}

function resourceLabel(resource) {
  return (resource && (resource.display_name || resource.name || resource.id)) || "API resource";
}

function collectionItems(value, ...keys) {
  if (Array.isArray(value)) return value;
  for (const key of keys) {
    if (value && Array.isArray(value[key])) return value[key];
  }
  return [];
}

function showDialog(dialog, focusTarget) {
  if (typeof dialog.showModal === "function") {
    if (!dialog.open) dialog.showModal();
  } else {
    dialog.setAttribute("open", "");
  }
  window.setTimeout(() => {
    if (focusTarget) focusTarget.focus();
  }, 0);
}

function closeDialog(dialog) {
  if (typeof dialog.close === "function" && dialog.open) {
    dialog.close();
  } else {
    dialog.removeAttribute("open");
  }
}

function variableDisplayValue(value) {
  if (typeof value === "string") return value;
  if (value === undefined) return "";
  return JSON.stringify(value);
}

function parseVariableValue(value) {
  const trimmed = value.trim();
  if (!trimmed) return "";
  try {
    return JSON.parse(trimmed);
  } catch (_error) {
    return value;
  }
}

function createVariableRow(key = "", value = "") {
  const row = document.createElement("div");
  row.className = "key-value-row";

  const keyInput = document.createElement("input");
  keyInput.type = "text";
  keyInput.value = key;
  keyInput.placeholder = "Variable name";
  keyInput.setAttribute("aria-label", "Variable name");

  const valueInput = document.createElement("input");
  valueInput.type = "text";
  valueInput.value = variableDisplayValue(value);
  valueInput.placeholder = "Value (plain text or JSON)";
  valueInput.setAttribute("aria-label", key ? `Value for ${key}` : "Variable value");

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "remove-row-button";
  remove.textContent = "×";
  remove.setAttribute("aria-label", key ? `Remove ${key}` : "Remove variable");
  remove.addEventListener("click", () => row.remove());
  row.append(keyInput, valueInput, remove);
  return row;
}

function renderJobVariables(variables = {}) {
  const rows = Object.entries(variables).map(([key, value]) => createVariableRow(key, value));
  elements.jobVariablesList.replaceChildren(...rows);
  state.jobVariables = { ...variables };
}

function collectJobVariables() {
  const variables = {};
  elements.jobVariablesList.querySelectorAll(".key-value-row").forEach((row) => {
    const inputs = row.querySelectorAll("input");
    const key = inputs[0].value.trim();
    if (!key) return;
    if (Object.hasOwn(variables, key)) {
      throw new Error(`API variable ${key} is listed more than once.`);
    }
    variables[key] = parseVariableValue(inputs[1].value);
  });
  state.jobVariables = variables;
  return variables;
}

function defaultTemplateNode(type = "string") {
  if (type === "object") return { type, children: [] };
  if (type === "array") return { type, children: [] };
  if (type === "number") return { type, value: 0 };
  if (type === "boolean") return { type, value: false };
  if (type === "null") return { type, value: null };
  return { type: "string", value: "" };
}

function templateNodeFromValue(value) {
  if (value === null) return defaultTemplateNode("null");
  if (Array.isArray(value)) {
    return { type: "array", children: value.map((item) => templateNodeFromValue(item)) };
  }
  if (typeof value === "object") {
    return {
      type: "object",
      children: Object.entries(value).map(([key, item]) => ({
        key,
        node: templateNodeFromValue(item),
      })),
    };
  }
  return { type: typeof value, value };
}

function templateValueFromNode(node) {
  if (node.type === "object") {
    const value = {};
    node.children.forEach((entry) => {
      const key = String(entry.key || "").trim();
      if (!key) throw new Error("Every object field in the request template needs a name.");
      if (Object.hasOwn(value, key)) throw new Error(`Request field ${key} is duplicated.`);
      value[key] = templateValueFromNode(entry.node);
    });
    return value;
  }
  if (node.type === "array") return node.children.map((child) => templateValueFromNode(child));
  if (node.type === "number") {
    const number = Number(node.value);
    if (!Number.isFinite(number)) throw new Error("Request-template numbers must be finite.");
    return number;
  }
  if (node.type === "boolean") return Boolean(node.value);
  if (node.type === "null") return null;
  return String(node.value ?? "");
}

function templateTypeSelect(node) {
  const select = document.createElement("select");
  select.setAttribute("aria-label", "JSON value type");
  ["object", "array", "string", "number", "boolean", "null"].forEach((type) => {
    const option = document.createElement("option");
    option.value = type;
    option.textContent = humanize(type);
    select.append(option);
  });
  select.value = node.type;
  return select;
}

function nextObjectKey(node) {
  const used = new Set(node.children.map((entry) => entry.key));
  let index = node.children.length + 1;
  while (used.has(`field_${index}`)) index += 1;
  return `field_${index}`;
}

function syncTemplateJson(message = "JSON preview synchronized.") {
  try {
    const value = templateValueFromNode(state.requestTemplateNode);
    elements.templateJson.value = JSON.stringify(value, null, 2);
    state.templateRawDirty = false;
    elements.templateJsonStatus.textContent = message;
    elements.templateJsonStatus.classList.remove("error");
    return value;
  } catch (error) {
    elements.templateJsonStatus.textContent = error.message;
    elements.templateJsonStatus.classList.add("error");
    throw error;
  }
}

function renderTemplateNode(node, options = {}) {
  const wrapper = document.createElement("div");
  wrapper.className = "json-tree-node";
  const row = document.createElement("div");
  row.className = "json-node-row";

  if (options.entry) {
    const keyInput = document.createElement("input");
    keyInput.value = options.entry.key;
    keyInput.placeholder = "Field name";
    keyInput.setAttribute("aria-label", "Object field name");
    keyInput.addEventListener("input", () => {
      options.entry.key = keyInput.value;
    });
    row.append(keyInput);
  } else {
    const label = document.createElement("span");
    label.className = "json-node-label";
    label.textContent = options.isRoot ? "$ root" : `[${options.index}]`;
    row.append(label);
  }

  const typeSelect = templateTypeSelect(node);
  typeSelect.addEventListener("change", () => {
    const replacement = defaultTemplateNode(typeSelect.value);
    Object.keys(node).forEach((key) => delete node[key]);
    Object.assign(node, replacement);
    renderTemplateTree();
  });
  row.append(typeSelect);

  if (node.type === "string" || node.type === "number") {
    const valueInput = document.createElement("input");
    valueInput.type = node.type === "number" ? "number" : "text";
    valueInput.value = String(node.value ?? "");
    valueInput.placeholder = node.type === "string" ? "Value or {{ variable }}" : "0";
    valueInput.setAttribute("aria-label", `${humanize(node.type)} value`);
    valueInput.addEventListener("input", () => {
      node.value = node.type === "number" ? Number(valueInput.value) : valueInput.value;
    });
    row.append(valueInput);
  } else if (node.type === "boolean") {
    const valueInput = document.createElement("input");
    valueInput.type = "checkbox";
    valueInput.checked = Boolean(node.value);
    valueInput.setAttribute("aria-label", "Boolean value");
    valueInput.addEventListener("change", () => {
      node.value = valueInput.checked;
    });
    row.append(valueInput);
  } else {
    const valueLabel = document.createElement("span");
    valueLabel.className = "json-node-label";
    valueLabel.textContent = node.type === "null" ? "null" : `${node.children.length} items`;
    row.append(valueLabel);
  }

  if (node.type === "object" || node.type === "array") {
    const add = document.createElement("button");
    add.type = "button";
    add.className = "json-add-button";
    add.textContent = node.type === "object" ? "+ Field" : "+ Item";
    add.addEventListener("click", () => {
      if (node.type === "object") {
        node.children.push({ key: nextObjectKey(node), node: defaultTemplateNode("string") });
      } else {
        node.children.push(defaultTemplateNode("string"));
      }
      renderTemplateTree();
    });
    row.append(add);
  } else {
    row.append(document.createElement("span"));
  }

  if (!options.isRoot) {
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "json-remove-button";
    remove.textContent = "Remove";
    remove.addEventListener("click", options.remove);
    row.append(remove);
  } else {
    row.append(document.createElement("span"));
  }
  wrapper.append(row);

  if (node.type === "object" || node.type === "array") {
    const children = document.createElement("div");
    children.className = "json-node-children";
    node.children.forEach((child, index) => {
      const childNode = node.type === "object" ? child.node : child;
      children.append(
        renderTemplateNode(childNode, {
          entry: node.type === "object" ? child : null,
          index,
          remove: () => {
            node.children.splice(index, 1);
            renderTemplateTree();
          },
        }),
      );
    });
    wrapper.append(children);
  }
  return wrapper;
}

function renderTemplateTree() {
  if (!state.requestTemplateNode) state.requestTemplateNode = defaultTemplateNode("object");
  elements.templateTree.replaceChildren(
    renderTemplateNode(state.requestTemplateNode, { isRoot: true }),
  );
  try {
    syncTemplateJson();
  } catch (_error) {
    // The tree remains editable while duplicate or blank object keys are corrected.
  }
}

function applyRawTemplateJson() {
  try {
    const value = JSON.parse(elements.templateJson.value || "{}");
    state.requestTemplateNode = templateNodeFromValue(value);
    state.templateRawDirty = false;
    renderTemplateTree();
    elements.templateJsonStatus.textContent = "Edited JSON applied to the tree builder.";
    elements.templateJsonStatus.classList.remove("error");
  } catch (error) {
    elements.templateJsonStatus.textContent = `Invalid JSON: ${error.message}`;
    elements.templateJsonStatus.classList.add("error");
    elements.templateJson.focus();
  }
}

function optionalNumber(input) {
  if (input.value === "") return null;
  const value = Number(input.value);
  if (!Number.isFinite(value)) throw new Error(`${input.labels[0].textContent} must be a number.`);
  return value;
}

function setOptionalNumber(input, value) {
  input.value = value === null || value === undefined ? "" : String(value);
}

function formatJsonObject(value) {
  const object = value && typeof value === "object" && !Array.isArray(value) ? value : {};
  return JSON.stringify(object, null, 2);
}

function parseJsonObjectField(textarea, label) {
  let value;
  try {
    value = JSON.parse(textarea.value || "{}");
  } catch (error) {
    textarea.focus();
    throw new Error(`${label} must be valid JSON: ${error.message}`);
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    textarea.focus();
    throw new Error(`${label} must be a JSON object.`);
  }
  return value;
}

function formatJsonArray(value) {
  return JSON.stringify(Array.isArray(value) ? value : [], null, 2);
}

function parseJsonArrayField(textarea, label) {
  let value;
  try {
    value = JSON.parse(textarea.value || "[]");
  } catch (error) {
    textarea.focus();
    throw new Error(`${label} must be valid JSON: ${error.message}`);
  }
  if (!Array.isArray(value)) {
    textarea.focus();
    throw new Error(`${label} must be a JSON array.`);
  }
  return value;
}

function hideResourceKey() {
  if (state.keyVisibilityTimer !== null) {
    window.clearTimeout(state.keyVisibilityTimer);
    state.keyVisibilityTimer = null;
  }
  elements.resourceApiKey.type = "password";
  elements.toggleResourceKey.textContent = "Show";
  elements.toggleResourceKey.setAttribute("aria-label", "Show API key");
  elements.toggleResourceKey.setAttribute("aria-pressed", "false");
}

function toggleResourceKeyVisibility() {
  if (elements.resourceApiKey.type === "text") {
    hideResourceKey();
    return;
  }
  elements.resourceApiKey.type = "text";
  elements.toggleResourceKey.textContent = "Hide";
  elements.toggleResourceKey.setAttribute("aria-label", "Hide API key");
  elements.toggleResourceKey.setAttribute("aria-pressed", "true");
  state.keyVisibilityTimer = window.setTimeout(hideResourceKey, 30_000);
}

function updateResourceAuthFields() {
  const mode = elements.resourceAuthPlacement.value;
  const namedPlacement = mode === "header" || mode === "query";
  const acceptsSecret = mode !== "none";
  elements.resourceAuthName.disabled = !namedPlacement;
  elements.resourceAuthPrefix.disabled = !namedPlacement;
  elements.resourceApiKey.disabled = !acceptsSecret;
  elements.toggleResourceKey.disabled = !acceptsSecret;
  if (!acceptsSecret) {
    elements.resourceApiKey.value = "";
    hideResourceKey();
  }
}

function defaultRequestTemplate() {
  return {
    text: "{{ text }}",
    model: "{{ model }}",
    voice: "{{ voice }}",
  };
}

function resourceConfigValue(resource, key, fallback = null) {
  if (resource && resource[key] !== undefined && resource[key] !== null) return resource[key];
  if (resource && resource.config && resource.config[key] !== undefined) return resource.config[key];
  const nestedPaths = {
    adapter: ["adapter_type"],
    default_model: ["defaults", "default_model"],
    default_voice: ["defaults", "default_voice"],
    models: ["defaults", "models"],
    voices: ["defaults", "voices"],
    auth_placement: ["auth", "mode"],
    auth_name: ["auth", "name"],
    auth_prefix: ["auth", "prefix"],
    response_mode: ["response", "mode"],
    audio_json_pointer: ["response", "json_pointer"],
    response_sample_rate_hz: ["response", "sample_rate_hz"],
    response_channels: ["response", "channels"],
    response_sample_width_bytes: ["response", "sample_width_bytes"],
    max_input_bytes: ["input_limits", "max_bytes"],
    max_input_tokens: ["input_limits", "max_tokens"],
    max_input_words: ["input_limits", "max_words"],
    max_input_characters: ["input_limits", "max_characters"],
    recommended_chunk_bytes: ["input_limits", "recommended_bytes"],
    recommended_chunk_words: ["input_limits", "recommended_words"],
    recommended_chunk_characters: ["input_limits", "recommended_characters"],
    minimum_request_interval_seconds: ["pacing", "minimum_interval_seconds"],
    requests_per_minute: ["pacing", "requests_per_minute"],
    max_concurrency: ["pacing", "max_concurrency"],
    request_timeout_seconds: ["retry", "request_timeout_seconds"],
    retry_max_attempts: ["retry", "max_attempts"],
    limit_basis: ["input_limits", "limit_basis"],
  };
  const path = nestedPaths[key];
  if (path) {
    let value = resource;
    for (const part of path) value = value && value[part];
    if (value !== undefined && value !== null) return value;
  }
  return fallback;
}

function populateResourceForm(resource = null) {
  const editing = Boolean(resource);
  state.editingResource = resource;
  elements.resourceModalTitle.textContent = editing ? "Edit API resource" : "Add API resource";
  elements.resourceId.disabled = editing;
  elements.deleteResource.hidden = !editing;
  elements.resourceName.value = resourceLabel(resource) === "API resource" ? "" : resourceLabel(resource);
  elements.resourceId.value = resourceId(resource) || "";
  const adapter = resourceConfigValue(resource, "adapter", "generic_rest");
  elements.resourceAdapter.value = ["generic_rest", "gemini", "deepgram", "inworld"].includes(adapter)
    ? adapter
    : "generic_rest";
  elements.resourceBaseUrl.value = resourceConfigValue(resource, "base_url", "") || "";
  elements.resourceMethod.value = String(resourceConfigValue(resource, "method", "POST")).toUpperCase();
  elements.resourceDefaultModel.value = resourceConfigValue(resource, "default_model", "") || "";
  elements.resourceDefaultVoice.value = resourceConfigValue(resource, "default_voice", "") || "";
  elements.resourceAuthPlacement.value = resourceConfigValue(resource, "auth_placement", "header");
  elements.resourceAuthName.value = resourceConfigValue(resource, "auth_name", "Authorization") || "";
  elements.resourceAuthPrefix.value = resourceConfigValue(resource, "auth_prefix", "Bearer ") || "";
  updateResourceAuthFields();
  elements.resourceApiKey.value = "";
  hideResourceKey();
  const hasKey = Boolean(resource && resource.has_api_key);
  const keySource = resource && resource.api_key_source
    ? resource.api_key_source
    : hasKey
      ? "vault"
      : null;
  elements.resourceKeyStatus.textContent = keySource === "environment"
    ? "Server environment"
    : keySource === "vault"
      ? "OS vault"
      : "Not stored";
  elements.resourceApiKey.placeholder = keySource === "environment"
    ? "Enter a key to override the server environment"
    : hasKey
      ? "Stored key — leave blank to keep"
      : "Enter API key";
  elements.clearResourceApiKey.checked = false;
  elements.clearResourceApiKey.disabled = keySource !== "vault";
  elements.resourceHeadersJson.value = formatJsonObject(resourceConfigValue(resource, "headers", {}));
  elements.resourceQueryJson.value = formatJsonObject(resourceConfigValue(resource, "query", {}));
  elements.resourceDefaultVariablesJson.value = formatJsonObject(
    resourceConfigValue(resource, "default_variables", defaultVariablesForResource(resource)),
  );
  elements.resourceModelsJson.value = formatJsonArray(resourceConfigValue(resource, "models", []));
  elements.resourceVoicesJson.value = formatJsonArray(resourceConfigValue(resource, "voices", []));

  let requestTemplate = resourceConfigValue(resource, "request_template", defaultRequestTemplate());
  if (typeof requestTemplate === "string") {
    try {
      requestTemplate = JSON.parse(requestTemplate);
    } catch (_error) {
      requestTemplate = defaultRequestTemplate();
    }
  }
  state.requestTemplateNode = templateNodeFromValue(requestTemplate || {});
  renderTemplateTree();

  setOptionalNumber(elements.resourceMaxBytes, resourceConfigValue(resource, "max_input_bytes"));
  setOptionalNumber(elements.resourceMaxCharacters, resourceConfigValue(resource, "max_input_characters"));
  setOptionalNumber(elements.resourceMaxTokens, resourceConfigValue(resource, "max_input_tokens"));
  setOptionalNumber(elements.resourceMaxWords, resourceConfigValue(resource, "max_input_words"));
  setOptionalNumber(elements.resourceChunkBytes, resourceConfigValue(resource, "recommended_chunk_bytes"));
  setOptionalNumber(elements.resourceChunkCharacters, resourceConfigValue(resource, "recommended_chunk_characters"));
  setOptionalNumber(elements.resourceChunkWords, resourceConfigValue(resource, "recommended_chunk_words"));
  setOptionalNumber(
    elements.resourcePacing,
    resourceConfigValue(resource, "minimum_request_interval_seconds", 0),
  );
  elements.resourceLimitBasis.value = resourceConfigValue(resource, "limit_basis", "text");
  setOptionalNumber(
    elements.resourceTimeout,
    resourceConfigValue(resource, "request_timeout_seconds", 300),
  );
  setOptionalNumber(
    elements.resourceRetryAttempts,
    resourceConfigValue(resource, "retry_max_attempts", 3),
  );
  setOptionalNumber(elements.resourceRequestsMinute, resourceConfigValue(resource, "requests_per_minute"));
  setOptionalNumber(
    elements.resourceMaxConcurrency,
    resourceConfigValue(resource, "max_concurrency", 1),
  );
  elements.resourceResponseMode.value = resourceConfigValue(resource, "response_mode", "raw_pcm");
  elements.resourceAudioPointer.value = resourceConfigValue(resource, "audio_json_pointer", "") || "";
  setOptionalNumber(elements.resourceSampleRate, resourceConfigValue(resource, "response_sample_rate_hz", 24_000));
  setOptionalNumber(elements.resourceChannels, resourceConfigValue(resource, "response_channels", 1));
  setOptionalNumber(elements.resourceSampleWidth, resourceConfigValue(resource, "response_sample_width_bytes", 2));
}

function buildResourcePayload() {
  if (state.templateRawDirty) {
    const value = JSON.parse(elements.templateJson.value || "{}");
    state.requestTemplateNode = templateNodeFromValue(value);
    state.templateRawDirty = false;
  }
  const requestTemplate = templateValueFromNode(state.requestTemplateNode);
  const payload = {
    id: elements.resourceId.value.trim(),
    name: elements.resourceName.value.trim(),
    adapter: elements.resourceAdapter.value,
    base_url: elements.resourceBaseUrl.value.trim() || null,
    method: elements.resourceMethod.value,
    default_model: elements.resourceDefaultModel.value.trim() || null,
    default_voice: elements.resourceDefaultVoice.value.trim() || null,
    auth_placement: elements.resourceAuthPlacement.value,
    auth_name: elements.resourceAuthName.value.trim() || null,
    auth_prefix: elements.resourceAuthPrefix.value,
    headers: parseJsonObjectField(elements.resourceHeadersJson, "Request headers"),
    query: parseJsonObjectField(elements.resourceQueryJson, "Query parameters"),
    default_variables: parseJsonObjectField(
      elements.resourceDefaultVariablesJson,
      "Default job variables",
    ),
    models: parseJsonArrayField(elements.resourceModelsJson, "Available models"),
    voices: parseJsonArrayField(elements.resourceVoicesJson, "Available voices"),
    request_template: requestTemplate,
    max_input_bytes: optionalNumber(elements.resourceMaxBytes),
    max_input_characters: optionalNumber(elements.resourceMaxCharacters),
    max_input_tokens: optionalNumber(elements.resourceMaxTokens),
    max_input_words: optionalNumber(elements.resourceMaxWords),
    recommended_chunk_bytes: optionalNumber(elements.resourceChunkBytes),
    recommended_chunk_characters: optionalNumber(elements.resourceChunkCharacters),
    recommended_chunk_words: optionalNumber(elements.resourceChunkWords),
    minimum_request_interval_seconds: optionalNumber(elements.resourcePacing),
    limit_basis: elements.resourceLimitBasis.value,
    request_timeout_seconds: optionalNumber(elements.resourceTimeout),
    retry_max_attempts: optionalNumber(elements.resourceRetryAttempts),
    requests_per_minute: optionalNumber(elements.resourceRequestsMinute),
    max_concurrency: optionalNumber(elements.resourceMaxConcurrency),
    response_mode: elements.resourceResponseMode.value,
    audio_json_pointer: elements.resourceAudioPointer.value.trim() || null,
    response_sample_rate_hz: optionalNumber(elements.resourceSampleRate),
    response_channels: optionalNumber(elements.resourceChannels),
    response_sample_width_bytes: optionalNumber(elements.resourceSampleWidth),
  };
  if (state.editingResource && state.editingResource.revision !== undefined) {
    payload.revision = state.editingResource.revision;
  }
  if (elements.clearResourceApiKey.checked) {
    payload.clear_api_key = true;
  } else if (elements.resourceApiKey.value) {
    payload.api_key = elements.resourceApiKey.value;
  }
  return payload;
}

async function loadApiResources(preferredId = null, selected = {}) {
  let resources;
  try {
    const result = await requestJson("/v1/api-resources", { reportError: false });
    resources = collectionItems(result, "resources", "items");
    state.resourcesEndpointAvailable = true;
  } catch (error) {
    if (error.status !== 404) {
      if (error.diagnostic) void reportClientError(error.diagnostic);
      throw error;
    }
    resources = collectionItems(await requestJson("/v1/providers"), "providers", "items");
    state.resourcesEndpointAvailable = false;
  }
  if (!resources.length) throw new Error("No API resources are configured.");
  state.providers = resources;
  const currentId = preferredId || elements.provider.value || resourceId(resources[0]);
  const chosen = resources.some((resource) => resourceId(resource) === currentId)
    ? currentId
    : resourceId(resources[0]);
  replaceSelectOptions(elements.provider, resources, chosen, resourceLabel);
  elements.provider.disabled = false;
  elements.addResource.disabled = !state.resourcesEndpointAvailable;
  elements.editResource.disabled = !state.resourcesEndpointAvailable;
  configureProvider(chosen, selected);
  return resources;
}

function closeResourceSettings() {
  hideResourceKey();
  elements.resourceApiKey.value = "";
  closeDialog(elements.resourceModal);
}

async function openResourceSettings(resource = null) {
  try {
    let detail = resource;
    if (resource) {
      detail = await requestJson(`/v1/api-resources/${encodeURIComponent(resourceId(resource))}`);
    }
    populateResourceForm(detail);
    showDialog(elements.resourceModal, elements.resourceName);
  } catch (error) {
    setMessage(`Could not open API resource settings: ${error.message}`, true);
  }
}

async function saveResource(event) {
  event.preventDefault();
  const editingId = resourceId(state.editingResource);
  try {
    const payload = buildResourcePayload();
    const path = editingId
      ? `/v1/api-resources/${encodeURIComponent(editingId)}`
      : "/v1/api-resources";
    const saved = await requestJson(path, {
      method: editingId ? "PUT" : "POST",
      body: JSON.stringify(payload),
    });
    const savedId = resourceId(saved) || payload.id;
    closeResourceSettings();
    await loadApiResources(savedId);
    markPreviewStale();
    setMessage(`${payload.name} API resource saved.`);
  } catch (error) {
    setMessage(`Could not save API resource: ${error.message}`, true);
  }
}

async function deleteCurrentResource() {
  const id = resourceId(state.editingResource);
  if (!id) return;
  if (!window.confirm(`Delete the ${resourceLabel(state.editingResource)} API resource? Existing jobs and profiles will keep their saved references.`)) return;
  try {
    await requestJson(`/v1/api-resources/${encodeURIComponent(id)}`, { method: "DELETE" });
    closeResourceSettings();
    await loadApiResources();
    markPreviewStale();
    setMessage("API resource deleted.");
  } catch (error) {
    setMessage(`Could not delete API resource: ${error.message}`, true);
  }
}

function replaceSelectOptions(select, values, selectedValue, labelFor = humanize) {
  const options = values.map((value) => {
    const option = document.createElement("option");
    const optionValue = typeof value === "string" ? value : resourceId(value);
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

function defaultVariablesForResource(resource) {
  if (resource && resource.default_variables && typeof resource.default_variables === "object") {
    return resource.default_variables;
  }
  if (!resource || !Array.isArray(resource.variables)) return {};
  const variables = {};
  resource.variables.forEach((definition) => {
    if (!definition || !definition.name || ["text", "model", "voice", "instructions"].includes(definition.name)) return;
    variables[definition.name] = definition.default ?? "";
  });
  return variables;
}

function configureProvider(providerName, selected = {}, resourceOverride = null) {
  const provider = resourceOverride
    || state.providers.find((item) => resourceId(item) === providerName);
  if (!provider) return;
  state.currentProvider = provider;
  state.selectedResourceRevision = selected.resource_revision !== null &&
    selected.resource_revision !== undefined
    ? selected.resource_revision
    : provider.revision ?? null;
  elements.provider.value = resourceId(provider);
  elements.editResource.disabled = !state.resourcesEndpointAvailable;

  const capabilities = provider.capabilities || {};
  const defaults = provider.defaults || {};
  const defaultModel = provider.default_model || defaults.default_model || "";
  const defaultVoice = provider.default_voice || defaults.default_voice || "";
  const models = (capabilities.models || []).length
    ? capabilities.models
    : (defaults.models || []).length
      ? defaults.models
      : [defaultModel].filter(Boolean);
  const modelOptions = models.map((model) => {
    const option = document.createElement("option");
    option.value = model;
    return option;
  });
  elements.modelOptions.replaceChildren(...modelOptions);
  elements.model.value = selected.model || defaultModel;

  replaceSelectOptions(
    elements.voice,
    (capabilities.voices || defaults.voices || []).length
      ? capabilities.voices
        || defaults.voices
      : [defaultVoice].filter(Boolean),
    selected.voice || defaultVoice,
    (voice) => {
      if (typeof voice === "string") return humanize(voice);
      const traits = Array.isArray(voice.traits) ? voice.traits : [];
      const id = voice.id || voice.name;
      const label = voice.label && voice.label !== id ? `${voice.label} (${id})` : id;
      return `${label}${traits.length ? ` · ${traits.join(", ")}` : ""}`;
    },
  );
  replaceSelectOptions(
    elements.tone,
    (capabilities.tone_presets || []).length ? capabilities.tone_presets : ["neutral"],
    selected.controls && selected.controls.tone,
  );
  replaceSelectOptions(
    elements.vocalStyle,
    (capabilities.vocal_styles || []).length ? capabilities.vocal_styles : ["natural"],
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
  renderJobVariables(
    selected.variables || defaultVariablesForResource(provider),
  );
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
  if (!provider || !state.providers.some((item) => resourceId(item) === provider)) {
    throw new Error("Select a valid API resource before continuing.");
  }
  const model = elements.model.value.trim();
  const voice = elements.voice.value;
  const currentResource = state.providers.find((item) => resourceId(item) === provider);
  const payload = {
    text: elements.transcript.value,
    provider,
    model: model || null,
    voice: voice || null,
    instructions: instructions || null,
    controls: buildControls(),
    split_strategy: elements.splitStrategy.value,
    remove_numeric_citations: elements.removeNumericCitations.checked,
    variables: collectJobVariables(),
  };
  if (state.resourcesEndpointAvailable) {
    payload.resource_id = provider;
    payload.resource_revision = state.selectedResourceRevision !== undefined
      ? state.selectedResourceRevision
      : currentResource && currentResource.revision !== undefined
        ? currentResource.revision
        : null;
  }
  return payload;
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

function buildProfilePayload(name, includeJob = elements.profileIncludeJob.checked) {
  const job = buildJobPayload();
  return {
    name: name.trim(),
    resource_id: job.provider,
    resource_revision: job.resource_revision ?? state.selectedResourceRevision,
    text: job.text,
    model: job.model,
    voice: job.voice,
    instructions: job.instructions,
    controls: job.controls,
    split_strategy: job.split_strategy,
    remove_numeric_citations: job.remove_numeric_citations,
    variables: job.variables,
    job_id: includeJob && state.activeJobId ? state.activeJobId : null,
  };
}

function profileId(profile) {
  return profile && (profile.id || profile.name);
}

function renderProfiles(profiles) {
  if (!profiles.length) {
    const empty = document.createElement("li");
    empty.className = "job-list-empty";
    empty.textContent = "No profiles yet.";
    elements.profilesList.replaceChildren(empty);
    return;
  }
  const rows = profiles.map((profile) => {
    const row = document.createElement("li");
    row.className = "profile-row";
    const copy = document.createElement("div");
    copy.className = "profile-copy";
    const name = document.createElement("strong");
    name.textContent = profile.name || profileId(profile);
    const meta = document.createElement("small");
    const resource = profile.resource_id ? `Resource: ${profile.resource_id}` : "No resource reference";
    const checkpoint = profile.job_id ? " · Includes job progress" : "";
    meta.textContent = `${resource}${checkpoint}`;
    copy.append(name, meta);

    const actions = document.createElement("div");
    actions.className = "profile-actions";
    const load = document.createElement("button");
    load.type = "button";
    load.textContent = "Load";
    load.addEventListener("click", () => void loadProfile(profileId(profile)));
    const update = document.createElement("button");
    update.type = "button";
    update.textContent = "Update";
    update.setAttribute("aria-label", `Update ${profile.name || profileId(profile)} from the current studio`);
    update.addEventListener("click", () => void updateProfile(profile));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "profile-delete";
    remove.textContent = "Delete";
    remove.setAttribute("aria-label", `Delete ${profile.name || profileId(profile)}`);
    remove.addEventListener("click", () => void deleteProfile(profile));
    actions.append(load, update, remove);
    row.append(copy, actions);
    return row;
  });
  elements.profilesList.replaceChildren(...rows);
}

async function loadProfiles() {
  try {
    const result = await requestJson("/v1/profiles");
    const profiles = collectionItems(result, "profiles", "items");
    renderProfiles(profiles);
    return profiles;
  } catch (error) {
    renderProfiles([]);
    setMessage(`Could not load profiles: ${error.message}`, true);
    return [];
  }
}

async function openProfiles() {
  elements.profileIncludeJob.checked = Boolean(state.activeJobId);
  showDialog(elements.profilesModal, elements.profileName);
  await loadProfiles();
}

async function saveProfile(event) {
  event.preventDefault();
  try {
    const payload = buildProfilePayload(elements.profileName.value);
    await requestJson("/v1/profiles", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    elements.profileName.value = "";
    await loadProfiles();
    setMessage(`${payload.name} profile saved.`);
  } catch (error) {
    setMessage(`Could not save profile: ${error.message}`, true);
  }
}

async function updateProfile(profile) {
  try {
    const payload = buildProfilePayload(
      profile.name || profileId(profile),
      elements.profileIncludeJob.checked,
    );
    if (profile.revision !== undefined) payload.revision = profile.revision;
    await requestJson(`/v1/profiles/${encodeURIComponent(profileId(profile))}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    await loadProfiles();
    setMessage(`${payload.name} profile updated from the current studio.`);
  } catch (error) {
    setMessage(`Could not update profile: ${error.message}`, true);
  }
}

async function deleteProfile(profile) {
  const id = profileId(profile);
  if (!window.confirm(`Delete the ${profile.name || id} profile?`)) return;
  try {
    await requestJson(`/v1/profiles/${encodeURIComponent(id)}`, { method: "DELETE" });
    await loadProfiles();
    setMessage("Profile deleted.");
  } catch (error) {
    setMessage(`Could not delete profile: ${error.message}`, true);
  }
}

async function loadProfile(id) {
  try {
    const profile = await requestJson(`/v1/profiles/${encodeURIComponent(id)}`);
    if (!state.providers.some((resource) => resourceId(resource) === profile.resource_id)) {
      await loadApiResources(profile.resource_id, profile);
    }
    let currentResource = state.providers.find(
      (resource) => resourceId(resource) === profile.resource_id,
    );
    let savedResource = currentResource;
    if (profile.resource_revision !== null && profile.resource_revision !== undefined
      && (!currentResource || currentResource.revision !== profile.resource_revision)) {
      savedResource = await requestJson(
        `/v1/api-resources/${encodeURIComponent(profile.resource_id)}?revision=${encodeURIComponent(profile.resource_revision)}`,
      );
      if (!currentResource) {
        state.providers.push(savedResource);
        replaceSelectOptions(
          elements.provider,
          state.providers,
          profile.resource_id,
          resourceLabel,
        );
      }
    }
    if (!savedResource) {
      throw new Error(`The saved API resource ${profile.resource_id} is no longer available.`);
    }
    state.pollGeneration += 1;
    configureProvider(profile.resource_id, profile, savedResource);
    elements.transcript.value = profile.text || "";
    elements.splitStrategy.value = profile.split_strategy || "semantic";
    elements.removeNumericCitations.checked = Boolean(profile.remove_numeric_citations);
    renderJobVariables(profile.variables || {});
    updateTranscriptStats();
    markPreviewStale();
    closeDialog(elements.profilesModal);

    if (profile.job_id) {
      try {
        const job = await requestJson(`/v1/speech/jobs/${encodeURIComponent(profile.job_id)}`);
        renderJob(job);
        if (["queued", "running"].includes(job.status)) startMonitoring(job.id);
        const jobPanel = document.querySelector(".job-panel");
        if (jobPanel) {
          jobPanel.scrollIntoView({ block: "start", behavior: "smooth" });
          elements.jobStatus.focus({ preventScroll: true });
        }
      } catch (error) {
        setMessage(`Profile loaded, but its saved job could not be reopened: ${error.message}`, true);
        elements.transcript.focus();
        return;
      }
    } else {
      elements.transcript.focus();
    }
    currentResource = state.providers.find(
      (resource) => resourceId(resource) === profile.resource_id,
    );
    const differs = currentResource && profile.resource_revision !== null &&
      profile.resource_revision !== undefined && currentResource.revision !== profile.resource_revision;
    setMessage(differs
      ? "Profile loaded with its saved API-resource revision. Reselect the resource to use its newer revision."
      : "Profile loaded.");
  } catch (error) {
    setMessage(`Could not load profile: ${error.message}`, true);
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

function jobErrorPayload(job) {
  return job && job.error_detail && typeof job.error_detail === "object"
    ? job.error_detail
    : null;
}

function jobErrorMessage(job) {
  const payload = jobErrorPayload(job);
  return String(payload ? payload.message || job.error || "" : job.error_detail || job.error || "");
}

function jobErrorCode(job) {
  const payload = jobErrorPayload(job);
  return String(payload?.code || job.error_code || "UNKNOWN");
}

function jobErrorEventId(job) {
  const payload = jobErrorPayload(job);
  return payload?.event_id || job.error_event_id || job.error_id || null;
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
  state.currentJobErrorEventId = jobErrorEventId(job);
  elements.viewJobDiagnostics.hidden = !state.currentJobErrorEventId;
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

  const detail = jobErrorMessage(job);
  const code = jobErrorCode(job);
  state.currentJobErrorEventId = jobErrorEventId(job);
  elements.viewJobDiagnostics.hidden = !state.currentJobErrorEventId;
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
      title.textContent = `${job.resource_id || job.provider} · ${job.voice}`;

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
        configureProvider(job.resource_id || job.provider, job);
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
        configureProvider(recoverable.resource_id || recoverable.provider, recoverable);
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
      const job = await requestJson(`/v1/speech/jobs/${encodeURIComponent(jobId)}`, {
        reportError: false,
      });
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
        if (error.diagnostic) {
          void reportClientError({
            ...error.diagnostic,
            context: {
              ...(error.diagnostic.context || {}),
              action: "Monitor synthesis job",
              job_id: jobId,
              transient_failures: transientFailures,
            },
          });
        }
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
  updateErrorCounts();
  try {
    await syncErrorEvents({ notify: false });
  } catch (_error) {
    // The studio remains usable if error history is temporarily unavailable.
  }
  scheduleErrorPoll();
  try {
    await loadApiResources();
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
elements.addResource.addEventListener("click", () => void openResourceSettings());
elements.editResource.addEventListener("click", () => {
  const resource = state.providers.find((item) => resourceId(item) === elements.provider.value);
  if (resource) void openResourceSettings(resource);
});
elements.closeResourceModal.addEventListener("click", closeResourceSettings);
elements.cancelResource.addEventListener("click", closeResourceSettings);
elements.resourceModal.addEventListener("close", () => {
  hideResourceKey();
  elements.resourceApiKey.value = "";
});
elements.resourceModal.addEventListener("cancel", hideResourceKey);
elements.resourceForm.addEventListener("submit", saveResource);
elements.deleteResource.addEventListener("click", () => void deleteCurrentResource());
elements.toggleResourceKey.addEventListener("click", toggleResourceKeyVisibility);
elements.resourceAuthPlacement.addEventListener("change", updateResourceAuthFields);
elements.resourceApiKey.addEventListener("input", () => {
  if (elements.resourceApiKey.value) elements.clearResourceApiKey.checked = false;
});
elements.clearResourceApiKey.addEventListener("change", () => {
  if (!elements.clearResourceApiKey.checked) return;
  elements.resourceApiKey.value = "";
  hideResourceKey();
});
elements.addTemplateRootField.addEventListener("click", () => {
  if (!state.requestTemplateNode || state.requestTemplateNode.type !== "object") {
    state.requestTemplateNode = defaultTemplateNode("object");
  }
  state.requestTemplateNode.children.push({
    key: nextObjectKey(state.requestTemplateNode),
    node: defaultTemplateNode("string"),
  });
  renderTemplateTree();
});
elements.refreshTemplateJson.addEventListener("click", () => {
  try {
    syncTemplateJson();
  } catch (_error) {
    // Validation detail is displayed beside the raw JSON editor.
  }
});
elements.applyTemplateJson.addEventListener("click", applyRawTemplateJson);
elements.templateJson.addEventListener("input", () => {
  state.templateRawDirty = true;
  elements.templateJsonStatus.textContent = "Raw JSON changed. Apply it to update the tree builder.";
  elements.templateJsonStatus.classList.remove("error");
});
elements.addJobVariable.addEventListener("click", () => {
  elements.jobVariablesList.append(createVariableRow());
  elements.variablesPanel.open = true;
  const rows = elements.jobVariablesList.querySelectorAll(".key-value-row");
  const lastInput = rows.length ? rows[rows.length - 1].querySelector("input") : null;
  if (lastInput) lastInput.focus();
  markPreviewStale();
});
elements.jobVariablesList.addEventListener("input", markPreviewStale);
elements.jobVariablesList.addEventListener("click", (event) => {
  if (event.target.closest(".remove-row-button")) markPreviewStale();
});
elements.openProfiles.addEventListener("click", () => void openProfiles());
elements.closeProfilesModal.addEventListener("click", () => closeDialog(elements.profilesModal));
elements.profileSaveForm.addEventListener("submit", saveProfile);
elements.refreshProfiles.addEventListener("click", () => void loadProfiles());
elements.errorLogButton.addEventListener("click", () => void openErrorLog());
elements.closeErrorLog.addEventListener("click", closeErrorLogDialog);
elements.showUnreadErrors.addEventListener("click", () => {
  state.errorFilter = "unread";
  renderErrorLog();
});
elements.showAllErrors.addEventListener("click", () => {
  state.errorFilter = "all";
  renderErrorLog();
});
elements.markAllErrorsRead.addEventListener("click", () => void markAllErrorEventsRead());
elements.clearReadErrors.addEventListener("click", () => void clearErrorEvents("read"));
elements.clearAllErrors.addEventListener("click", () => void clearErrorEvents("all"));
elements.closeErrorDetails.addEventListener("click", closeErrorDetailsDialog);
elements.doneErrorDetails.addEventListener("click", closeErrorDetailsDialog);
elements.markErrorRead.addEventListener("click", () => void markErrorEventRead(state.selectedErrorId));
elements.copyErrorMessage.addEventListener("click", () =>
  void copyDiagnosticText(elements.errorDetailsMessage.textContent, "Error message copied."),
);
elements.copyAllErrorDetails.addEventListener("click", () =>
  void copyDiagnosticText(elements.errorDetailsRaw.textContent, "Complete diagnostic report copied."),
);
document.querySelectorAll("[data-error-copy]").forEach((button) => {
  button.addEventListener("click", () => {
    const section = button.dataset.errorCopy;
    const values = {
      request: elements.errorDetailsRequest.textContent,
      response: elements.errorDetailsResponse.textContent,
      exception: elements.errorDetailsException.textContent,
      context: elements.errorDetailsContext.textContent,
      raw: elements.errorDetailsRaw.textContent,
    };
    void copyDiagnosticText(values[section] || "", `${humanize(section)} details copied.`);
  });
});
[elements.errorLogModal, elements.errorDetailsModal].forEach((dialog) => {
  dialog.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      if (dialog === elements.errorDetailsModal) closeErrorDetailsDialog();
      else closeErrorLogDialog();
      return;
    }
    trapDialogFocus(dialog, event);
  });
  dialog.addEventListener("click", (event) => {
    if (event.target !== dialog) return;
    if (dialog === elements.errorDetailsModal) closeErrorDetailsDialog();
    else closeErrorLogDialog();
  });
});
elements.errorLogModal.addEventListener("cancel", (event) => {
  event.preventDefault();
  closeErrorLogDialog();
});
elements.errorDetailsModal.addEventListener("cancel", (event) => {
  event.preventDefault();
  closeErrorDetailsDialog();
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden) hideResourceKey();
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
elements.viewJobDiagnostics.addEventListener("click", () => {
  if (state.currentJobErrorEventId) {
    void openErrorDetails(
      state.currentJobErrorEventId,
      elements.viewJobDiagnostics,
      elements.errorModal,
    );
  }
});
elements.playbackRate.addEventListener("change", () => {
  elements.jobAudio.playbackRate = Number(elements.playbackRate.value);
});
elements.refreshAudio.addEventListener("click", refreshCurrentAudio);
elements.jobAudio.addEventListener("timeupdate", updatePlayerTime);
elements.jobAudio.addEventListener("loadedmetadata", updatePlayerTime);
elements.jobAudio.addEventListener("durationchange", updatePlayerTime);
elements.jobAudio.addEventListener("error", () => {
  if (elements.jobAudio.dataset.source) {
    const message = "Audio could not be loaded. Refresh it after another chunk completes.";
    setMessage(message, true);
    void reportClientError({
      code: "client_audio_load_error",
      category: "media",
      message,
      retryable: true,
      status_code: null,
      method: "GET",
      endpoint: elements.jobAudio.dataset.source,
      request: null,
      response: null,
      exception: elements.jobAudio.error
        ? {
            code: elements.jobAudio.error.code,
            message: elements.jobAudio.error.message || null,
          }
        : null,
      context: { job_id: state.activeJobId },
    });
  }
});

void boot();
