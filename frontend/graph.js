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

const TYPE_STYLE = {
  Athlete: { shape: "circle", fill: "var(--athlete)", r: 16 },
  Injury: { shape: "diamond", fill: "var(--injury)", r: 15 },
  Flag: { shape: "triangle", fill: "var(--flag)", r: 14 },
  SessionMetric: { shape: "square", fill: "var(--injury-fill)", r: 8 },
  WellnessEntry: { shape: "square", fill: "var(--wellness)", r: 8 },
  Treatment: { shape: "square", fill: "var(--physio)", r: 11 },
  Physio: { shape: "circle", fill: "var(--physio)", r: 10 },
  RehabSession: { shape: "square", fill: "var(--physio-fill)", r: 10 },
  Outcome: { shape: "circle", fill: "var(--clean)", r: 10 },
  ClinicalNote: { shape: "square", fill: "var(--mist-strong)", r: 8 },
  Cluster: { shape: "triangle", fill: "var(--signal)", r: 12 },
};
const DEFAULT_STYLE = { shape: "circle", fill: "var(--ink-muted)", r: 9 };

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
    const el = document.createElementNS(SVG_NS, "polygon");
    el.setAttribute("points", `0,${-r} ${r},0 0,${r} ${-r},0`);
    return el;
  }
  // triangle
  const el = document.createElementNS(SVG_NS, "polygon");
  el.setAttribute("points", `0,${-r} ${r},${r} ${-r},${r}`);
  return el;
}

export function createGraph(svg, { onNodeClick, onEdgeClick, onBackgroundClick } = {}) {
  const nodes = new Map(); // id -> {id,label,properties,x,y,vx,vy,fx,fy}
  const edges = new Map(); // id -> {id,type,from,to,properties}
  const nodeEls = new Map(); // id -> {group, shape}
  const edgeEls = new Map(); // id -> {line, hit}

  const viewport = document.createElementNS(SVG_NS, "g");
  const edgeLayer = document.createElementNS(SVG_NS, "g");
  const nodeLayer = document.createElementNS(SVG_NS, "g");
  viewport.appendChild(edgeLayer);
  viewport.appendChild(nodeLayer);
  svg.appendChild(viewport);

  let transform = { x: 0, y: 0, scale: 1 };
  let highlighted = new Set();

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
    const list = [...nodes.values()];

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
    const shape = shapeElement(style.shape, style.r);
    shape.setAttribute("class", "node-shape");
    shape.setAttribute("fill", style.fill);
    group.appendChild(shape);

    const label = document.createElementNS(SVG_NS, "text");
    label.setAttribute("class", "node-label");
    label.setAttribute("text-anchor", "middle");
    label.setAttribute("y", style.r + 12);
    label.textContent = nodeDisplayName(node);
    group.appendChild(label);

    nodeLayer.appendChild(group);
    nodeEls.set(node.id, { group, shape });

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

    edgeEls.set(edge.id, { line, hit });
  }

  function nodeDisplayName(node) {
    const p = node.properties || {};
    return p.name || p.type || p.protocol || p.result || node.id;
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
      const newScale = Math.min(3, Math.max(0.25, transform.scale * factor));
      const graphX = (px - transform.x) / transform.scale;
      const graphY = (py - transform.y) / transform.scale;
      transform.scale = newScale;
      transform.x = px - graphX * newScale;
      transform.y = py - graphY * newScale;
      applyTransform();
    },
    { passive: false }
  );

  // --- Public API ---

  function merge(subgraph) {
    for (const node of subgraph.nodes || []) ensureNode(node);
    for (const edge of subgraph.edges || []) ensureEdge(edge);
    wake();
  }

  function highlight(ids) {
    highlighted = new Set(ids);
    for (const [id, els] of nodeEls) {
      els.shape.classList.toggle("highlighted", highlighted.has(id));
    }
  }

  function hasNode(id) {
    return nodes.has(id);
  }

  function nodeCount() {
    return nodes.size;
  }

  return { merge, highlight, hasNode, nodeCount };
}
