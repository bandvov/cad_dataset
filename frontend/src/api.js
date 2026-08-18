const LLM_SERVICE_URL =
  import.meta.env.VITE_LLM_SERVICE_URL || "http://localhost:8001";

async function extractErrorDetail(res) {
  let detail = res.statusText;
  try {
    const body = await res.json();
    const raw = body.detail ?? body.error ?? detail;
    // FastAPI's HTTPException(detail={...}) shape (error_type/error dict)
    // vs. a plain string detail -- normalize to a readable string either
    // way, since template-stringing an object gives "[object Object]".
    detail = typeof raw === "string" ? raw : raw?.error ?? JSON.stringify(raw);
  } catch {
    // response wasn't JSON, keep statusText
  }
  return detail;
}

async function handleResponse(res) {
  if (!res.ok) {
    throw new Error(`llm-service ${res.status}: ${await extractErrorDetail(res)}`);
  }
  return res.json();
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

/**
 * Calls llm-service's stateless POST /v1/generate (no persistence --
 * caller passes base_ir explicitly). Prefer generateInProject() below for
 * the normal product flow; this is for one-off / no-session use.
 *
 * Response shape (see llm-service/app/main.py):
 *   { success, json_ir, attempts, stats, error, conversation,
 *     file_b64?, content_type? }
 */
export async function generatePart({ prompt, baseIr, maxAttempts = 3 }) {
  const res = await fetch(`${LLM_SERVICE_URL}/v1/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      prompt,
      base_ir: baseIr ?? null,
      max_attempts: maxAttempts,
      export_format: "glb",
    }),
  });
  return handleResponse(res);
}

// ---- project/session store (Phase 2 item 1) ----
// See llm-service/app/store.py and the /v1/projects* endpoints in main.py.
// A "project" is a persisted, versioned part -- generate/undo/redo here
// are the normal product flow, where a user iterates on one part across
// multiple turns and edits compose automatically (base_ir is taken from
// the project's current version server-side, the frontend doesn't pass it).

export async function createProject(name = "Untitled part") {
  const res = await fetch(`${LLM_SERVICE_URL}/v1/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  return handleResponse(res);
}

export async function listProjects() {
  const res = await fetch(`${LLM_SERVICE_URL}/v1/projects`);
  return handleResponse(res);
}

export async function deleteProject(projectId) {
  const res = await fetch(`${LLM_SERVICE_URL}/v1/projects/${projectId}`, {
    method: "DELETE",
  });
  return handleResponse(res);
}

export async function getProject(projectId) {
  const res = await fetch(`${LLM_SERVICE_URL}/v1/projects/${projectId}`);
  return handleResponse(res);
}

/**
 * Fetches the binary export of a project's current version -- used only
 * to restore the viewport after a page reload, when we already have the
 * json_ir/stats from getProject() and just need render bytes. Returns a
 * base64 string so Viewer3D's prop contract stays uniform regardless of
 * which API call produced the model.
 */
export async function renderProject(projectId, format = "glb") {
  const res = await fetch(
    `${LLM_SERVICE_URL}/v1/projects/${projectId}/render?format=${format}`
  );
  if (!res.ok) {
    throw new Error(`llm-service ${res.status}: ${await extractErrorDetail(res)}`);
  }
  const buffer = await res.arrayBuffer();
  return arrayBufferToBase64(buffer);
}

/**
 * Fetches an export as a downloadable file (STEP/STL/GLB). Separate from
 * renderProject() above -- that one returns base64 for feeding straight
 * into the three.js viewer; this one returns a real Blob for triggering
 * an actual browser download (see App.jsx's handleDownload).
 */
export async function downloadExport(projectId, format) {
  const res = await fetch(
    `${LLM_SERVICE_URL}/v1/projects/${projectId}/render?format=${format}`
  );
  if (!res.ok) {
    throw new Error(`llm-service ${res.status}: ${await extractErrorDetail(res)}`);
  }
  return res.blob();
}

/**
 * Fire-and-forget: tells llm-service a download actually happened, for
 * the request log's outcome classification (Phase 3 item 2) -- this is
 * kept as a separate call from downloadExport() above rather than folded
 * into the render GET, since that GET is also used to restore the
 * viewport on page load and shouldn't be conflated with an explicit
 * "the user wanted this file" signal. Failures here are swallowed --
 * telemetry should never break the actual download.
 */
export async function logDownload(projectId) {
  try {
    await fetch(`${LLM_SERVICE_URL}/v1/projects/${projectId}/log-download`, {
      method: "POST",
    });
  } catch {
    // non-fatal, see docstring above
  }
}

export async function generateInProject({ projectId, prompt, maxAttempts = 3 }) {
  const res = await fetch(`${LLM_SERVICE_URL}/v1/projects/${projectId}/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt, max_attempts: maxAttempts, export_format: "glb" }),
  });
  return handleResponse(res);
}

export async function undoProject(projectId) {
  const res = await fetch(`${LLM_SERVICE_URL}/v1/projects/${projectId}/undo?export_format=glb`, {
    method: "POST",
  });
  return handleResponse(res);
}

export async function redoProject(projectId) {
  const res = await fetch(`${LLM_SERVICE_URL}/v1/projects/${projectId}/redo?export_format=glb`, {
    method: "POST",
  });
  return handleResponse(res);
}

/**
 * Structured-editing fallback (Phase 2 item 4): apply a directly-edited
 * feature tree, bypassing the model entirely. Validates server-side
 * (llm-service calls the geometry service, not the LLM) and versions the
 * result on success -- same as any other edit. Throws with the real
 * error_type/error on validation failure (422), same shape as a
 * generate() failure, so callers can surface it the same way.
 */
export async function applyEdit({ projectId, jsonIr }) {
  const res = await fetch(`${LLM_SERVICE_URL}/v1/projects/${projectId}/apply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ json_ir: jsonIr, export_format: "glb" }),
  });
  return handleResponse(res);
}
