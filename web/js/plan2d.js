/**
 * 2D floor-plan renderer.
 *
 * Draws to SVG in real metres (1 unit = 1 m) so nothing is ever scaled by hand;
 * the viewBox does all the zooming. Plan Y runs into the plot but SVG Y runs
 * down the screen, so every Y is flipped through `fy()` rather than by
 * transforming the group — that keeps text upright without counter-transforms.
 *
 * The drawing is built from exactly the same room rectangles, wall segments and
 * openings the 3D view consumes, which is what guarantees the two agree.
 */

const NS = 'http://www.w3.org/2000/svg';
const ZONE_TINT = {
  public: '#cfe3f7', private: '#f7e0e8', service: '#fbe6cc',
  circulation: '#e6e9ee', outdoor: '#ddf0e3',
};

function el(name, attrs = {}, parent = null) {
  const n = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) {
    if (v !== null && v !== undefined) n.setAttribute(k, String(v));
  }
  if (parent) parent.appendChild(n);
  return n;
}

const fmt = (v, d = 2) => Number(v).toFixed(d);

export class Plan2D {
  constructor(host) {
    this.host = host;
    this.plan = null;
    this.floor = 0;
    this.opts = { furniture: true, dims: true, zones: false };
    this.highlight = new Set();
    this.onHover = null;
    this.onSelect = null;
    this.view = null;          // current viewBox {x,y,w,h}
    this._drag = null;
    this._bindPanZoom();
  }

  setPlan(plan) {
    const fresh = !this.plan
      || this.plan.plot.w !== plan.plot.w
      || this.plan.plot.h !== plan.plot.h;
    this.plan = plan;
    if (fresh) this.view = null;
    this.render();
  }

  setFloor(f) { this.floor = f; this.render(); }
  setOptions(o) { Object.assign(this.opts, o); this.render(); }
  setHighlight(ids) { this.highlight = new Set(ids || []); this.render(); }
  fit() { this.view = null; this.render(); }

  // ── pan & zoom ──────────────────────────────────────────
  _bindPanZoom() {
    const h = this.host;
    h.addEventListener('wheel', (e) => {
      if (!this.view) return;
      e.preventDefault();
      const r = h.getBoundingClientRect();
      const px = (e.clientX - r.left) / r.width;
      const py = (e.clientY - r.top) / r.height;
      const k = e.deltaY > 0 ? 1.12 : 1 / 1.12;
      const v = this.view;
      const nw = Math.min(Math.max(v.w * k, 1.5), 400);
      const nh = nw * (v.h / v.w);
      this.view = { x: v.x + (v.w - nw) * px, y: v.y + (v.h - nh) * py, w: nw, h: nh };
      this._applyView();
    }, { passive: false });

    h.addEventListener('mousedown', (e) => {
      if (!this.view) return;
      this._drag = { x: e.clientX, y: e.clientY, v: { ...this.view } };
    });
    window.addEventListener('mousemove', (e) => {
      if (!this._drag || !this.view) return;
      const r = h.getBoundingClientRect();
      const dx = (e.clientX - this._drag.x) / r.width * this._drag.v.w;
      const dy = (e.clientY - this._drag.y) / r.height * this._drag.v.h;
      this.view = { ...this._drag.v, x: this._drag.v.x - dx, y: this._drag.v.y - dy };
      this._applyView();
    });
    window.addEventListener('mouseup', () => { this._drag = null; });
  }

  _applyView() {
    const svg = this.host.querySelector('svg');
    if (svg && this.view) {
      const v = this.view;
      svg.setAttribute('viewBox', `${v.x} ${v.y} ${v.w} ${v.h}`);
    }
  }

  // ── render ──────────────────────────────────────────────
  render() {
    const p = this.plan;
    this.host.innerHTML = '';
    if (!p) return;

    const plot = p.plot;
    const PAD = Math.max(1.6, Math.min(plot.w, plot.h) * 0.16);
    const D = plot.h;                              // plan depth, for the Y flip
    const fy = (y) => D - y;                       // plan Y -> SVG Y

    if (!this.view) {
      this.view = { x: -PAD, y: -PAD, w: plot.w + PAD * 2, h: plot.h + PAD * 2.2 };
    }
    const v = this.view;
    const svg = el('svg', {
      viewBox: `${v.x} ${v.y} ${v.w} ${v.h}`,
      preserveAspectRatio: 'xMidYMid meet',
    });
    this.host.appendChild(svg);

    const defs = el('defs', {}, svg);
    // Hatch for open / unroofed areas.
    const hatch = el('pattern', {
      id: 'hatch', width: 0.34, height: 0.34, patternUnits: 'userSpaceOnUse',
      patternTransform: 'rotate(45)',
    }, defs);
    el('rect', { width: 0.34, height: 0.34, fill: '#eceef1' }, hatch);
    el('line', { x1: 0, y1: 0, x2: 0, y2: 0.34, stroke: '#c9ced6', 'stroke-width': 0.035 }, hatch);

    const root = el('g', {}, svg);
    const rooms = p.rooms.filter((r) => r.floor === this.floor);

    this._drawSite(root, p, fy);
    this._drawRooms(root, rooms, fy);
    this._drawWalls(root, p, fy);
    this._drawOpenings(root, p, rooms, fy);
    if (this.opts.furniture) this._drawFurniture(root, p, rooms, fy);
    this._drawLabels(root, rooms, fy);
    if (this.opts.dims) this._drawDimensions(root, p, rooms, fy);
    this._drawCompassAndScale(root, p, fy, PAD);

    return svg;
  }

  // ── site: plot boundary, setback line ───────────────────
  _drawSite(g, p, fy) {
    const plot = p.plot; const env = p.envelope;

    el('rect', {
      x: plot.x, y: fy(plot.y + plot.h), width: plot.w, height: plot.h,
      fill: '#fbfbf9', stroke: '#3b424c', 'stroke-width': 0.07,
    }, g);

    el('rect', {
      x: env.x, y: fy(env.y + env.h), width: env.w, height: env.h,
      fill: 'none', stroke: '#1f5fd0', 'stroke-width': 0.035,
      'stroke-dasharray': '0.26 0.16', opacity: 0.75,
    }, g);

    // Street edge marker along the front boundary.
    const t = el('text', {
      x: plot.x + plot.w / 2, y: fy(plot.y) + 0.62, class: 'plot-label',
      'text-anchor': 'middle',
    }, g);
    t.textContent = `STREET  ·  plot ${fmt(plot.w)} × ${fmt(plot.h)} m`;
  }

  // ── rooms ───────────────────────────────────────────────
  _drawRooms(g, rooms, fy) {
    const hl = this.highlight;
    for (const r of rooms) {
      const open = r.type === 'balcony' || r.type === 'terrace' || r.type === 'parking';
      let fill = this.opts.zones ? (ZONE_TINT[r.zone] || '#eee') : r.color;
      if (open) fill = 'url(#hatch)';

      const cls = ['room-shape'];
      if (hl.size && hl.has(r.id)) cls.push('flagged');
      else if (hl.size) cls.push('dim');

      const rect = el('rect', {
        x: r.x, y: fy(r.y + r.h), width: r.w, height: r.h,
        fill, stroke: '#aeb4bd', 'stroke-width': 0.018,
        class: cls.join(' '), 'data-room': r.id,
      }, g);

      rect.addEventListener('mouseenter', () => this.onHover && this.onHover(r));
      rect.addEventListener('mouseleave', () => this.onHover && this.onHover(null));
      rect.addEventListener('click', () => this.onSelect && this.onSelect(r));
      el('title', {}, rect).textContent =
        `${r.label} — ${fmt(r.w)} × ${fmt(r.h)} m = ${fmt(r.area, 1)} m²`;
    }
  }

  // ── walls: solid poché, the line weight that makes it read as a plan ──
  _drawWalls(g, p, fy) {
    const walls = p.walls.filter((w) => w.floor === this.floor);
    const tExt = p.constants.wall_exterior;
    const tInt = p.constants.wall_interior;
    for (const w of walls) {
      const t = w.exterior ? tExt : tInt;
      if (w.orientation === 'v') {
        el('rect', {
          x: w.x1 - t / 2, y: fy(Math.max(w.y1, w.y2)),
          width: t, height: Math.abs(w.y2 - w.y1),
          fill: '#2b3038',
        }, g);
      } else {
        el('rect', {
          x: Math.min(w.x1, w.x2), y: fy(w.y1) - t / 2,
          width: Math.abs(w.x2 - w.x1), height: t,
          fill: '#2b3038',
        }, g);
      }
    }
  }

  // ── openings: knock the wall out, then draw the symbol ──
  _drawOpenings(g, p, rooms, fy) {
    const ops = p.openings.filter((o) => o.floor === this.floor);
    const tExt = p.constants.wall_exterior;

    for (const o of ops) {
      const isWin = o.kind === 'window';
      const t = tExt * 1.25;                  // generous, to clear both wall weights

      // 1. erase the wall across the opening
      if (o.orientation === 'v') {
        el('rect', {
          x: o.x - t / 2, y: fy(o.y + o.width / 2),
          width: t, height: o.width, fill: '#fbfbf9',
        }, g);
      } else {
        el('rect', {
          x: o.x - o.width / 2, y: fy(o.y) - t / 2,
          width: o.width, height: t, fill: '#fbfbf9',
        }, g);
      }

      if (isWin) this._window(g, o, fy);
      else this._door(g, o, fy);
    }
  }

  _window(g, o, fy) {
    const s = 0.055;
    if (o.orientation === 'v') {
      const y1 = fy(o.y + o.width / 2); const y2 = fy(o.y - o.width / 2);
      el('line', { x1: o.x, y1, x2: o.x, y2, stroke: '#2b3038', 'stroke-width': s * 1.5 }, g);
      el('line', { x1: o.x - 0.075, y1, x2: o.x - 0.075, y2, stroke: '#5c93d6', 'stroke-width': s }, g);
      el('line', { x1: o.x + 0.075, y1, x2: o.x + 0.075, y2, stroke: '#5c93d6', 'stroke-width': s }, g);
    } else {
      const y = fy(o.y); const x1 = o.x - o.width / 2; const x2 = o.x + o.width / 2;
      el('line', { x1, y1: y, x2, y2: y, stroke: '#2b3038', 'stroke-width': s * 1.5 }, g);
      el('line', { x1, y1: y - 0.075, x2, y2: y - 0.075, stroke: '#5c93d6', 'stroke-width': s }, g);
      el('line', { x1, y1: y + 0.075, x2, y2: y + 0.075, stroke: '#5c93d6', 'stroke-width': s }, g);
    }
  }

  _door(g, o, fy) {
    const w = o.width;
    const main = o.kind === 'main_door';
    const col = main ? '#1f5fd0' : '#3b424c';
    const sw = main ? 0.05 : 0.038;
    const dir = o.swing >= 0 ? 1 : -1;

    if (o.orientation === 'v') {
      const hy = fy(o.y - w / 2);            // hinge at one end of the opening
      const ey = fy(o.y + w / 2);
      el('line', { x1: o.x, y1: hy, x2: o.x + dir * w, y2: hy, stroke: col, 'stroke-width': sw }, g);
      el('path', {
        d: `M ${o.x + dir * w} ${hy} A ${w} ${w} 0 0 ${dir > 0 ? 0 : 1} ${o.x} ${ey}`,
        fill: 'none', stroke: col, 'stroke-width': sw * 0.62, 'stroke-dasharray': '0.1 0.07',
      }, g);
    } else {
      const hx = o.x - w / 2;
      const ex = o.x + w / 2;
      const y = fy(o.y);
      el('line', { x1: hx, y1: y, x2: hx, y2: y + dir * w, stroke: col, 'stroke-width': sw }, g);
      el('path', {
        d: `M ${hx} ${y + dir * w} A ${w} ${w} 0 0 ${dir > 0 ? 1 : 0} ${ex} ${y}`,
        fill: 'none', stroke: col, 'stroke-width': sw * 0.62, 'stroke-dasharray': '0.1 0.07',
      }, g);
    }
  }

  // ── furniture ───────────────────────────────────────────
  _drawFurniture(g, p, rooms, fy) {
    const ids = new Set(rooms.map((r) => r.id));
    const items = p.furniture.filter((f) => ids.has(f.room));
    const S = { stroke: '#6d7581', 'stroke-width': 0.026, fill: '#ffffff', 'fill-opacity': 0.72 };

    for (const f of items) {
      const x = f.x; const y = fy(f.y + f.h); const w = f.w; const h = f.h;
      const grp = el('g', { 'pointer-events': 'none' }, g);

      switch (f.kind) {
        case 'bed_double': case 'bed_single': {
          el('rect', { x, y, width: w, height: h, rx: 0.06, ...S }, grp);
          // Pillow band at the head, taken from the rotation the placer chose.
          const pd = Math.min(0.42, Math.min(w, h) * 0.3);
          const p2 = (f.rot === 0) ? { x, y: y + h - pd, width: w, height: pd }
            : (f.rot === 180) ? { x, y, width: w, height: pd }
              : (f.rot === 90) ? { x: x + w - pd, y, width: pd, height: h }
                : { x, y, width: pd, height: h };
          el('rect', { ...p2, rx: 0.05, fill: '#dde3ea', stroke: '#9aa3ae', 'stroke-width': 0.022 }, grp);
          break;
        }
        case 'wardrobe': case 'bookshelf': case 'shelving': case 'shoe_rack':
        case 'tv_unit': case 'pooja_unit': case 'desk': case 'counter': {
          el('rect', { x, y, width: w, height: h, ...S, fill: '#f1f3f6' }, grp);
          if (f.kind === 'wardrobe' || f.kind === 'shelving') {
            const n = Math.max(1, Math.round((w > h ? w : h) / 0.6));
            for (let i = 1; i < n; i++) {
              const t = i / n;
              if (w > h) el('line', { x1: x + w * t, y1: y, x2: x + w * t, y2: y + h, stroke: '#c2c8d0', 'stroke-width': 0.02 }, grp);
              else el('line', { x1: x, y1: y + h * t, x2: x + w, y2: y + h * t, stroke: '#c2c8d0', 'stroke-width': 0.02 }, grp);
            }
          }
          break;
        }
        case 'sofa': {
          el('rect', { x, y, width: w, height: h, rx: 0.09, ...S, fill: '#eef1f5' }, grp);
          const bd = Math.min(0.22, Math.min(w, h) * 0.3);
          const back = (f.rot === 0) ? { x, y: y + h - bd, width: w, height: bd }
            : (f.rot === 180) ? { x, y, width: w, height: bd }
              : (f.rot === 90) ? { x: x + w - bd, y, width: bd, height: h }
                : { x, y, width: bd, height: h };
          el('rect', { ...back, rx: 0.05, fill: '#d8dee6', stroke: '#9aa3ae', 'stroke-width': 0.02 }, grp);
          break;
        }
        case 'coffee_table':
          el('rect', { x, y, width: w, height: h, rx: 0.08, ...S }, grp); break;
        case 'dining_table': {
          el('rect', { x, y, width: w, height: h, rx: 0.09, ...S, fill: '#f4f1ea' }, grp);
          const seats = f.rot || 4; const perSide = Math.max(1, Math.round(seats / 2));
          const along = w >= h;
          for (let i = 0; i < perSide; i++) {
            const t = (i + 0.5) / perSide;
            const cs = 0.2;
            if (along) {
              el('circle', { cx: x + w * t, cy: y - 0.2, r: cs, ...S }, grp);
              el('circle', { cx: x + w * t, cy: y + h + 0.2, r: cs, ...S }, grp);
            } else {
              el('circle', { cx: x - 0.2, cy: y + h * t, r: cs, ...S }, grp);
              el('circle', { cx: x + w + 0.2, cy: y + h * t, r: cs, ...S }, grp);
            }
          }
          break;
        }
        case 'sink':
          el('rect', { x, y, width: w, height: h, rx: 0.05, ...S, fill: '#e4eef3' }, grp);
          el('circle', { cx: x + w / 2, cy: y + h / 2, r: Math.min(w, h) * 0.2, fill: 'none', stroke: '#8fa4b3', 'stroke-width': 0.024 }, grp);
          break;
        case 'hob':
          el('rect', { x, y, width: w, height: h, rx: 0.04, ...S, fill: '#e9e6e2' }, grp);
          for (const [dx, dy] of [[0.28, 0.3], [0.72, 0.3], [0.28, 0.72], [0.72, 0.72]]) {
            el('circle', { cx: x + w * dx, cy: y + h * dy, r: Math.min(w, h) * 0.13, fill: 'none', stroke: '#8b9098', 'stroke-width': 0.022 }, grp);
          }
          break;
        case 'fridge': case 'washer':
          el('rect', { x, y, width: w, height: h, rx: 0.04, ...S, fill: '#eff1f4' }, grp);
          el('circle', { cx: x + w / 2, cy: y + h / 2, r: Math.min(w, h) * 0.27, fill: 'none', stroke: '#a8afb8', 'stroke-width': 0.024 }, grp);
          break;
        case 'wc':
          el('rect', { x, y, width: w, height: h * 0.32, rx: 0.04, ...S }, grp);
          el('ellipse', { cx: x + w / 2, cy: y + h * 0.66, rx: w * 0.46, ry: h * 0.33, ...S }, grp);
          break;
        case 'basin':
          el('ellipse', { cx: x + w / 2, cy: y + h / 2, rx: w * 0.45, ry: h * 0.42, ...S, fill: '#e4eef3' }, grp);
          break;
        case 'shower':
          el('rect', { x, y, width: w, height: h, ...S, fill: '#e4eef3', 'stroke-dasharray': '0.1 0.07' }, grp);
          el('line', { x1: x, y1: y, x2: x + w, y2: y + h, stroke: '#a9bcc8', 'stroke-width': 0.024 }, grp);
          el('line', { x1: x + w, y1: y, x2: x, y2: y + h, stroke: '#a9bcc8', 'stroke-width': 0.024 }, grp);
          break;
        case 'car': {
          el('rect', { x, y, width: w, height: h, rx: Math.min(w, h) * 0.26, fill: '#dfe4ea', stroke: '#98a1ac', 'stroke-width': 0.03 }, grp);
          const inset = 0.18;
          el('rect', {
            x: x + (f.rot === 0 ? inset : w * 0.3), y: y + (f.rot === 0 ? h * 0.3 : inset),
            width: f.rot === 0 ? w - inset * 2 : w * 0.4,
            height: f.rot === 0 ? h * 0.4 : h - inset * 2,
            rx: 0.09, fill: '#c6cdd6',
          }, grp);
          break;
        }
        case 'stair': {
          // Treads plus the direction arrow, drawn across the short axis.
          const up = h >= w;
          const n = Math.max(3, Math.floor((up ? h : w) / 0.28));
          for (let i = 1; i < n; i++) {
            const t = i / n;
            if (up) el('line', { x1: x, y1: y + h * t, x2: x + w, y2: y + h * t, stroke: '#98a1ac', 'stroke-width': 0.022 }, grp);
            else el('line', { x1: x + w * t, y1: y, x2: x + w * t, y2: y + h, stroke: '#98a1ac', 'stroke-width': 0.022 }, grp);
          }
          // Central well line of a dog-legged flight.
          if (up) el('line', { x1: x + w / 2, y1: y + 0.1, x2: x + w / 2, y2: y + h - 0.1, stroke: '#6d7581', 'stroke-width': 0.03 }, grp);
          else el('line', { x1: x + 0.1, y1: y + h / 2, x2: x + w - 0.1, y2: y + h / 2, stroke: '#6d7581', 'stroke-width': 0.03 }, grp);
          const ar = el('path', {
            d: up
              ? `M ${x + w * 0.26} ${y + h - 0.22} L ${x + w * 0.26} ${y + 0.3} M ${x + w * 0.26 - 0.1} ${y + 0.42} L ${x + w * 0.26} ${y + 0.26} L ${x + w * 0.26 + 0.1} ${y + 0.42}`
              : `M ${x + 0.22} ${y + h * 0.26} L ${x + w - 0.3} ${y + h * 0.26} M ${x + w - 0.42} ${y + h * 0.26 - 0.1} L ${x + w - 0.26} ${y + h * 0.26} L ${x + w - 0.42} ${y + h * 0.26 + 0.1}`,
            fill: 'none', stroke: '#1f5fd0', 'stroke-width': 0.03,
          }, grp);
          ar.setAttribute('stroke-linecap', 'round');
          break;
        }
        default:
          el('rect', { x, y, width: w, height: h, ...S }, grp);
      }
    }
  }

  // ── labels ──────────────────────────────────────────────
  _drawLabels(g, rooms, fy) {
    for (const r of rooms) {
      const small = Math.min(r.w, r.h) < 1.35 || r.area < 2.6;
      const cx = r.x + r.w / 2;
      const cy = fy(r.y + r.h / 2);
      const scale = small ? 0.72 : 1;

      const name = el('text', {
        x: cx, y: cy - (small ? 0.02 : 0.1), class: 'room-label',
        'font-size': 0.3 * scale,
      }, g);
      name.textContent = r.label;

      if (!small || r.area >= 1.8) {
        const area = el('text', {
          x: cx, y: cy + 0.22 * scale, class: 'room-area', 'font-size': 0.22 * scale,
        }, g);
        area.textContent = `${r.area.toFixed(1)} m²`;
      }
      if (!small && r.area >= 4) {
        const dim = el('text', {
          x: cx, y: cy + 0.48, class: 'room-dim', 'font-size': 0.19,
        }, g);
        dim.textContent = `${fmt(r.w)} × ${fmt(r.h)}`;
      }
    }
  }

  // ── dimension strings along two sides of the envelope ───
  _drawDimensions(g, p, rooms, fy) {
    const env = p.envelope;
    const off = 0.75;
    const C = '#6d7581';
    const tick = (x, y, vertical) => el('line', {
      x1: vertical ? x - 0.09 : x, y1: vertical ? y : y - 0.09,
      x2: vertical ? x + 0.09 : x, y2: vertical ? y : y + 0.09,
      stroke: C, 'stroke-width': 0.022,
    }, g);

    // Unique vertical gridlines -> horizontal dimension chain below the plan.
    const xs = [...new Set(rooms.flatMap((r) => [+r.x.toFixed(2), +(r.x + r.w).toFixed(2)]))]
      .filter((x) => x >= env.x - 0.02 && x <= env.x + env.w + 0.02).sort((a, b) => a - b);
    const yBase = fy(env.y) + off;
    el('line', { x1: env.x, y1: yBase, x2: env.x + env.w, y2: yBase, stroke: C, 'stroke-width': 0.022 }, g);
    for (let i = 0; i < xs.length - 1; i++) {
      const a = xs[i]; const b = xs[i + 1];
      if (b - a < 0.45) continue;
      tick(a, yBase, false); tick(b, yBase, false);
      const t = el('text', { x: (a + b) / 2, y: yBase - 0.12, class: 'dim-text' }, g);
      t.textContent = fmt(b - a);
    }
    const tot = el('text', {
      x: env.x + env.w / 2, y: yBase + 0.5, class: 'dim-text', 'font-size': 0.24,
    }, g);
    tot.textContent = `${fmt(env.w)} m buildable width`;

    // Unique horizontal gridlines -> vertical dimension chain at the left.
    const ys = [...new Set(rooms.flatMap((r) => [+r.y.toFixed(2), +(r.y + r.h).toFixed(2)]))]
      .filter((y) => y >= env.y - 0.02 && y <= env.y + env.h + 0.02).sort((a, b) => a - b);
    const xBase = env.x - off;
    el('line', { x1: xBase, y1: fy(env.y), x2: xBase, y2: fy(env.y + env.h), stroke: C, 'stroke-width': 0.022 }, g);
    for (let i = 0; i < ys.length - 1; i++) {
      const a = ys[i]; const b = ys[i + 1];
      if (b - a < 0.45) continue;
      tick(xBase, fy(a), true); tick(xBase, fy(b), true);
      const t = el('text', {
        x: xBase - 0.14, y: fy((a + b) / 2), class: 'dim-text',
        transform: `rotate(-90 ${xBase - 0.14} ${fy((a + b) / 2)})`,
      }, g);
      t.textContent = fmt(b - a);
    }
  }

  // ── north arrow + scale bar ─────────────────────────────
  _drawCompassAndScale(g, p, fy, PAD) {
    const plot = p.plot;
    // The brief's "facing" is the direction the entrance looks towards; the
    // street is at the bottom of the sheet, so north rotates accordingly.
    const facing = p.requirements.facing || 'N';
    const rot = { N: 0, E: 90, S: 180, W: 270 }[facing] ?? 0;
    const cx = plot.x + plot.w + PAD * 0.5;
    const cy = fy(plot.y + plot.h) + 0.9;

    const c = el('g', { transform: `rotate(${rot} ${cx} ${cy})` }, g);
    el('circle', { cx, cy, r: 0.62, fill: 'none', stroke: '#8a929d', 'stroke-width': 0.03 }, c);
    el('path', {
      d: `M ${cx} ${cy - 0.52} L ${cx + 0.22} ${cy + 0.3} L ${cx} ${cy + 0.12} L ${cx - 0.22} ${cy + 0.3} Z`,
      fill: '#2b3038',
    }, c);
    const n = el('text', {
      x: cx, y: cy - 0.72, class: 'dim-text', 'font-size': 0.26, 'font-weight': 600,
    }, c);
    n.textContent = 'N';

    // Scale bar: 1 m ticks over 5 m.
    const sx = plot.x; const sy = fy(plot.y) + PAD * 0.62;
    for (let i = 0; i < 5; i++) {
      el('rect', {
        x: sx + i, y: sy, width: 1, height: 0.13,
        fill: i % 2 ? '#ffffff' : '#2b3038', stroke: '#2b3038', 'stroke-width': 0.018,
      }, g);
    }
    const lab = el('text', { x: sx + 2.5, y: sy + 0.42, class: 'dim-text' }, g);
    lab.textContent = '0        5 metres';
  }

  toSVGString() {
    const svg = this.host.querySelector('svg');
    if (!svg) return '';
    const clone = svg.cloneNode(true);
    clone.setAttribute('xmlns', NS);
    // Inline the class-based text styles so the exported file stands alone.
    const css = `
      .room-label{font:500 .30px Inter,sans-serif;text-anchor:middle;fill:#1d2229}
      .room-area{font:.22px "JetBrains Mono",monospace;text-anchor:middle;fill:#5b6470}
      .room-dim{font:.19px "JetBrains Mono",monospace;text-anchor:middle;fill:#8a929d}
      .dim-text{font:.20px "JetBrains Mono",monospace;text-anchor:middle;fill:#4a5361}
      .plot-label{font:500 .26px Inter,sans-serif;fill:#8a929d}`;
    const style = document.createElementNS(NS, 'style');
    style.textContent = css;
    clone.insertBefore(style, clone.firstChild);
    return new XMLSerializer().serializeToString(clone);
  }
}
