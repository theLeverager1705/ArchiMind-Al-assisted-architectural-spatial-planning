/**
 * 3D model view.
 *
 * Built from the identical dataset the 2D plan uses — the same room rectangles,
 * the same merged wall runs, the same door and window positions — so the model
 * cannot drift from the drawing. Walls are split around their openings and
 * capped with lintels and sills, which is why the windows read as real holes
 * rather than painted-on rectangles.
 *
 * Orbit control is implemented here rather than pulled from three/examples so
 * the page depends on exactly one script.
 */

const T = () => window.THREE;

const MAT = {
  wallExt: 0xe9e5dd, wallInt: 0xf2efe9, slab: 0xcfcac2, floorTint: 0xffffff,
  roof: 0xb9b3aa, parapet: 0xdedad2, glass: 0x8fc4e8, door: 0x9a6f4a,
  ground: 0xdfe4d8, paving: 0xc9ccc6, stair: 0xd7d3cb, car: 0x5b6470,
};

export class View3D {
  constructor(canvas) {
    this.canvas = canvas;
    this.ready = !!T();
    if (!this.ready) return;

    const THREE = T();
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0xeef0f2);
    this.scene.fog = new THREE.Fog(0xeef0f2, 60, 220);

    this.camera = new THREE.PerspectiveCamera(45, 1, 0.1, 600);
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;

    this._lights();
    this.building = new THREE.Group();
    this.scene.add(this.building);

    this.target = new THREE.Vector3(0, 1.5, 0);
    this.spherical = { radius: 32, phi: Math.PI * 0.33, theta: Math.PI * 0.25 };
    this.opts = { explode: false, roof: true, cutaway: false };
    this.plan = null;
    this.activeFloor = null;    // null = show all levels

    this._bindControls();
    this._resize();
    window.addEventListener('resize', () => this._resize());
    this._loop();
  }

  _lights() {
    const THREE = T();
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x9aa08f, 0.85));
    const sun = new THREE.DirectionalLight(0xfff4e0, 1.15);
    sun.position.set(18, 30, 14);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    const d = 34;
    Object.assign(sun.shadow.camera, { left: -d, right: d, top: d, bottom: -d, near: 1, far: 110 });
    this.scene.add(sun);
    const fill = new THREE.DirectionalLight(0xdde6ff, 0.32);
    fill.position.set(-16, 14, -12);
    this.scene.add(fill);
  }

  // ── orbit / pan / zoom ──────────────────────────────────
  _bindControls() {
    const c = this.canvas;
    let drag = null;

    c.addEventListener('contextmenu', (e) => e.preventDefault());
    c.addEventListener('mousedown', (e) => {
      drag = { x: e.clientX, y: e.clientY, button: e.button, ...this.spherical,
        tx: this.target.x, tz: this.target.z };
    });
    window.addEventListener('mousemove', (e) => {
      if (!drag) return;
      const dx = e.clientX - drag.x; const dy = e.clientY - drag.y;
      if (drag.button === 2 || e.shiftKey) {
        const k = this.spherical.radius * 0.0016;
        const s = Math.sin(this.spherical.theta); const co = Math.cos(this.spherical.theta);
        this.target.x = drag.tx - (dx * co - dy * s) * k;
        this.target.z = drag.tz - (dx * s + dy * co) * k;
      } else {
        this.spherical.theta = drag.theta - dx * 0.006;
        this.spherical.phi = Math.min(Math.PI * 0.492, Math.max(0.08, drag.phi - dy * 0.005));
      }
    });
    window.addEventListener('mouseup', () => { drag = null; });
    c.addEventListener('wheel', (e) => {
      e.preventDefault();
      this.spherical.radius = Math.min(180, Math.max(4,
        this.spherical.radius * (e.deltaY > 0 ? 1.1 : 1 / 1.1)));
    }, { passive: false });
  }

  _resize() {
    if (!this.ready) return;
    const r = this.canvas.getBoundingClientRect();
    const w = Math.max(1, r.width); const h = Math.max(1, r.height);
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  _loop() {
    if (!this.ready) return;
    requestAnimationFrame(() => this._loop());
    const s = this.spherical;
    this.camera.position.set(
      this.target.x + s.radius * Math.sin(s.phi) * Math.sin(s.theta),
      this.target.y + s.radius * Math.cos(s.phi),
      this.target.z + s.radius * Math.sin(s.phi) * Math.cos(s.theta),
    );
    this.camera.lookAt(this.target);
    this.renderer.render(this.scene, this.camera);
  }

  resetView() {
    if (!this.plan) return;
    const p = this.plan.plot;
    this.target.set(p.w / 2, 1.4, p.h / 2);
    this.spherical = {
      radius: Math.max(p.w, p.h) * 1.85 + 8,
      phi: Math.PI * 0.33, theta: Math.PI * 0.25,
    };
  }

  setOptions(o) { Object.assign(this.opts, o); this.build(); }
  setFloor(f) { this.activeFloor = f; this.build(); }

  setPlan(plan) {
    const fresh = !this.plan
      || this.plan.plot.w !== plan.plot.w || this.plan.plot.h !== plan.plot.h;
    this.plan = plan;
    this.build();
    if (fresh) this.resetView();
  }

  // ── geometry helpers ────────────────────────────────────
  _box(w, h, d, color, x, y, z, opacity = 1) {
    const THREE = T();
    const mat = new THREE.MeshLambertMaterial({
      color, transparent: opacity < 1, opacity,
    });
    const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
    m.position.set(x, y, z);
    m.castShadow = true;
    m.receiveShadow = true;
    this.building.add(m);
    return m;
  }

  build() {
    if (!this.ready || !this.plan) return;
    const THREE = T();
    while (this.building.children.length) {
      const c = this.building.children.pop();
      c.geometry?.dispose?.();
      c.material?.dispose?.();
    }

    const p = this.plan;
    const K = p.constants;
    const F2F = K.floor_to_floor;
    const WH = K.ceiling_height;
    const levels = p.levels.map((l) => l.level);
    const gap = this.opts.explode ? 2.6 : 0;

    this._ground(p);

    for (const lvl of levels) {
      if (this.activeFloor !== null && lvl !== this.activeFloor) continue;
      const base = lvl * F2F + lvl * gap;
      const rooms = p.rooms.filter((r) => r.floor === lvl);

      this._slab(p, rooms, base, K);
      this._floorTints(rooms, base);
      this._walls(p, lvl, base, WH, K);
      this._balconies(rooms, base, K);
      this._stairs(rooms, base, F2F, K);
      this._cars(p, lvl, base);
    }

    if (this.opts.roof && this.activeFloor === null) {
      this._roof(p, levels, F2F, gap, K);
    }
  }

  _ground(p) {
    const plot = p.plot;
    const pad = Math.max(plot.w, plot.h) * 0.85;
    this._box(plot.w + pad, 0.18, plot.h + pad, MAT.ground,
      plot.w / 2, -0.11, plot.h / 2);
    this._box(plot.w, 0.06, plot.h, MAT.paving, plot.w / 2, -0.005, plot.h / 2);
    // Street strip in front of the plot so the model is oriented at a glance.
    this._box(plot.w + pad * 0.6, 0.05, 4, 0xb9bdb6, plot.w / 2, 0.005, -2.2);
  }

  _slab(p, rooms, base, K) {
    const enclosed = rooms.filter((r) => r.type !== 'balcony' && r.type !== 'terrace');
    if (!enclosed.length) return;
    const e = p.envelope;
    this._box(e.w, K.slab, e.h, MAT.slab,
      e.x + e.w / 2, base - K.slab / 2, e.y + e.h / 2);
  }

  _floorTints(rooms, base) {
    for (const r of rooms) {
      if (r.type === 'terrace' || r.type === 'balcony') continue;
      const col = parseInt((r.color || '#eeeeee').slice(1), 16);
      this._box(Math.max(0.05, r.w - 0.1), 0.02, Math.max(0.05, r.h - 0.1), col,
        r.x + r.w / 2, base + 0.012, r.y + r.h / 2);
    }
  }

  /**
   * Extrude each merged wall run, splitting it around the openings on that wall
   * and capping doors with a lintel and windows with a sill plus header.
   */
  _walls(p, lvl, base, WH, K) {
    const walls = p.walls.filter((w) => w.floor === lvl);
    const ops = p.openings.filter((o) => o.floor === lvl);
    const DH = 2.10; const WSILL = 0.90; const WTOP = 0.90 + 1.35;

    for (const w of walls) {
      const vertical = w.orientation === 'v';
      const t = w.exterior ? K.wall_exterior : K.wall_interior;
      const col = w.exterior ? MAT.wallExt : MAT.wallInt;
      const a = vertical ? Math.min(w.y1, w.y2) : Math.min(w.x1, w.x2);
      const b = vertical ? Math.max(w.y1, w.y2) : Math.max(w.x1, w.x2);
      const fixed = vertical ? w.x1 : w.y1;

      // Openings that actually sit in this wall run.
      const here = ops.filter((o) => {
        if ((o.orientation === 'v') !== vertical) return false;
        const oFixed = vertical ? o.x : o.y;
        const oPos = vertical ? o.y : o.x;
        return Math.abs(oFixed - fixed) < 0.06
          && oPos - o.width / 2 > a - 0.06 && oPos + o.width / 2 < b + 0.06;
      }).map((o) => ({
        lo: (vertical ? o.y : o.x) - o.width / 2,
        hi: (vertical ? o.y : o.x) + o.width / 2,
        kind: o.kind,
      })).sort((x, y) => x.lo - y.lo);

      const put = (lo, hi, y0, y1, color = col) => {
        const len = hi - lo; const ht = y1 - y0;
        if (len < 0.02 || ht < 0.02) return;
        const cx = vertical ? fixed : (lo + hi) / 2;
        const cz = vertical ? (lo + hi) / 2 : fixed;
        const opacity = this.opts.cutaway ? 0.28 : 1;
        this._box(vertical ? t : len, ht, vertical ? len : t, color,
          cx, base + y0 + ht / 2, cz, opacity);
      };

      // Solid pieces between the openings.
      let cursor = a;
      for (const o of here) {
        put(cursor, Math.max(cursor, o.lo), 0, WH);
        // Head, and for a window also the sill below.
        if (o.kind === 'window') {
          put(o.lo, o.hi, 0, WSILL);
          put(o.lo, o.hi, WTOP, WH);
          if (!this.opts.cutaway) {
            const cx = vertical ? fixed : (o.lo + o.hi) / 2;
            const cz = vertical ? (o.lo + o.hi) / 2 : fixed;
            const len = o.hi - o.lo;
            this._box(vertical ? t * 0.22 : len, WTOP - WSILL, vertical ? len : t * 0.22,
              MAT.glass, cx, base + (WSILL + WTOP) / 2, cz, 0.42);
          }
        } else {
          put(o.lo, o.hi, DH, WH);
        }
        cursor = Math.max(cursor, o.hi);
      }
      put(cursor, b, 0, WH);
    }
  }

  _balconies(rooms, base, K) {
    for (const r of rooms) {
      if (r.type !== 'balcony') continue;
      this._box(r.w, 0.14, r.h, MAT.slab, r.x + r.w / 2, base + 0.07, r.y + r.h / 2);
      const ph = K.parapet; const t = 0.08;
      // Railing on all four sides; the one against the host room is harmless.
      this._box(r.w, ph, t, MAT.parapet, r.x + r.w / 2, base + ph / 2, r.y);
      this._box(r.w, ph, t, MAT.parapet, r.x + r.w / 2, base + ph / 2, r.y + r.h);
      this._box(t, ph, r.h, MAT.parapet, r.x, base + ph / 2, r.y + r.h / 2);
      this._box(t, ph, r.h, MAT.parapet, r.x + r.w, base + ph / 2, r.y + r.h / 2);
    }
  }

  _stairs(rooms, base, F2F, K) {
    for (const r of rooms) {
      if (r.type !== 'staircase') continue;
      const along = r.h >= r.w;
      const run = (along ? r.h : r.w) - 0.2;
      const n = Math.max(6, Math.round(F2F / 0.165));
      const rise = F2F / n;
      const tread = run / Math.ceil(n / 2);
      const half = Math.ceil(n / 2);

      for (let i = 0; i < half; i++) {
        const h = rise * (i + 1);
        if (along) {
          this._box(r.w / 2 - 0.12, h, tread, MAT.stair,
            r.x + r.w * 0.27, base + h / 2, r.y + 0.1 + tread * (i + 0.5));
        } else {
          this._box(tread, h, r.h / 2 - 0.12, MAT.stair,
            r.x + 0.1 + tread * (i + 0.5), base + h / 2, r.y + r.h * 0.27);
        }
      }
      // Upper flight returns on the other side of the well.
      for (let i = 0; i < n - half; i++) {
        const h = rise * (half + i + 1);
        if (along) {
          this._box(r.w / 2 - 0.12, h, tread, MAT.stair,
            r.x + r.w * 0.73, base + h / 2, r.y + r.h - 0.1 - tread * (i + 0.5));
        } else {
          this._box(tread, h, r.h / 2 - 0.12, MAT.stair,
            r.x + r.w - 0.1 - tread * (i + 0.5), base + h / 2, r.y + r.h * 0.73);
        }
      }
    }
  }

  _cars(p, lvl, base) {
    const ids = new Set(p.rooms.filter((r) => r.floor === lvl && r.type === 'parking')
      .map((r) => r.id));
    for (const f of p.furniture) {
      if (f.kind !== 'car' || !ids.has(f.room)) continue;
      this._box(f.w, 0.62, f.h, MAT.car, f.x + f.w / 2, base + 0.41, f.y + f.h / 2);
      const cw = f.rot === 0 ? f.w * 0.74 : f.w * 0.44;
      const cd = f.rot === 0 ? f.h * 0.44 : f.h * 0.74;
      this._box(cw, 0.42, cd, 0x8b93a0, f.x + f.w / 2, base + 0.83, f.y + f.h / 2, 0.85);
    }
  }

  _roof(p, levels, F2F, gap, K) {
    const top = Math.max(...levels);
    const base = top * F2F + top * gap + F2F;
    const e = p.envelope;
    const type = p.requirements.roof_type;

    if (type === 'sloped') {
      const THREE = T();
      const ridge = 1.6;
      const geo = new THREE.BufferGeometry();
      const x0 = e.x; const x1 = e.x + e.w; const z0 = e.y; const z1 = e.y + e.h;
      const zm = (z0 + z1) / 2;
      const eaves = 0.45;
      const v = new Float32Array([
        x0 - eaves, base, z0 - eaves, x1 + eaves, base, z0 - eaves, x1 + eaves, base + ridge, zm,
        x0 - eaves, base, z0 - eaves, x1 + eaves, base + ridge, zm, x0 - eaves, base + ridge, zm,
        x0 - eaves, base + ridge, zm, x1 + eaves, base + ridge, zm, x1 + eaves, base, z1 + eaves,
        x0 - eaves, base + ridge, zm, x1 + eaves, base, z1 + eaves, x0 - eaves, base, z1 + eaves,
      ]);
      geo.setAttribute('position', new THREE.BufferAttribute(v, 3));
      geo.computeVertexNormals();
      const mesh = new THREE.Mesh(geo, new THREE.MeshLambertMaterial({
        color: 0x9c6a52, side: THREE.DoubleSide,
      }));
      mesh.castShadow = true;
      this.building.add(mesh);
    } else {
      this._box(e.w, K.slab, e.h, MAT.roof, e.x + e.w / 2, base + K.slab / 2, e.y + e.h / 2);
      if (type === 'terrace') {
        const ph = K.parapet; const t = 0.12;
        const y = base + K.slab + ph / 2;
        this._box(e.w, ph, t, MAT.parapet, e.x + e.w / 2, y, e.y);
        this._box(e.w, ph, t, MAT.parapet, e.x + e.w / 2, y, e.y + e.h);
        this._box(t, ph, e.h, MAT.parapet, e.x, y, e.y + e.h / 2);
        this._box(t, ph, e.h, MAT.parapet, e.x + e.w, y, e.y + e.h / 2);
        // Stair head room over the core.
        const st = p.rooms.find((r) => r.type === 'staircase');
        if (st) {
          this._box(st.w, 2.4, st.h, MAT.wallExt,
            st.x + st.w / 2, base + K.slab + 1.2, st.y + st.h / 2);
          this._box(st.w + 0.3, K.slab, st.h + 0.3, MAT.roof,
            st.x + st.w / 2, base + K.slab + 2.4, st.y + st.h / 2);
        }
      }
    }
  }

  snapshot() {
    if (!this.ready) return null;
    this.renderer.render(this.scene, this.camera);
    return this.canvas.toDataURL('image/png');
  }
}
