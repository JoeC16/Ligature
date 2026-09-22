import { getOverview, expandNode, searchNodes, getNodesByIds, askQuestion } from "./api.js";
import { createGraph } from "./graph.js";

const svg = document.getElementById("graph-svg");
const detailPanel = document.getElementById("detail-panel");
const detailBody = document.getElementById("detail-body");
const detailBackdrop = document.getElementById("detail-backdrop");
const detailClose = document.getElementById("detail-close");
const searchInput = document.getElementById("search-input");
const searchResults = document.getElementById("search-results");
const askForm = document.getElementById("ask-form");
const askInput = document.getElementById("ask-input");
const askSubmit = document.getElementById("ask-submit");
const themeToggle = document.getElementById("theme-toggle");
const graphLoading = document.getElementById("graph-loading");
const graphLoadingText = document.getElementById("graph-loading-text");

const graph = createGraph(svg, {
  onNodeClick: handleNodeClick,
  onEdgeClick: handleEdgeClick,
  onBackgroundClick: clearDetailPanel,
});

let lastAskAnswer = null;

// --- Detail panel (sidebar on desktop, a bottom sheet on mobile — see the
// max-width: 760px block in style.css; .open only has an effect there) ---

function openDetailPanel() {
  detailPanel.classList.add("open");
  detailBackdrop.classList.add("open");
}

function closeDetailPanel() {
  detailPanel.classList.remove("open");
  detailBackdrop.classList.remove("open");
}

detailClose.addEventListener("click", closeDetailPanel);
detailBackdrop.addEventListener("click", closeDetailPanel);
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") closeDetailPanel();
});

async function handleNodeClick(node) {
  renderNodeDetail(node);
  openDetailPanel();
  if (!node._expanded) {
    node._expanded = true;
    try {
      const subgraph = await expandNode(node.id);
      graph.merge(subgraph);
    } catch (err) {
      console.error("expand failed", err);
    }
  }
}

function handleEdgeClick(edge) {
  renderEdgeDetail(edge);
  openDetailPanel();
}

function clearDetailPanel() {
  if (lastAskAnswer) {
    renderAskAnswer(lastAskAnswer);
  } else {
    detailBody.innerHTML = '<p class="empty">Click a node or edge to inspect it.</p>';
  }
  closeDetailPanel();
}

function propTable(properties) {
  const rows = Object.entries(properties || {})
    .map(([k, v]) => {
      const value = Array.isArray(v) ? v.join(", ") : v;
      return `<tr><td class="key">${escapeHtml(k)}</td><td>${escapeHtml(String(value))}</td></tr>`;
    })
    .join("");
  return `<table class="prop-table">${rows}</table>`;
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function renderNodeDetail(node) {
  detailBody.innerHTML = `
    <span class="detail-label" style="background:var(--mist);color:var(--ink-secondary)">${escapeHtml(node.label)}</span>
    <h2>${escapeHtml(node.properties?.name || node.properties?.type || node.id)}</h2>
    <div class="id">${escapeHtml(node.id)}</div>
    ${propTable(node.properties)}
  `;
}

function renderEdgeDetail(edge) {
  detailBody.innerHTML = `
    <span class="detail-label" style="background:var(--mist);color:var(--ink-secondary)">${escapeHtml(edge.type)}</span>
    <h2>${escapeHtml(edge.from)} &rarr; ${escapeHtml(edge.to)}</h2>
    <div class="id">${escapeHtml(edge.id)}</div>
    ${propTable(edge.properties)}
  `;
}

// --- Search ---

let searchDebounce = null;
searchInput.addEventListener("input", () => {
  clearTimeout(searchDebounce);
  const q = searchInput.value.trim();
  if (q.length < 2) {
    searchResults.innerHTML = "";
    return;
  }
  searchDebounce = setTimeout(async () => {
    try {
      const results = await searchNodes(q);
      renderSearchResults(results);
    } catch (err) {
      console.error("search failed", err);
    }
  }, 200);
});

searchInput.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") {
    searchResults.innerHTML = "";
    searchInput.blur();
  }
});

function renderSearchResults(results) {
  searchResults.innerHTML = results
    .map(
      (n) =>
        `<button type="button" data-id="${escapeHtml(n.id)}">${escapeHtml(n.properties?.name || n.properties?.type || n.id)}<span class="result-label">${escapeHtml(n.label)}</span></button>`
    )
    .join("");
  for (const btn of searchResults.querySelectorAll("button")) {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.id;
      searchResults.innerHTML = "";
      searchInput.value = "";
      await focusOnNode(id);
    });
  }
}

async function focusOnNode(id) {
  if (!graph.hasNode(id)) {
    const [node] = await getNodesByIds([id]);
    if (node) graph.merge({ nodes: [node], edges: [] });
  }
  const subgraph = await expandNode(id).catch(() => null);
  if (subgraph) graph.merge(subgraph);
  graph.highlight([id]);
}

document.addEventListener("click", (ev) => {
  if (!ev.target.closest(".search-box")) {
    searchResults.innerHTML = "";
  }
});

// --- Ask in English ---

askForm.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const question = askInput.value.trim();
  if (!question) return;

  askSubmit.disabled = true;
  const originalLabel = askSubmit.textContent;
  askSubmit.textContent = "Asking…";
  try {
    const answer = await askQuestion(question);
    lastAskAnswer = answer;
    renderAskAnswer(answer);
    openDetailPanel();
    if (answer.matched_ids && answer.matched_ids.length > 0) {
      const missing = answer.matched_ids.filter((id) => !graph.hasNode(id));
      if (missing.length > 0) {
        const nodes = await getNodesByIds(missing);
        graph.merge({ nodes, edges: [] });
      }
      graph.highlight(answer.matched_ids);
    }
  } catch (err) {
    console.error("ask failed", err);
    lastAskAnswer = { status: "error", question, error: String(err) };
    renderAskAnswer(lastAskAnswer);
    openDetailPanel();
  } finally {
    askSubmit.disabled = false;
    askSubmit.textContent = originalLabel;
  }
});

function renderAskAnswer(answer) {
  let body;
  if (answer.status === "ok") {
    body = `<div class="summary">${escapeHtml(answer.summary)}</div>
      <div class="cypher">${escapeHtml(answer.cypher)}</div>`;
  } else if (answer.status === "refused") {
    body = `<div class="refused">Can't answer that with the current schema: ${escapeHtml(answer.refusal_reason || "")}</div>`;
  } else if (answer.status === "unsafe") {
    body = `<div class="errored">Refused to run this query: ${escapeHtml(answer.reason || "")}</div>`;
  } else {
    body = `<div class="errored">Something went wrong: ${escapeHtml(answer.error || "")}</div>`;
  }

  detailBody.innerHTML = `
    <p class="empty">Click a node or edge to inspect it.</p>
    <div class="ask-answer">
      <div class="question">“${escapeHtml(answer.question)}”</div>
      ${body}
    </div>
  `;
}

// --- Theme toggle ---

const THEME_KEY = "ligature-theme";

function initTheme() {
  let stored = null;
  try {
    stored = localStorage.getItem(THEME_KEY);
  } catch {
    // Private browsing / blocked storage — fall back to the system preference below.
  }
  if (stored === "light" || stored === "dark") {
    document.documentElement.setAttribute("data-theme", stored);
  }
}

themeToggle.addEventListener("click", () => {
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const current = document.documentElement.getAttribute("data-theme") || (systemDark ? "dark" : "light");
  const next = current === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  try {
    localStorage.setItem(THEME_KEY, next);
  } catch {
    // Nothing to persist to if storage is unavailable — the toggle still
    // works for the rest of this page load.
  }
});

initTheme();

// --- Initial load ---

getOverview()
  .then((subgraph) => {
    graph.merge(subgraph);
    graphLoading.classList.add("hidden");
  })
  .catch((err) => {
    console.error("overview load failed", err);
    graphLoading.classList.add("errored");
    graphLoadingText.textContent = "Couldn't load the graph. Is the API reachable?";
  });
