// Thin fetch() wrappers for the graph explorer backend (api/app.py). Every
// function returns already-parsed JSON, and throws with the response body
// text on a non-2xx status so callers can show something useful.

async function request(path, options) {
  const res = await fetch(path, options);
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
