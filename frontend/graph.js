// Force-directed graph render + interactions: drag, pan/zoom, tap-to-select
// (node and edge), shape+color node typing. Adapted from an earlier
// hand-rolled prototype for this same product; the physics model and
// interaction shape carry over, rewritten here as a small module with a
// click-vs-drag distance threshold (rather than manual pointerdown-order
// bookkeeping) so neither of that prototype's two known bugs — a tap
// leaving a node permanently pinned, and an edge-tap selection getting
// wiped by a same-tick background handler — has a way to recur.

const SVG_NS = "http://www.w3.org/2000/svg";

const REPULSION = 2600;
const SPRING = 0.02;
const REST_LEN = 95;
const GRAVITY = 0.015;
const DAMPING = 0.82;
const CLICK_DRAG_THRESHOLD = 5; // px of pointer travel before a press counts as a drag, not a tap
const SLEEP_ENERGY = 0.02;
const SLEEP_FRAMES = 40;
const MIN_SCALE = 0.25;
const MAX_SCALE = 3;

// Primary types (Athlete, Injury, Flag) carry a bold shape and a
// persistent canvas label. Secondary/detail types share one small-dot
// shape and get NO persistent label — only a hover tooltip and the detail
// panel on click — so the canvas never turns into a wall of ids like
// `metric-0045`. Legend, not shape, does the identification work for
// these (design system: "keeps the canvas from turning into a shape zoo").
const TYPE_STYLE = {
  Athlete: { tier: "primary", shape: "circle", stroke: "var(--athlete)", fill: "var(--athlete-fill)", r: 20 },
  Injury: { tier: "primary", shape: "diamond", stroke: "var(--injury)", fill: "var(--injury-fill)", r: 20 },
  Flag: { tier: "primary", shape: "triangle", stroke: "var(--flag)", fill: "var(--flag-fill)", r: 20, halo: true },
  Treatment: { tier: "secondary", shape: "circle", stroke: "var(--treatment)", fill: "var(--treatment-fill)", r: 9 },
  Physio: { tier: "secondary", shape: "circle", stroke: "var(--treatment)", fill: "var(--treatment-fill)", r: 9 },
  RehabSession: { tier: "secondary", shape: "circle", stroke: "var(--treatment)", fill: "var(--treatment-fill)", r: 9 },
  WellnessEntry: { tier: "secondary", shape: "circle", stroke: "var(--wellness)", fill: "var(--wellness-fill)", r: 9 },
  Outcome: { tier: "secondary", shape: "circle", stroke: "var(--outcome)", fill: "var(--outcome-fill)", r: 9 },
  SessionMetric: { tier: "secondary", shape: "circle", stroke: "var(--metric)", fill: "var(--metric-fill)", r: 9 },
};
const DEFAULT_STYLE = { tier: "secondary", shape: "circle", stroke: "var(--metric)", fill: "var(--metric-fill)", r: 9 };

// Primary-type labels: Athlete is "who" (sans, bold, prominent). Injury
// and Flag are "what happened" (mono, quieter) -- the type scale's own
// rule that mono is reserved for anything that IS data, applied to the
// one place on the canvas where that distinction matters most.
const LABEL_STYLE = {
  Athlete: "sans",
  Injury: "mono",
  Flag: "mono",
};

// Edge types worth a confidence/label chip on the canvas -- the small set
// this product actually differentiates on (cross-athlete pattern matches),
// not every relationship, which would just recreate the clutter this
// design pass exists to remove.
const LABELED_EDGE_TYPES = new Set(["SIMILAR_PATTERN_TO", "MATCHES"]);

function styleFor(label) {
  return TYPE_STYLE[label] || DEFAULT_STYLE;
}

function shapeElement(shape, r) {
  if (shape === "circle") {
    const el = document.createElementNS(SVG_NS, "circle");
    el.setAttribute("r", r);
    return el;
  }
  if (shape === "square") {
    const el = document.createElementNS(SVG_NS, "rect");
    el.setAttribute("x", -r);
    el.setAttribute("y", -r);
    el.setAttribute("width", r * 2);
    el.setAttribute("height", r * 2);
    return el;
  }
  if (shape === "diamond") {
    const el = document.createElementNS(SVG_NS, "rect");
    const side = r * 1.4;
    el.setAttribute("x", -side / 2);
    el.setAttribute("y", -side / 2);
    el.setAttribute("width", side);
    el.setAttribute("height", side);
    el.setAttribute("rx", 3);
    el.setAttribute("transform", "rotate(45)");
    return el;
  }
  // triangle
  const el = document.createElementNS(SVG_NS, "polygon");
  el.setAttribute("points", `0,${-r} ${r},${r} ${-r},${r}`);
  return el;
}

function truncateLabel(s, max = 22) {
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

function humanizeEnum(value) {
  const s = String(value).replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function nodeDisplayName(node) {
  const p = node.properties || {};
  // display_name: computed server-side for the two labels (Flag,
  // SessionMetric) whose own properties have nothing readable on them --
  // see api/graph.py's _enrich_display_names. Everything else already
  // carries a usable property directly.
  if (p.display_name) return p.display_name;
  if (p.name) return p.name;
  if (p.type) return p.type;
  if (p.protocol) return p.protocol;
  if (p.result) return humanizeEnum(p.result); // Outcome: "clean_return" -> "Clean return"
  return node.id;
}

export function createGraph(svg, { onNodeClick, onEdgeClick, onBackgroundClick } = {}) {
  const nodes = new Map(); // id -> {id,label,properties,x,y,vx,vy,fx,fy}
  const edges = new Map(); // id -> {id,type,from,to,properties}
  const nodeEls = new Map(); // id -> {group, shape, label}
  const edgeEls = new Map(); // id -> {line, hit, labelGroup}

  const viewport = document.createElementNS(SVG_NS, "g");
  const edgeLayer = document.createElementNS(SVG_NS, "g");
  const nodeLayer = document.createElementNS(SVG_NS, "g");
  viewport.appendChild(edgeLayer);
  viewport.appendChild(nodeLayer);
  svg.appendChild(viewport);

  let transform = { x: 0, y: 0, scale: 1 };
  let highlighted = new Set();

  // --- Visibility / filtering ---
  // Two independent mechanisms, not one combined predicate: typeFilter is
  // a persistent rule (from the filter panel's checkboxes, reapplied to
  // every node including ones added later via expand/search), snapshot is
  // a one-shot override (from an ask-in-English answer, replacing
  // whatever typeFilter would show until explicitly cleared). forceShown
  // is neither -- an explicit click or search selection always wins over
  // both, since hiding something the user just asked to see would be
  // exactly backwards.
  let typeFilter = () => true;
  let snapshot = null; // Set of ids, or null
  const forceShown = new Set();
  const hidden = new Set(); // ids currently hidden -- tick() excludes these from physics too,
  // not just CSS display:none, so a hidden node can't still shove the
  // visible layout around from off-screen.

  function applyTransform() {
    viewport.setAttribute(
      "transform",
      `translate(${transform.x},${transform.y}) scale(${transform.scale})`
    );
  }
  applyTransform();

  function clientSize() {
    const rect = svg.getBoundingClientRect();
    return { width: rect.width || 800, height: rect.height || 600 };
  }

  function toGraphCoords(clientX, clientY) {
    const rect = svg.getBoundingClientRect();
    const sx = clientX - rect.left;
    const sy = clientY - rect.top;
    return {
      x: (sx - transform.x) / transform.scale,
      y: (sy - transform.y) / transform.scale,
    };
  }

  function zoomAtPoint(px, py, factor) {
    const newScale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, transform.scale * factor));
    const graphX = (px - transform.x) / transform.scale;
    const graphY = (py - transform.y) / transform.scale;
    transform.scale = newScale;
    transform.x = px - graphX * newScale;
    transform.y = py - graphY * newScale;
    applyTransform();
  }

  function zoomAtCenter(factor) {
    const { width, height } = clientSize();
    zoomAtPoint(width / 2, height / 2, factor);
  }

  function resetView() {
    transform = { x: 0, y: 0, scale: 1 };
    applyTransform();
  }

  // --- Simulation ---

  let sleeping = true;
  let quietFrames = 0;
  let rafHandle = null;

  function wake() {
    sleeping = false;
    quietFrames = 0;
    if (rafHandle === null) {
      rafHandle = requestAnimationFrame(loop);
    }
  }

  function tick() {
    const { width, height } = clientSize();
    const cx = width / 2 / transform.scale;
    const cy = height / 2 / transform.scale;
    const list = [...nodes.values()].filter((n) => !hidden.has(n.id));

    for (const n of list) {
      n.fx_ = 0;
      n.fy_ = 0;
    }

    for (let i = 0; i < list.length; i++) {
      for (let j = i + 1; j < list.length; j++) {
        const a = list[i];
        const b = list[j];
        let dx = a.x - b.x;
        let dy = a.y - b.y;
        let distSq = dx * dx + dy * dy;
        if (distSq < 1) distSq = 1;
        const force = REPULSION / distSq;
        const dist = Math.sqrt(distSq);
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        a.fx_ += fx;
        a.fy_ += fy;
        b.fx_ -= fx;
        b.fy_ -= fy;
      }
    }

    for (const e of edges.values()) {
      if (hidden.has(e.from) || hidden.has(e.to)) continue;
      const a = nodes.get(e.from);
      const b = nodes.get(e.to);
      if (!a || !b) continue;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const dist = Math.max(1, Math.sqrt(dx * dx + dy * dy));
      const stretch = dist - REST_LEN;
      const force = SPRING * stretch;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      a.fx_ += fx;
      a.fy_ += fy;
      b.fx_ -= fx;
      b.fy_ -= fy;
    }

    let energy = 0;
    for (const n of list) {
      n.fx_ += (cx - n.x) * GRAVITY;
      n.fy_ += (cy - n.y) * GRAVITY;

      if (n.fx != null) {
        n.x = n.fx;
        n.y = n.fy;
        n.vx = 0;
        n.vy = 0;
        continue;
      }

      n.vx = (n.vx + n.fx_) * DAMPING;
      n.vy = (n.vy + n.fy_) * DAMPING;
      n.x += n.vx;
      n.y += n.vy;
      energy += n.vx * n.vx + n.vy * n.vy;
    }

    return energy;
  }

  function render() {
    for (const n of nodes.values()) {
      const els = nodeEls.get(n.id);
      if (!els) continue;
      els.group.setAttribute("transform", `translate(${n.x},${n.y})`);
    }
    for (const e of edges.values()) {
      const a = nodes.get(e.from);
      const b = nodes.get(e.to);
      const els = edgeEls.get(e.id);
      if (!a || !b || !els) continue;
      els.line.setAttribute("x1", a.x);
      els.line.setAttribute("y1", a.y);
      els.line.setAttribute("x2", b.x);
      els.line.setAttribute("y2", b.y);
      els.hit.setAttribute("x1", a.x);
      els.hit.setAttribute("y1", a.y);
      els.hit.setAttribute("x2", b.x);
      els.hit.setAttribute("y2", b.y);
      if (els.labelGroup) {
        els.labelGroup.setAttribute("transform", `translate(${(a.x + b.x) / 2},${(a.y + b.y) / 2})`);
      }
    }
  }

  function loop() {
    const energy = tick();
    render();
    if (energy < SLEEP_ENERGY) {
      quietFrames += 1;
    } else {
      quietFrames = 0;
    }
    if (quietFrames > SLEEP_FRAMES) {
      sleeping = true;
      rafHandle = null;
      return;
    }
    rafHandle = requestAnimationFrame(loop);
  }

  // --- Node/edge creation ---

  function ensureNode(node) {
    if (nodes.has(node.id)) {
      const existing = nodes.get(node.id);
      existing.label = node.label;
      existing.properties = node.properties;
      return existing;
    }
    const { width, height } = clientSize();
    const cx = width / 2 / transform.scale;
    const cy = height / 2 / transform.scale;
    const angle = Math.random() * Math.PI * 2;
    const entry = {
      id: node.id,
      label: node.label,
      properties: node.properties,
      x: cx + Math.cos(angle) * 40,
      y: cy + Math.sin(angle) * 40,
      vx: 0,
      vy: 0,
      fx: null,
      fy: null,
    };
    nodes.set(node.id, entry);

    const style = styleFor(node.label);
    const group = document.createElementNS(SVG_NS, "g");
    group.setAttribute("data-id", node.id);
    group.setAttribute("data-label", node.label);

    // Flag halo: calm static rings behind the shape, not a pulsing/red
    // alert -- a Flag means "this matches a prior pattern," never
    // "something is wrong right now." Also drawn on an Athlete carrying
    // active_flag_count (api/graph.py's fetch_overview no longer sends
    // Flag nodes into the overview at all -- the agent writes one Flag
    // per matched historical injury by design, so an at-risk athlete
    // matching a 5-injury cluster is 5 separate Flag nodes; showing every
    // one of those on the first screen is exactly the clutter this halo
    // replaces. Clicking the athlete still reveals the real Flag nodes.
    const flagCount = node.properties?.active_flag_count;
    if (style.halo || flagCount) {
      const outer = document.createElementNS(SVG_NS, "circle");
      outer.setAttribute("class", "flag-halo outer");
      outer.setAttribute("r", style.r + 14);
      group.appendChild(outer);
      const inner = document.createElementNS(SVG_NS, "circle");
      inner.setAttribute("class", "flag-halo inner");
      inner.setAttribute("r", style.r + 4);
      group.appendChild(inner);
    }

    const shape = shapeElement(style.shape, style.r);
    const tierClass = style.tier === "primary" ? "" : " secondary";
    // node-enter: a one-shot appear animation, safe to leave on
    // permanently since ensureNode only reaches this branch once per id.
    shape.setAttribute("class", `node-shape node-enter${tierClass}`);
    shape.setAttribute("fill", style.fill);
    shape.setAttribute("stroke", style.stroke);
    shape.style.color = style.stroke; // for .highlighted's drop-shadow(currentColor)
    group.appendChild(shape);

    const fullName = nodeDisplayName(node);
    if (style.tier === "primary") {
      const labelStyle = LABEL_STYLE[node.label] || "mono";
      const label = document.createElementNS(SVG_NS, "text");
      label.setAttribute("class", `node-label${labelStyle === "mono" ? " secondary" : ""}`);
      label.setAttribute("text-anchor", "middle");
      label.setAttribute("y", style.r + 14);
      label.textContent = truncateLabel(fullName);
      group.appendChild(label);
      nodeEls.set(node.id, { group, shape, label });
    } else {
      nodeEls.set(node.id, { group, shape, label: null });
    }

    // Secondary nodes carry no persistent label -- a hover tooltip (and
    // the detail panel on click) is the full text either way. A flagged
    // athlete's halo has no room for a count on its own, so it goes here.
    const title = document.createElementNS(SVG_NS, "title");
    title.textContent = flagCount ? `${fullName} · ${flagCount} active flag${flagCount === 1 ? "" : "s"}` : fullName;
    group.appendChild(title);

    nodeLayer.appendChild(group);
    attachNodeInteraction(entry, group);
    return entry;
  }

  function ensureEdge(edge) {
    if (edges.has(edge.id)) return;
    edges.set(edge.id, edge);

    const line = document.createElementNS(SVG_NS, "line");
    line.setAttribute("class", `edge-line ${edge.type}`);
    edgeLayer.appendChild(line);

    const hit = document.createElementNS(SVG_NS, "line");
    hit.setAttribute("class", "edge-hit");
    edgeLayer.appendChild(hit);
    // Stopped on pointerdown too, not just click: the svg-level pointerdown
    // handler below starts a pan/background-click sequence on every press,
    // and pointerdown always reaches it before this element's own click
    // fires — so without this, a tap on an edge still triggers a spurious
    // background deselect right before the edge selection lands.
    hit.addEventListener("pointerdown", (ev) => ev.stopPropagation());
    hit.addEventListener("click", (ev) => {
      ev.stopPropagation();
      if (onEdgeClick) onEdgeClick(edge);
    });

    let labelGroup = null;
    if (LABELED_EDGE_TYPES.has(edge.type)) {
      const confidence = edge.properties?.confidence;
      const text = confidence != null ? `${Math.round(confidence * 100)}%` : edge.type;
      labelGroup = document.createElementNS(SVG_NS, "g");
      labelGroup.setAttribute("class", `edge-label ${edge.type}`);
      const width = Math.max(28, text.length * 6.5 + 12);
      const rect = document.createElementNS(SVG_NS, "rect");
      rect.setAttribute("x", -width / 2);
      rect.setAttribute("y", -8);
      rect.setAttribute("width", width);
      rect.setAttribute("height", 16);
      rect.setAttribute("rx", 4);
      labelGroup.appendChild(rect);
      const text_ = document.createElementNS(SVG_NS, "text");
      text_.setAttribute("text-anchor", "middle");
      text_.setAttribute("y", 3);
      text_.textContent = text;
      labelGroup.appendChild(text_);
      edgeLayer.appendChild(labelGroup);
    }

    edgeEls.set(edge.id, { line, hit, labelGroup });
  }

  // --- Node drag / tap ---

  function attachNodeInteraction(entry, group) {
    let dragging = false;
    let moved = false;
    let startClient = null;
    let pointerOffset = { x: 0, y: 0 };

    group.addEventListener("pointerdown", (ev) => {
      ev.stopPropagation();
      dragging = true;
      moved = false;
      startClient = { x: ev.clientX, y: ev.clientY };
      const g = toGraphCoords(ev.clientX, ev.clientY);
      pointerOffset = { x: entry.x - g.x, y: entry.y - g.y };
      group.setPointerCapture(ev.pointerId);
    });

    group.addEventListener("pointermove", (ev) => {
      if (!dragging) return;
      const dx = ev.clientX - startClient.x;
      const dy = ev.clientY - startClient.y;
      if (Math.hypot(dx, dy) > CLICK_DRAG_THRESHOLD) moved = true;
      if (moved) {
        const g = toGraphCoords(ev.clientX, ev.clientY);
        entry.fx = g.x + pointerOffset.x;
        entry.fy = g.y + pointerOffset.y;
        wake();
      }
    });

    function endDrag(ev) {
      if (!dragging) return;
      dragging = false;
      if (!moved) {
        // A tap, not a drag: never leave the node pinned from a plain click.
        entry.fx = null;
        entry.fy = null;
        if (onNodeClick) onNodeClick(entry);
      }
      wake();
    }

    group.addEventListener("pointerup", endDrag);
    group.addEventListener("pointercancel", endDrag);
  }

  // --- Pan / zoom on the background ---

  let panning = false;
  let panMoved = false;
  let panStart = null;
  let panOrigin = null;

  svg.addEventListener("pointerdown", (ev) => {
    panning = true;
    panMoved = false;
    panStart = { x: ev.clientX, y: ev.clientY };
    panOrigin = { x: transform.x, y: transform.y };
    svg.classList.add("panning");
  });

  svg.addEventListener("pointermove", (ev) => {
    if (!panning) return;
    const dx = ev.clientX - panStart.x;
    const dy = ev.clientY - panStart.y;
    if (Math.hypot(dx, dy) > CLICK_DRAG_THRESHOLD) panMoved = true;
    if (panMoved) {
      transform.x = panOrigin.x + dx;
      transform.y = panOrigin.y + dy;
      applyTransform();
    }
  });

  function endPan() {
    if (!panning) return;
    panning = false;
    svg.classList.remove("panning");
    if (!panMoved && onBackgroundClick) onBackgroundClick();
  }
  svg.addEventListener("pointerup", endPan);
  svg.addEventListener("pointercancel", endPan);

  svg.addEventListener(
    "wheel",
    (ev) => {
      ev.preventDefault();
      const rect = svg.getBoundingClientRect();
      const px = ev.clientX - rect.left;
      const py = ev.clientY - rect.top;
      const factor = Math.exp(-ev.deltaY * 0.001);
      zoomAtPoint(px, py, factor);
    },
    { passive: false }
  );

  // --- Public API ---

  function merge(subgraph) {
    for (const node of subgraph.nodes || []) ensureNode(node);
    for (const edge of subgraph.edges || []) ensureEdge(edge);
    // Not just wake(): a newly-added node needs its visibility decided
    // against whichever filter is currently active (typeFilter or a
    // snapshot) before the physics sim starts moving it, same as every
    // node already on screen.
    recomputeVisibility();
  }

  // isVisible's precedence, most specific first: an explicit click or
  // search selection (forceShown) always wins; failing that, an active
  // ask-in-English snapshot shows only its matches; failing that, the
  // filter panel's persistent typeFilter decides.
  function isVisible(id) {
    if (forceShown.has(id)) return true;
    if (snapshot) return snapshot.has(id);
    const node = nodes.get(id);
    return node ? typeFilter(node) : true;
  }

  function recomputeVisibility() {
    hidden.clear();
    for (const [id, els] of nodeEls) {
      const visible = isVisible(id);
      if (!visible) hidden.add(id);
      els.group.classList.toggle("node-hidden", !visible);
    }
    for (const [id, els] of edgeEls) {
      const edge = edges.get(id);
      const edgeHidden = !edge || hidden.has(edge.from) || hidden.has(edge.to);
      els.line.classList.toggle("edge-hidden", edgeHidden);
      els.hit.classList.toggle("edge-hidden", edgeHidden);
      if (els.labelGroup) els.labelGroup.classList.toggle("edge-hidden", edgeHidden);
    }
    wake();
  }

  function setTypeFilter(fn) {
    typeFilter = fn;
    snapshot = null;
    forceShown.clear();
    recomputeVisibility();
  }

  function setSnapshotFilter(ids) {
    snapshot = ids && ids.length ? new Set(ids) : null;
    forceShown.clear();
    recomputeVisibility();
  }

  // An explicit click or search selection always shows its target,
  // regardless of the active filter -- forceShown is cleared whenever a
  // new filter or snapshot is set (both setters above), so these
  // overrides don't linger and quietly punch permanent holes in whatever
  // filter the user sets up next.
  function forceShow(id) {
    forceShown.add(id);
    recomputeVisibility();
  }

  function highlight(ids) {
    highlighted = new Set(ids);
    for (const [id, els] of nodeEls) {
      const on = highlighted.has(id);
      els.shape.classList.toggle("highlighted", on);
      if (els.label) els.label.classList.toggle("highlighted", on);
    }
  }

  function hasNode(id) {
    return nodes.has(id);
  }

  function getNode(id) {
    return nodes.get(id);
  }

  function edgesForNode(id) {
    return [...edges.values()].filter((e) => e.from === id || e.to === id);
  }

  function nodeCount() {
    return nodes.size;
  }

  return {
    merge,
    highlight,
    hasNode,
    getNode,
    edgesForNode,
    nodeCount,
    zoomIn: () => zoomAtCenter(1.25),
    zoomOut: () => zoomAtCenter(0.8),
    resetView,
    setTypeFilter,
    setSnapshotFilter,
    forceShow,
  };
}
