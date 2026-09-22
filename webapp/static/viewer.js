/* 3D viewer: web-ifc tessellates the IFC in the browser, three.js draws it.

   Written directly against web-ifc and three.js (see CLAUDE.md: no code from
   IFCflow). Loaded on demand as an ES module when the 3D tab is opened; the
   import map in index.html resolves "three" and "web-ifc" to jsDelivr.

   Elements are joined to the audit by STEP id: web-ifc's expressID is the
   STEP id, and /api/jobs/<id>/elements maps it to GUID, class, name and
   storey. Issues are then joined by GUID, exactly as the report does. */

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import * as WebIFC from "web-ifc";

const WEB_IFC_BASE = "https://cdn.jsdelivr.net/npm/web-ifc@0.0.78/";
const SEV_RANK = { error: 0, warning: 1, info: 2 };

let apiPromise = null;
function ifcApi() {
  if (!apiPromise) {
    apiPromise = (async () => {
      const api = new WebIFC.IfcAPI();
      api.SetWasmPath(WEB_IFC_BASE, true);
      // Single-threaded: the multi-threaded build needs cross-origin isolation.
      await api.Init(undefined, true);
      return api;
    })();
  }
  return apiPromise;
}

function cssColor(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return new THREE.Color(v || fallback);
}

export class Viewer {
  constructor(container, { onSelect } = {}) {
    this.container = container;
    this.onSelect = onSelect || (() => {});
    this.elements = new Map();      // expressID -> record
    this.byGuid = new Map();        // guid -> [record]
    this.selected = null;
    this.colourByIssues = true;
    this.xray = false;
    this.isolated = null;           // Set of expressIDs, or null
    this.sectionAt = 1;             // 0..1 of model height; 1 = off

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.localClippingEnabled = true;
    container.appendChild(renderer.domElement);
    this.renderer = renderer;

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(45, 1, 0.01, 10000);
    this.camera.position.set(20, 20, 20);
    this.controls = new OrbitControls(this.camera, renderer.domElement);
    this.controls.enableDamping = false;
    this.controls.addEventListener("change", () => this.render());

    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8a80, 2.2));
    const sun = new THREE.DirectionalLight(0xffffff, 1.4);
    sun.position.set(1, 2, 1.5);
    this.scene.add(sun);

    this.group = new THREE.Group();
    this.scene.add(this.group);
    this.clip = new THREE.Plane(new THREE.Vector3(0, -1, 0), 0);
    this.box = new THREE.Box3();

    this._resize = () => {
      const w = container.clientWidth || 1, h = container.clientHeight || 1;
      renderer.setSize(w, h, false);
      this.camera.aspect = w / h;
      this.camera.updateProjectionMatrix();
      this.render();
    };
    this._ro = new ResizeObserver(this._resize);
    this._ro.observe(container);

    // Click to pick; a drag (orbit) is not a click.
    let down = null;
    renderer.domElement.addEventListener("pointerdown", (e) => {
      down = { x: e.clientX, y: e.clientY };
    });
    renderer.domElement.addEventListener("pointerup", (e) => {
      if (!down || Math.hypot(e.clientX - down.x, e.clientY - down.y) > 4) return;
      this._pick(e);
    });

    this.refreshTheme();
    this._resize();
  }

  refreshTheme() {
    this.colors = {
      error: cssColor("--sev-error", "#d03b3b"),
      warning: cssColor("--sev-warning", "#fab219"),
      info: cssColor("--sev-info", "#898781"),
      clean: cssColor("--v3d-clean", "#e4e2db"),
      selected: cssColor("--accent", "#2a78d6"),
    };
    this.scene.background = cssColor("--plane", "#f9f9f7");
    if (this.elements.size) this._applyStyles();
    this.render();
  }

  render() {
    this.renderer.render(this.scene, this.camera);
  }

  /** Load the model at `url`. `elements` comes from /api/jobs/<id>/elements,
      `issues` from the audit result. */
  async load(url, elements, issues, onProgress = () => {}) {
    onProgress("Loading the geometry engine…");
    const api = await ifcApi();

    onProgress("Downloading the model…");
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Could not download the model (${res.status})`);
    const data = new Uint8Array(await res.arrayBuffer());

    const info = new Map(elements.map((e) => [e.id, e]));
    const issuesByGuid = new Map();
    for (const issue of issues) {
      for (const ref of issue.elements || []) {
        if (!ref.guid) continue;
        if (!issuesByGuid.has(ref.guid)) issuesByGuid.set(ref.guid, []);
        issuesByGuid.get(ref.guid).push(issue);
      }
    }

    onProgress("Building 3D geometry…");
    const modelID = api.OpenModel(data, { COORDINATE_TO_ORIGIN: true });
    try {
      const matrix = new THREE.Matrix4();
      api.StreamAllMeshes(modelID, (flat) => {
        const id = flat.expressID;
        let rec = this.elements.get(id);
        if (!rec) {
          const meta = info.get(id) || {};
          const found = (meta.guid && issuesByGuid.get(meta.guid)) || [];
          rec = {
            id, guid: meta.guid || null, cls: meta.cls || "IfcProduct",
            name: meta.name || null, storey: meta.storey || null,
            issues: found, meshes: [],
            severity: found.reduce((best, i) =>
              best === null || SEV_RANK[i.severity] < SEV_RANK[best] ? i.severity : best,
            null),
          };
          this.elements.set(id, rec);
          if (rec.guid) {
            if (!this.byGuid.has(rec.guid)) this.byGuid.set(rec.guid, []);
            this.byGuid.get(rec.guid).push(rec);
          }
        }
        const placed = flat.geometries;
        for (let i = 0; i < placed.size(); i++) {
          const pg = placed.get(i);
          const geom = api.GetGeometry(modelID, pg.geometryExpressID);
          const verts = api.GetVertexArray(geom.GetVertexData(), geom.GetVertexDataSize());
          const index = api.GetIndexArray(geom.GetIndexData(), geom.GetIndexDataSize());
          geom.delete();
          if (!index.length) continue;

          // web-ifc interleaves position (3) and normal (3).
          const buffer = new THREE.InterleavedBuffer(new Float32Array(verts), 6);
          const g = new THREE.BufferGeometry();
          g.setAttribute("position", new THREE.InterleavedBufferAttribute(buffer, 3, 0));
          g.setAttribute("normal", new THREE.InterleavedBufferAttribute(buffer, 3, 3));
          g.setIndex(new THREE.BufferAttribute(new Uint32Array(index), 1));

          const c = pg.color;
          const mat = new THREE.MeshLambertMaterial({
            color: new THREE.Color(c.x, c.y, c.z), side: THREE.DoubleSide,
            transparent: c.w < 1, opacity: c.w, clippingPlanes: [this.clip],
          });
          const mesh = new THREE.Mesh(g, mat);
          matrix.fromArray(pg.flatTransformation);
          mesh.applyMatrix4(matrix);
          mesh.userData = { id, color: mat.color.clone(), opacity: c.w };
          rec.meshes.push(mesh);
          this.group.add(mesh);
        }
      }, true);
    } finally {
      api.CloseModel(modelID);
    }

    this.box.setFromObject(this.group);
    this._applyStyles();
    this.setSection(this.sectionAt);
    this.fit();
    onProgress("");
    return this.stats();
  }

  stats() {
    let flagged = 0;
    for (const r of this.elements.values()) if (r.severity) flagged++;
    return { elements: this.elements.size, flagged };
  }

  _applyStyles() {
    for (const rec of this.elements.values()) {
      const hidden = this.isolated && !this.isolated.has(rec.id);
      const isSel = this.selected && this.selected.id === rec.id;
      for (const mesh of rec.meshes) {
        const m = mesh.material;
        mesh.visible = !hidden;
        if (isSel) {
          m.color.copy(this.colors.selected);
        } else if (this.colourByIssues) {
          m.color.copy(rec.severity ? this.colors[rec.severity] : this.colors.clean);
        } else {
          m.color.copy(mesh.userData.color);
        }
        // X-ray fades what is fine so the problems stand out.
        const fade = this.xray && !isSel && !(this.colourByIssues && rec.severity);
        m.opacity = fade ? 0.12 : mesh.userData.opacity;
        m.transparent = fade || mesh.userData.opacity < 1;
        m.depthWrite = !fade;
        m.needsUpdate = true;
      }
    }
    this.render();
  }

  _pick(e) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1);
    const ray = new THREE.Raycaster();
    ray.setFromCamera(ndc, this.camera);
    const hits = ray.intersectObjects(this.group.children.filter((m) => m.visible), false)
      .filter((h) => this.sectionAt >= 1 || this.clip.distanceToPoint(h.point) >= 0)
      .filter((h) => !this.xray || h.object.material.opacity > 0.5);
    const rec = hits.length ? this.elements.get(hits[0].object.userData.id) : null;
    this.select(rec ? rec.id : null, { fly: false });
  }

  /** Select by expressID (null clears). */
  select(id, { fly = true } = {}) {
    this.selected = id === null ? null : this.elements.get(id) || null;
    this._applyStyles();
    if (this.selected && fly) this.fit(this.selected.meshes);
    this.onSelect(this.selected);
    return this.selected;
  }

  /** Select the elements behind a GUID. Returns false when it has no geometry. */
  selectGuid(guid) {
    const recs = this.byGuid.get(guid);
    if (!recs || !recs.length) { this.select(null); return false; }
    this.select(recs[0].id);
    return true;
  }

  fit(meshes) {
    const box = new THREE.Box3();
    const list = meshes || this.group.children.filter((m) => m.visible);
    for (const m of list) box.expandByObject(m);
    if (box.isEmpty()) return;
    const size = box.getSize(new THREE.Vector3()).length() || 1;
    const center = box.getCenter(new THREE.Vector3());
    const dir = new THREE.Vector3(1, 0.8, 1.2).normalize();
    const dist = size / (2 * Math.tan((this.camera.fov * Math.PI) / 360)) * 1.1;
    this.camera.near = Math.max(size / 1000, 0.001);
    this.camera.far = size * 100 + dist;
    this.camera.updateProjectionMatrix();
    this.camera.position.copy(center).addScaledVector(dir, dist);
    this.controls.target.copy(center);
    this.controls.update();
    this.render();
  }

  setColourByIssues(on) { this.colourByIssues = on; this._applyStyles(); }
  setXray(on) { this.xray = on; this._applyStyles(); }

  isolateSelection() {
    if (!this.selected) return false;
    this.isolated = new Set([this.selected.id]);
    this._applyStyles();
    this.fit(this.selected.meshes);
    return true;
  }

  isolateFlagged() {
    this.isolated = new Set([...this.elements.values()]
      .filter((r) => r.severity).map((r) => r.id));
    this._applyStyles();
    this.fit();
  }

  showAll() { this.isolated = null; this._applyStyles(); this.fit(); }

  /** Horizontal section. t in 0..1 of the model's height; 1 turns it off. */
  setSection(t) {
    this.sectionAt = t;
    if (this.box.isEmpty() || t >= 1) {
      this.clip.constant = Infinity;
    } else {
      this.clip.constant = this.box.min.y + (this.box.max.y - this.box.min.y) * t;
    }
    this.render();
  }

  dispose() {
    this._ro.disconnect();
    this.controls.dispose();
    for (const m of this.group.children) { m.geometry.dispose(); m.material.dispose(); }
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}
