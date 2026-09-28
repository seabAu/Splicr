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
    throw new ApiError(`Could not reach the local SPLICR service: ${cause.message}`);
  }
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("json") ? await response.json() : await response.text();
  if (!response.ok) {
    if (response.status === 401) {
      const next = `${window.location.pathname}${window.location.search}`;
      window.location.assign(`/auth?next=${encodeURIComponent(next)}`);
    }
    throw new ApiError(errorMessage(body, `Request failed (${response.status})`), {
      status: response.status,
      code: body?.detail?.code || body?.error_code || null,
      detail: body,
    });
  }
  return body;
}

export const api = {
  providers: () => request("/v1/providers"),
  jobs: () => request("/v1/speech/jobs"),
  job: (id) => request(`/v1/speech/jobs/${encodeURIComponent(id)}`),
  preview: (payload) =>
    request("/v1/speech/preview", { method: "POST", body: JSON.stringify(payload) }),
  createJob: (payload) =>
    request("/v1/speech/jobs", { method: "POST", body: JSON.stringify(payload) }),
  jobAction: (id, action) =>
    request(`/v1/speech/jobs/${encodeURIComponent(id)}/${action}`, { method: "POST" }),
  importDocument: (file) => {
    const body = new FormData();
    body.append("file", file);
    return request("/v1/documents/import", { method: "POST", body });
  },
};
