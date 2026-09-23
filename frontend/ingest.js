import { uploadIngest } from "./api.js";

const form = document.getElementById("ingest-form");
const submitButton = document.getElementById("ingest-submit");
const reportEl = document.getElementById("ingest-report");
const themeToggle = document.getElementById("theme-toggle");

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const SOURCE_LABELS = {
  roster: "Athlete roster",
  gps: "GPS / session export",
  wellness: "Wellness survey export",
  injuries: "Injury log",
};

let rowListSeq = 0;

function rowList(rows, kind) {
  if (!rows || rows.length === 0) return "";
  const id = `ingest-rows-${kind}-${rowListSeq++}`;
  const items = rows
    .map((r) => `<li><span class="ingest-row-line">line ${r.line}</span>${escapeHtml(r.reason)}</li>`)
    .join("");
  const label = kind === "warnings" ? "warning" : "skipped row";
  return `
    <button type="button" class="ingest-detail-toggle" data-target="${id}">
      ${rows.length} ${label}${rows.length === 1 ? "" : "s"} — show
    </button>
    <ul class="ingest-row-list" id="${id}">${items}</ul>
  `;
}

function sourceCard(key, result) {
  if (result == null) return "";
  const title = SOURCE_LABELS[key];

  if (result.file_error) {
    return `
      <div class="ingest-source-card">
        <div class="ingest-source-title">${escapeHtml(title)}</div>
        <div class="ingest-file-error">${escapeHtml(result.file_error)}</div>
      </div>`;
  }

  const stats = result.stats || {};
  const statPairs = Object.entries(stats)
    .map(([k, v]) => {
      const label = k.replace(/_/g, " ");
      const cls = k === "skipped" && v > 0 ? " ingest-stat-skipped" : "";
      return `<span class="${cls.trim()}"><strong>${escapeHtml(String(v))}</strong> ${escapeHtml(label)}</span>`;
    })
    .join("");

  return `
    <div class="ingest-source-card">
      <div class="ingest-source-title">${escapeHtml(title)}</div>
      <div class="ingest-stat-row">${statPairs}</div>
      ${rowList(result.warnings, "warnings")}
      ${rowList(result.skipped_rows, "skipped")}
    </div>`;
}

function renderReport(report) {
  const cards = ["roster", "gps", "wellness", "injuries"].map((key) => sourceCard(key, report[key])).join("");
  const abortedBanner = report.aborted
    ? `<div class="ingest-banner ingest-banner-aborted">Import stopped — the roster couldn't be loaded, so nothing else was resolved against it. Fix the issue above and try again.</div>`
    : "";

  reportEl.innerHTML = `${abortedBanner}${cards}`;
  reportEl.classList.remove("hidden");

  for (const btn of reportEl.querySelectorAll(".ingest-detail-toggle")) {
    btn.addEventListener("click", () => {
      const target = document.getElementById(btn.dataset.target);
      const open = target.classList.toggle("open");
      const count = target.children.length;
      const kind = btn.dataset.target.includes("warnings") ? "warning" : "skipped row";
      btn.textContent = `${count} ${kind}${count === 1 ? "" : "s"} — ${open ? "hide" : "show"}`;
    });
  }
}

function renderError(message) {
  reportEl.innerHTML = `<div class="ingest-banner ingest-banner-error">${escapeHtml(message)}</div>`;
  reportEl.classList.remove("hidden");
}

form.addEventListener("submit", async (ev) => {
  ev.preventDefault();

  const rosterInput = document.getElementById("file-roster");
  if (!rosterInput.files[0]) return;

  const files = {
    roster: rosterInput.files[0],
    gps: document.getElementById("file-gps").files[0] || null,
    wellness: document.getElementById("file-wellness").files[0] || null,
    injuries: document.getElementById("file-injuries").files[0] || null,
  };

  submitButton.disabled = true;
  submitButton.textContent = "Importing…";
  reportEl.classList.add("hidden");

  try {
    const report = await uploadIngest(files);
    renderReport(report);
  } catch (err) {
    console.error("ingest failed", err);
    renderError(`Import failed: ${err.message || err}`);
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "Import";
  }
});

// --- Theme toggle (same logic as app.js -- this is a standalone page,
// so it isn't shared as a module, just kept in sync by hand) ---

const THEME_KEY = "ligature-theme";

function initTheme() {
  let stored = null;
  try {
    stored = localStorage.getItem(THEME_KEY);
  } catch {
    // Private browsing / blocked storage -- fall back to the system preference below.
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
    // Nothing to persist to if storage is unavailable -- the toggle still
    // works for the rest of this page load.
  }
});

initTheme();
