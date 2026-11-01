import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

const COLORS = [0xa9f3d3, 0xffb28d];
const V = (x, y, z) => new THREE.Vector3(x, y, z);

function roundedBox(width, height, depth, radius = 0.1) {
  const shape = new THREE.Shape(), x = -width / 2, y = -depth / 2;
  shape.moveTo(x + radius, y); shape.lineTo(x + width - radius, y);
  shape.quadraticCurveTo(x + width, y, x + width, y + radius);
  shape.lineTo(x + width, y + depth - radius); shape.quadraticCurveTo(x + width, y + depth, x + width - radius, y + depth);
  shape.lineTo(x + radius, y + depth); shape.quadraticCurveTo(x, y + depth, x, y + depth - radius);
  shape.lineTo(x, y + radius); shape.quadraticCurveTo(x, y, x + radius, y);
  const geometry = new THREE.ExtrudeGeometry(shape, { depth: height, bevelEnabled: true, bevelSegments: 3, steps: 1, bevelSize: 0.035, bevelThickness: 0.035, curveSegments: 8 });
  geometry.rotateX(Math.PI / 2); geometry.translate(0, height / 2, 0);
  return geometry;
}

function drone(color) {
  const group = new THREE.Group(), body = new THREE.Group(); group.add(body);
  const shell = new THREE.MeshStandardMaterial({ color: 0xe7e9e7, roughness: 0.28, metalness: 0.35 });
  const dark = new THREE.MeshStandardMaterial({ color: 0x1b242b, roughness: 0.48, metalness: 0.7 });
  const motorMaterial = new THREE.MeshStandardMaterial({ color: 0x46545c, roughness: 0.4, metalness: 0.8 });
  const accent = new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 2.2 });
  const chassis = new THREE.Mesh(roundedBox(0.6, 0.18, 0.84, 0.16), shell);
  chassis.castShadow = true; body.add(chassis);
  const top = new THREE.Mesh(roundedBox(0.36, 0.02, 0.47, 0.08), dark); top.position.y = 0.03; body.add(top);
  for (let i = 0; i < 5; i++) {
    const vent = new THREE.Mesh(new THREE.BoxGeometry(0.26, 0.012, 0.014), motorMaterial);
    vent.position.set(0, 0.055, -0.12 + i * 0.053); body.add(vent);
  }
  const lens = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.07, 0.075, 16), dark);
  lens.rotation.x = Math.PI / 2; lens.position.set(0, -0.07, 0.46); body.add(lens);
  const glass = new THREE.Mesh(new THREE.CircleGeometry(0.048, 20), new THREE.MeshStandardMaterial({ color: 0x132d38, metalness: 0.95, roughness: 0.08 }));
  glass.position.set(0, -0.07, 0.5); body.add(glass);
  const props = [];
  for (const x of [-0.53, 0.53]) for (const z of [-0.53, 0.53]) {
    const arm = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.09, 0.73), dark);
    arm.position.set(x / 2, -0.08, z / 2); arm.rotation.y = x * z > 0 ? Math.PI / 4 : -Math.PI / 4; arm.castShadow = true; body.add(arm);
    const guard = new THREE.Mesh(new THREE.TorusGeometry(0.31, 0.027, 7, 48), dark);
    guard.rotation.x = Math.PI / 2; guard.position.set(x, 0, z); guard.castShadow = true; body.add(guard);
    const motor = new THREE.Mesh(new THREE.CylinderGeometry(0.075, 0.07, 0.17, 12), motorMaterial);
    motor.position.set(x, -0.055, z); body.add(motor);
    const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.027, 0.04, 0.18, 8), dark);
    leg.position.set(x, -0.22, z); body.add(leg);
    const prop = new THREE.Group(); prop.position.set(x, 0.05, z);
    const blade = new THREE.Mesh(new THREE.BoxGeometry(0.52, 0.012, 0.044), new THREE.MeshStandardMaterial({ color: 0xb6c5c4, metalness: 0.45, transparent: true, opacity: 0.7 }));
    prop.add(blade); body.add(prop); props.push(prop);
    const blur = new THREE.Mesh(new THREE.CircleGeometry(0.27, 32), new THREE.MeshBasicMaterial({ color: 0xd5efeb, transparent: true, opacity: 0.055, side: THREE.DoubleSide, depthWrite: false }));
    blur.rotation.x = -Math.PI / 2; blur.position.set(x, 0.055, z); body.add(blur);
    const light = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.035, 0.045), accent);
    light.position.set(x, -0.06, z + Math.sign(z) * 0.1); body.add(light);
  }
  const indicator = new THREE.Mesh(new THREE.BoxGeometry(0.25, 0.025, 0.035), accent);
  indicator.position.set(0, -0.07, -0.44); body.add(indicator);
  const underglow = new THREE.PointLight(color, 1.7, 3, 2); underglow.position.y = -0.25; body.add(underglow);
  const halo = new THREE.Mesh(new THREE.RingGeometry(0.37, 0.4, 64), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.5, side: THREE.DoubleSide, depthWrite: false }));
  halo.rotation.x = -Math.PI / 2; halo.position.y = 0.015;
  return { group, body, props, halo };
}

export class DanceScene {
  constructor(container, labelContainer) {
    this.container = container;
    this.labelContainer = labelContainer;
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0c131b);
    this.scene.fog = new THREE.FogExp2(0x0c131b, 0.027);
    this.camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
    this.camera.position.set(8.5, 6.5, 10);
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'high-performance' });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFShadowMap;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.2;
    this.renderer.domElement.setAttribute('aria-label', 'Interactive 3D visualization of two autonomous dancing drones. Drag to orbit, scroll to zoom.');
    this.renderer.domElement.setAttribute('role', 'img');
    container.prepend(this.renderer.domElement);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.target.set(0, 1.1, 0);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.05;
    this.controls.minDistance = 7; this.controls.maxDistance = 24;
    this.controls.maxPolarAngle = Math.PI / 2.08;
    this.controls.enablePan = false;
    this.view = 'orbit';
    this.cameraGoal = null;
    this.scene.add(new THREE.HemisphereLight(0xd6eafa, 0x1b2429, 2.4));
    const key = new THREE.DirectionalLight(0xf6eadb, 4.5); key.position.set(-3, 9, 5); key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048); key.shadow.camera.left = -8; key.shadow.camera.right = 8;
    key.shadow.camera.top = 8; key.shadow.camera.bottom = -8; key.shadow.normalBias = 0.03;
    this.scene.add(key);
    const rim = new THREE.DirectionalLight(0x8ab4e5, 3); rim.position.set(4, 5, -7); this.scene.add(rim);
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(200, 200), new THREE.MeshStandardMaterial({ color: 0x0c131a, roughness: 0.94, metalness: 0.1 }));
    floor.rotation.x = -Math.PI / 2; floor.position.y = -0.2; floor.receiveShadow = true; this.scene.add(floor);
    const stage = new THREE.Mesh(new THREE.CylinderGeometry(5.2, 5.3, 0.18, 128), new THREE.MeshStandardMaterial({ color: 0x1b2832, roughness: 0.66, metalness: 0.5 }));
    stage.position.y = -0.09; stage.receiveShadow = true; this.scene.add(stage);
    for (const radius of [1.5, 3, 4.5, 5.12]) {
      const ring = new THREE.Mesh(new THREE.RingGeometry(radius - (radius > 5 ? 0.018 : 0.006), radius + 0.006, 128), new THREE.MeshBasicMaterial({ color: radius > 5 ? 0x6c8c97 : 0x3a4b56, transparent: true, opacity: radius > 5 ? 0.55 : 0.4, side: THREE.DoubleSide }));
      ring.rotation.x = -Math.PI / 2; ring.position.y = 0.006; this.scene.add(ring);
    }
    const grid = new THREE.GridHelper(10, 20, 0x56707b, 0x34444f); grid.position.y = 0.008;
    grid.material.transparent = true; grid.material.opacity = 0.17; this.scene.add(grid);
    for (let i = 0; i < 96; i++) {
      const theta = i / 96 * Math.PI * 2;
      const tick = new THREE.Mesh(new THREE.BoxGeometry(0.012, 0.008, i % 8 === 0 ? 0.18 : 0.07), new THREE.MeshBasicMaterial({ color: i % 8 === 0 ? 0x92a9b1 : 0x4a626d }));
      tick.position.set(Math.sin(theta) * 5, 0.012, Math.cos(theta) * 5); tick.rotation.y = theta; this.scene.add(tick);
    }
    this.beatRing = new THREE.Mesh(new THREE.RingGeometry(4.95, 4.98, 128), new THREE.MeshBasicMaterial({ color: 0xb5f5dc, transparent: true, opacity: 0.1, side: THREE.DoubleSide, depthWrite: false }));
    this.beatRing.rotation.x = -Math.PI / 2; this.beatRing.position.y = 0.018; this.scene.add(this.beatRing);
    this.drones = COLORS.map(color => { const d = drone(color); this.scene.add(d.group, d.halo); return d; });
    this.trailPoints = [[], []]; this.trails = []; this.trailVisible = true;
    for (const color of COLORS) {
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.Float32BufferAttribute(new Float32Array(540 * 3), 3));
      geometry.setAttribute('color', new THREE.Float32BufferAttribute(new Float32Array(540 * 3), 3));
      geometry.setDrawRange(0, 0);
      const line = new THREE.Line(geometry, new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.68, vertexColors: true, depthWrite: false }));
      line.frustumCulled = false; this.scene.add(line); this.trails.push(line);
    }
    const connectionGeometry = new THREE.BufferGeometry().setFromPoints([V(0, 0, 0), V(0, 0, 0)]);
    this.connection = new THREE.Line(connectionGeometry, new THREE.LineDashedMaterial({ color: 0x8fa5aa, transparent: true, opacity: 0.2, dashSize: 0.08, gapSize: 0.13 }));
    this.connection.frustumCulled = false; this.scene.add(this.connection);
    this.composer = new EffectComposer(this.renderer);
    this.composer.addPass(new RenderPass(this.scene, this.camera));
    this.bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.3, 0.45, 1.25);
    this.composer.addPass(this.bloom); this.composer.addPass(new OutputPass());
    this.labels = COLORS.map((_, i) => {
      const label = document.createElement('div'); label.className = `drone-label drone-${i}`;
      label.innerHTML = `<span class="label-dot"></span>${i === 0 ? 'ARI' : 'SOL'}<span class="label-height">2.0 m</span>`;
      labelContainer.append(label); return label;
    });
    this.lastTrail = -1;
    this.resizeObserver = new ResizeObserver(() => this.resize()); this.resizeObserver.observe(container);
    this.resize();
    this.renderer.domElement.addEventListener('webglcontextlost', e => { e.preventDefault(); document.dispatchEvent(new CustomEvent('duet-render-error')); });
    this.controls.addEventListener('start', () => { this.cameraGoal = null; });
  }

  resize() {
    const w = this.container.clientWidth, h = this.container.clientHeight;
    this.camera.aspect = w / h; this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h); this.composer.setSize(w, h);
  }

  setView(view) {
    this.view = view;
    this.cameraGoal = view === 'top' ? V(0.01, 15, 0.01) : view === 'front' ? V(0, 5, 15) : V(8.5, 6.5, 10);
  }

  resetTrails() { this.trailPoints = [[], []]; this.lastTrail = -1; this.trails.forEach(t => t.geometry.setDrawRange(0, 0)); }

  render(engine, playing, dt) {
    if (this.cameraGoal) {
      this.camera.position.lerp(this.cameraGoal, 1 - Math.exp(-dt * 5));
      if (this.camera.position.distanceTo(this.cameraGoal) < 0.02) this.cameraGoal = null;
    }
    this.controls.update();
    const record = playing && engine.time - this.lastTrail > 0.055;
    engine.agents.forEach((agent, i) => {
      const d = this.drones[i];
      d.group.position.fromArray(agent.pos);
      d.body.rotation.x = THREE.MathUtils.damp(d.body.rotation.x, agent.vel[2] * 0.13, 5, dt);
      d.body.rotation.z = THREE.MathUtils.damp(d.body.rotation.z, -agent.vel[0] * 0.13, 5, dt);
      const partner = engine.agents[1 - i];
      const desiredYaw = Math.atan2(partner.pos[0] - agent.pos[0], partner.pos[2] - agent.pos[2]);
      const diff = Math.atan2(Math.sin(desiredYaw - d.body.rotation.y), Math.cos(desiredYaw - d.body.rotation.y));
      d.body.rotation.y += diff * Math.min(1, dt * 2);
      d.props.forEach((p, k) => { if (playing) p.rotation.y += dt * (k % 2 ? 73 : -73); });
      d.halo.position.set(agent.pos[0], 0.02, agent.pos[2]);
      d.halo.material.opacity = 0.28 + Math.max(0, 1 - engine.beat % 1) * 0.16;
      if (record) {
        const points = this.trailPoints[i]; points.push([...agent.pos]); if (points.length > 540) points.shift();
        const geometry = this.trails[i].geometry;
        const positions = geometry.attributes.position.array, colors = geometry.attributes.color.array;
        points.forEach((point, j) => {
          positions.set(point, j * 3);
          const fade = Math.pow(j / Math.max(1, points.length - 1), 1.6); colors.set([fade, fade, fade], j * 3);
        });
        geometry.attributes.position.needsUpdate = true; geometry.attributes.color.needsUpdate = true;
        geometry.setDrawRange(0, points.length);
      }
      this.trails[i].visible = this.trailVisible;
      const projected = V(agent.pos[0], agent.pos[1] + 0.65, agent.pos[2]).project(this.camera);
      const x = (projected.x * 0.5 + 0.5) * this.container.clientWidth;
      const y = (-projected.y * 0.5 + 0.5) * this.container.clientHeight;
      this.labels[i].style.transform = `translate(${x}px, ${y}px) translate(-50%, -100%)`;
      this.labels[i].style.opacity = projected.z < 1 && Math.abs(projected.x) < 0.95 && Math.abs(projected.y) < 0.95 ? 1 : 0;
      this.labels[i].querySelector('.label-height').textContent = `${agent.pos[1].toFixed(1)} m`;
    });
    if (record) this.lastTrail = engine.time;
    const coords = this.connection.geometry.attributes.position.array;
    coords.set(engine.agents[0].pos, 0); coords.set(engine.agents[1].pos, 3);
    this.connection.geometry.attributes.position.needsUpdate = true; this.connection.computeLineDistances();
    this.beatRing.material.opacity = 0.035 + Math.pow(1 - engine.beat % 1, 4) * 0.16;
    this.composer.render();
  }
}
