// Tiny fetch helper. JSON in, JSON out. Throws ApiError with .code/.message
// on non-2xx so the UI can surface server error envelopes verbatim.

export class ApiError extends Error {
  constructor(code, message, status) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

function buildUrl(base, params) {
  const url = new URL(base, window.location.origin);
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
  });
  return url.toString();
}

export async function getJson(path, params, signal) {
  const res = await fetch(buildUrl(path, params), {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
    signal,
  });
  let body = null;
  try {
    body = await res.json();
  } catch (_e) {
    // Non-JSON body on error. Fall through with res.statusText.
  }
  if (!res.ok) {
    const env = body && body.error;
    throw new ApiError(
      (env && env.code) || "http_error",
      (env && env.message) || res.statusText || `HTTP ${res.status}`,
      res.status,
    );
  }
  return body;
}

// Read Django's CSRF cookie. Wagtail's admin sets it on first hit; POST
// requests must mirror it back via X-CSRFToken header.
function getCsrfToken() {
  const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

export async function postJson(path, body, signal) {
  const res = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-CSRFToken": getCsrfToken(),
    },
    body: JSON.stringify(body),
    signal,
  });
  let payload = null;
  try {
    payload = await res.json();
  } catch (_e) {
    // ignore; rely on status
  }
  if (!res.ok) {
    const env = payload && payload.error;
    throw new ApiError(
      (env && env.code) || "http_error",
      (env && env.message) || res.statusText || `HTTP ${res.status}`,
      res.status,
    );
  }
  return payload;
}
