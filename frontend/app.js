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
const answerBand = document.getElementById("answer-band");
const legendPanel = document.getElementById("legend-panel");
const legendToggle = document.getElementById("legend-toggle");
const legendPill = document.getElementById("legend-pill");
const legendSheet = document.getElementById("legend-sheet");
const zoomIn = document.getElementById("zoom-in");
const zoomOut = document.getElementById("zoom-out");
const zoomReset = document.getElementById("zoom-reset");

const MOBILE_QUERY = window.matchMedia("(max-width: 760px)");

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
  graph.highlight([node.id]);
  if (!node._expanded) {
    node._expanded = true;
    try {
      const subgraph = await expandNode(node.id);
      graph.merge(subgraph);
      // The relationships section was built from whatever had already
      // loaded — refresh it now that expand may have pulled in more.
      if (detailBody.dataset.nodeId === node.id) renderNodeDetail(node);
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
  detailBody.innerHTML = '<p class="empty">Click a node or edge to inspect it.</p>';
  delete detailBody.dataset.nodeId;
  graph.highlight([]);
  closeDetailPanel();
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// --- Node type -> label color/text, kept in sync by hand with graph.js's
// TYPE_STYLE (small enough not to be worth sharing a module for). ---

const LABEL_COLOR_VAR = {
  Athlete: "--athlete",
  Injury: "--injury",
  Flag: "--flag",
  Treatment: "--treatment",
  Physio: "--treatment",
  RehabSession: "--treatment",
  WellnessEntry: "--wellness",
  Outcome: "--outcome",
  SessionMetric: "--metric",
};

function labelColorVar(label) {
  return LABEL_COLOR_VAR[label] || "--metric";
}

function nodeHeading(node) {
  const p = node.properties || {};
  // Same fallback order as graph.js's nodeDisplayName (kept in sync
  // manually since it's a two-line check, not worth an import for) --
  // display_name covers Flag/SessionMetric, which have nothing else
  // readable on them.
  return p.display_name || p.name || p.type || node.id;
}

function propList(properties) {
  const rows = Object.entries(properties || {})
    .map(([k, v]) => {
      const value = Array.isArray(v) ? v.join(", ") : v;
      return `<div class="prop-row"><span class="prop-key">${escapeHtml(k)}</span><span class="prop-value">${escapeHtml(String(value))}</span></div>`;
    })
    .join("");
  return `<div class="prop-list">${rows}</div>`;
}

const EVIDENCE_NOTE =
  '<div class="evidence-note">Evidence view only — this surfaces matched history, it does not generate a clinical or training recommendation.</div>';

function relationshipRows(nodeId) {
  const edges = graph.edgesForNode(nodeId);
  if (edges.length === 0) return "";
  const rows = edges
    .map((edge) => {
      const otherId = edge.from === nodeId ? edge.to : edge.from;
      const other = graph.getNode(otherId);
      const otherName = other ? nodeHeading(other) : otherId;
      const emphasis = edge.type === "SIMILAR_PATTERN_TO" || edge.type === "MATCHES" || edge.type === "PRECEDED";
      const confidence = edge.properties?.confidence;
      const suffix = confidence != null ? ` — ${Math.round(confidence * 100)}% match` : "";
      const lag = edge.properties?.lag_days;
      const lagSuffix = lag != null ? ` — ${lag}d prior` : "";
      return `
        <div class="rel-row" data-jump-id="${escapeHtml(otherId)}">
          <span class="rel-chip${emphasis ? " emphasis" : ""}">${escapeHtml(edge.type)}</span>
          <span class="rel-desc">${escapeHtml(otherName)}${escapeHtml(suffix)}${escapeHtml(lagSuffix)}</span>
        </div>`;
    })
    .join("");
  return `
    <div class="detail-section">
      <div class="section-title">Relationships</div>
      <div class="rel-list">${rows}</div>
    </div>`;
}

function matchCards(nodeId) {
  const matches = graph
    .edgesForNode(nodeId)
    .filter((e) => e.type === "SIMILAR_PATTERN_TO")
    .map((e) => {
      const otherId = e.from === nodeId ? e.to : e.from;
      return { otherId, confidence: e.properties?.confidence ?? 0 };
    })
    .sort((a, b) => b.confidence - a.confidence);
  if (matches.length === 0) return "";

  const cards = matches
    .map(({ otherId, confidence }) => {
      const other = graph.getNode(otherId);
      const name = other ? nodeHeading(other) : otherId;
      const desc = other?.properties?.body_part || other?.properties?.date || "";
      return `
        <div class="match-card" data-jump-id="${escapeHtml(otherId)}">
          <div class="match-head"><span>${escapeHtml(name)}</span><span class="match-pct">${Math.round(confidence * 100)}%</span></div>
          ${desc ? `<div class="match-desc">${escapeHtml(desc)}</div>` : ""}
        </div>`;
    })
    .join("");
  return `
    <div class="detail-section">
      <div class="section-title">Who else matched this pattern</div>
      <div class="section-subtitle">Same deviation signature, ranked by similarity.</div>
      <div class="match-cards">${cards}</div>
    </div>`;
}

function renderNodeDetail(node) {
  detailBody.dataset.nodeId = node.id;
  const colorVar = labelColorVar(node.label);
  // display_name is computed just to head the SVG label/this heading for
  // labels with nothing else readable (Flag, SessionMetric) -- once it's
  // shown there, repeating it as its own property row is just noise.
  const { display_name, ...rest } = node.properties || {};

  detailBody.innerHTML = `
    <div class="detail-header">
      <div>
        <div class="badge-row">
          <span class="micro-mono" style="color:var(${colorVar})">${escapeHtml(node.label)}</span>
        </div>
        <h2>${escapeHtml(nodeHeading(node))}</h2>
      </div>
    </div>
    <div class="detail-section">
      <div class="section-title">Properties</div>
      ${propList(rest)}
    </div>
    ${relationshipRows(node.id)}
    ${node.label === "Injury" ? matchCards(node.id) : ""}
    <div class="detail-section">${EVIDENCE_NOTE}</div>
  `;
  wireJumpLinks();
}

function renderEdgeDetail(edge) {
  const fromNode = graph.getNode(edge.from);
  const toNode = graph.getNode(edge.to);
  const fromName = fromNode ? nodeHeading(fromNode) : edge.from;
  const toName = toNode ? nodeHeading(toNode) : edge.to;
  delete detailBody.dataset.nodeId;
  detailBody.innerHTML = `
    <div class="detail-header">
      <div>
        <div class="badge-row"><span class="micro-mono" style="color:var(--flag)">${escapeHtml(edge.type)}</span></div>
        <h2>${escapeHtml(fromName)} &rarr; ${escapeHtml(toName)}</h2>
      </div>
    </div>
    <div class="detail-section">
      <div class="section-title">Properties</div>
      ${propList(edge.properties)}
    </div>
    <div class="detail-section">${EVIDENCE_NOTE}</div>
  `;
}

function wireJumpLinks() {
  for (const el of detailBody.querySelectorAll("[data-jump-id]")) {
    el.addEventListener("click", () => jumpToNode(el.dataset.jumpId));
  }
}

async function jumpToNode(id) {
  const alreadyLoaded = graph.hasNode(id);
  if (!alreadyLoaded) await focusOnNode(id); // this already calls expandNode(id) once
  const node = graph.getNode(id);
  if (!node) return;
  if (!alreadyLoaded) node._expanded = true; // avoid handleNodeClick expanding it a second time
  await handleNodeClick(node);
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
    return;
  }
  // Mobile collapses search + ask into one field (see the max-width: 760px
  // block in style.css). Enter with no suggestion open reads as a full
  // question, not a name fragment -- a physio hitting Enter mid-search
  // would normally click a suggestion instead.
  if (ev.key === "Enter" && MOBILE_QUERY.matches && searchResults.childElementCount === 0) {
    ev.preventDefault();
    const question = searchInput.value.trim();
    if (question) runAsk(question);
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

askForm.addEventListener("submit", (ev) => {
  ev.preventDefault();
  const question = askInput.value.trim();
  if (question) runAsk(question);
});

async function runAsk(question) {
  askSubmit.disabled = true;
  try {
    const answer = await askQuestion(question);
    lastAskAnswer = answer;
    renderAnswerBand(answer);
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
    renderAnswerBand(lastAskAnswer);
  } finally {
    askSubmit.disabled = false;
  }
}

function renderAnswerBand(answer) {
  let body;
  let showCypher = false;
  if (answer.status === "ok") {
    showCypher = true;
    body = `<div class="answer-summary">${escapeHtml(answer.summary)}</div>`;
  } else if (answer.status === "refused") {
    body = `<div class="answer-refused">Can't answer that with the current schema: ${escapeHtml(answer.refusal_reason || "")}</div>`;
  } else if (answer.status === "unsafe") {
    body = `<div class="answer-errored">Refused to run this query: ${escapeHtml(answer.reason || "")}</div>`;
  } else {
    body = `<div class="answer-errored">Something went wrong: ${escapeHtml(answer.error || "")}</div>`;
  }

  answerBand.innerHTML = `
    <svg class="answer-icon" width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <circle cx="9" cy="9" r="7.5" stroke="currentColor" stroke-width="1.4" fill="none" />
      <path d="M9 5v4.4l3 2" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" fill="none" />
    </svg>
    <div class="answer-body">
      <div class="answer-question">“${escapeHtml(answer.question)}”</div>
      ${body}
      ${
        showCypher
          ? `<div class="answer-actions"><button type="button" class="cypher-toggle" id="cypher-toggle">View as Cypher</button></div>
             <div class="cypher" id="answer-cypher">${escapeHtml(answer.cypher)}</div>`
          : ""
      }
    </div>
    <button type="button" class="answer-dismiss" id="answer-dismiss" aria-label="Dismiss answer">&times;</button>
  `;
  answerBand.classList.remove("hidden");

  document.getElementById("answer-dismiss").addEventListener("click", dismissAnswerBand);
  const cypherToggle = document.getElementById("cypher-toggle");
  if (cypherToggle) {
    cypherToggle.addEventListener("click", () => {
      document.getElementById("answer-cypher").classList.toggle("open");
    });
  }
}

function dismissAnswerBand() {
  lastAskAnswer = null;
  answerBand.classList.add("hidden");
  answerBand.innerHTML = "";
}

// --- Legend (floating panel on desktop, collapsed pill -> sheet on mobile) ---

const LEGEND_ITEMS = [
  { label: "Athlete", colorVar: "--athlete", fillVar: "--athlete-fill", shape: "circle" },
  { label: "Injury", colorVar: "--injury", fillVar: "--injury-fill", shape: "diamond" },
  { label: "Flag (pattern match)", colorVar: "--flag", fillVar: "--flag-fill", shape: "triangle" },
  { label: "Treatment / Physio / Rehab", colorVar: "--treatment", fillVar: "--treatment-fill", shape: "circle" },
  { label: "Wellness entry", colorVar: "--wellness", fillVar: "--wellness-fill", shape: "circle" },
  { label: "Outcome", colorVar: "--outcome", fillVar: "--outcome-fill", shape: "circle" },
  { label: "Session metric", colorVar: "--metric", fillVar: "--metric-fill", shape: "circle" },
];

function legendIcon({ colorVar, fillVar, shape }) {
  const stroke = `var(${colorVar})`;
  const fill = `var(${fillVar})`;
  if (shape === "diamond") {
    return `<svg width="14" height="14"><rect x="3" y="3" width="8" height="8" transform="rotate(45 7 7)" fill="${fill}" stroke="${stroke}" stroke-width="1.6"/></svg>`;
  }
  if (shape === "triangle") {
    return `<svg width="14" height="14"><polygon points="7,2 12,11 2,11" fill="${fill}" stroke="${stroke}" stroke-width="1.6" stroke-linejoin="round"/></svg>`;
  }
  return `<svg width="14" height="14"><circle cx="7" cy="7" r="6" fill="${fill}" stroke="${stroke}" stroke-width="1.6"/></svg>`;
}

function legendHtml() {
  return LEGEND_ITEMS.map((item) => `<div class="legend-item">${legendIcon(item)}${escapeHtml(item.label)}</div>`).join("");
}

document.getElementById("legend-items").innerHTML = legendHtml();
document.getElementById("legend-items-mobile").innerHTML = legendHtml();

legendToggle.addEventListener("click", () => legendPanel.classList.toggle("collapsed"));

legendPill.addEventListener("click", (ev) => {
  ev.stopPropagation();
  legendSheet.classList.toggle("open");
});
document.addEventListener("click", (ev) => {
  if (legendSheet.classList.contains("open") && !ev.target.closest(".legend-sheet") && !ev.target.closest(".legend-pill")) {
    legendSheet.classList.remove("open");
  }
});

// --- Zoom controls ---

zoomIn.addEventListener("click", () => graph.zoomIn());
zoomOut.addEventListener("click", () => graph.zoomOut());
zoomReset.addEventListener("click", () => graph.resetView());

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
