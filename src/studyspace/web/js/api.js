// Thin wrapper around the Studyspace API. Every response is {ok, data, error}.

function workspaceId() {
  // On this computer everything lives in the "local" workspace. On a hosted demo every visitor gets their own.
  const local = ["localhost", "127.0.0.1", "[::1]", ""].includes(location.hostname);
  if (local) return "local";
  try {
    let id = localStorage.getItem("studyspace.workspace");
    if (!id) {
      id = "demo-" + Math.random().toString(36).slice(2, 10);
      localStorage.setItem("studyspace.workspace", id);
    }
    return id;
  } catch {
    if (!window.__studyspaceWs) window.__studyspaceWs = "demo-" + Math.random().toString(36).slice(2, 10);
    return window.__studyspaceWs;
  }
}

export class ApiError extends Error {
  constructor(code, message, details, status) {
    super(message);
    this.code = code;
    this.details = details;
    this.status = status;
  }
}

async function request(method, path, body, isForm = false) {
  const headers = { "X-Workspace": workspaceId() };
  let payload;
  if (body !== undefined && !isForm) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  } else if (isForm) {
    payload = body;
  }
  let res;
  try {
    res = await fetch(path, { method, headers, body: payload });
  } catch {
    throw new ApiError("NETWORK", "Cannot reach the Studyspace server. Is it still running?");
  }
  let json = null;
  try { json = await res.json(); } catch { /* not JSON */ }
  if (!json) throw new ApiError("BAD_RESPONSE", `Unexpected response (${res.status})`, null, res.status);
  if (!json.ok) {
    const err = json.error || {};
    throw new ApiError(err.code || "ERROR", err.message || "Something went wrong", err.details, res.status);
  }
  return json.data;
}

export const api = {
  get: (path) => request("GET", path),
  post: (path, body = {}) => request("POST", path, body),
  put: (path, body = {}) => request("PUT", path, body),
  patch: (path, body = {}) => request("PATCH", path, body),
  del: (path) => request("DELETE", path),
  upload: (path, formData) => request("POST", path, formData, true),
  workspace: workspaceId,
  async blobUrl(path) {
    const res = await fetch(path, { headers: { "X-Workspace": workspaceId() } });
    if (!res.ok) throw new ApiError("FILE", "The original file is not available.");
    return URL.createObjectURL(await res.blob());
  },
  async download(path, filename) {
    const res = await fetch(path, { headers: { "X-Workspace": workspaceId() } });
    if (!res.ok) {
      let msg = "Download failed";
      try { msg = (await res.json()).error.message; } catch { /* ignore */ }
      throw new ApiError("DOWNLOAD", msg);
    }
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  },
};
