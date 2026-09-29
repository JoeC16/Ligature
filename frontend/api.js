// Thin fetch() wrappers for the graph explorer backend (api/app.py). Every
// data route lives under /api/ (see app.py's require_auth) and needs a
// valid login session cookie; every function returns already-parsed JSON,
// and throws with the response body text on a non-2xx status so callers
// can show something useful.

const LOGIN_PATH = "/login.html";

async function request(path, options) {
  const res = await fetch(`/api${path}`, options);
  if (res.status === 401) {
    // Session missing or expired. Bounce to the login page rather than
    // surfacing a raw 401 in whatever UI called this -- except when the
    // call that 401'd *was* the login attempt itself (wrong password),
    // which the login page needs to show inline, not redirect away from.
    if (!location.pathname.endsWith(LOGIN_PATH)) {
      const next = encodeURIComponent(location.pathname + location.search);
      location.href = `${LOGIN_PATH}?next=${next}`;
    }
    const body = await res.text().catch(() => "");
    throw new Error(`401 ${body}`);
  }
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}: ${body}`);
  }
  return res.json();
}

export function getOverview() {
  return request("/graph/overview");
}

export function expandNode(id) {
  return request(`/graph/expand/${encodeURIComponent(id)}`);
}

export function searchNodes(q) {
  return request(`/graph/search?q=${encodeURIComponent(q)}`);
}

export function getNodesByIds(ids) {
  if (ids.length === 0) return Promise.resolve([]);
  return request(`/graph/nodes?ids=${encodeURIComponent(ids.join(","))}`);
}

export function askQuestion(question) {
  return request("/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
}

export function getUnreviewedFlags() {
  return request("/flags/unreviewed");
}

export function resolveFlag(flagId, resolutionState, notes) {
  return request(`/flags/${encodeURIComponent(flagId)}/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ resolution_state: resolutionState, notes: notes || null }),
  });
}

// --- Treatment / rehab / outcome input (build order step 4 -- the closed
// loop: without this, questions like "which protocols preceded a clean
// return" can only ever run against seed data, never a real pilot's own
// treatment history) ---

export function getOpenInjuries() {
  return request("/injuries/open");
}

export function getPhysios() {
  return request("/physios");
}

export function getOpenTreatments() {
  return request("/treatments/open");
}

export function getOpenRehabSessions() {
  return request("/rehab-sessions/open");
}

function postJson(path, body) {
  return request(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export function createTreatment(body) {
  return postJson("/treatments", body);
}

export function createRehabSession(body) {
  return postJson("/rehab-sessions", body);
}

export function createOutcome(body) {
  return postJson("/outcomes", body);
}

// files: { roster: File, gps: File|null, wellness: File|null, injuries: File|null }.
// No Content-Type header here on purpose -- the browser sets
// multipart/form-data with the right boundary itself; setting it manually
// breaks the upload.
export function uploadIngest(files) {
  const formData = new FormData();
  formData.append("roster", files.roster);
  if (files.gps) formData.append("gps", files.gps);
  if (files.wellness) formData.append("wellness", files.wellness);
  if (files.injuries) formData.append("injuries", files.injuries);
  return request("/ingest", { method: "POST", body: formData });
}

// --- Auth ---

export function login(email, password) {
  return request("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
}

export function logout() {
  return request("/auth/logout", { method: "POST" });
}

export function getMe() {
  return request("/auth/me");
}
