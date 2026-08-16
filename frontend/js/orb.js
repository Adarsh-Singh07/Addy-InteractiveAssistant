const stage = document.getElementById('orb-stage');
const fallback = document.getElementById('orb-fallback');
const errorBanner = document.getElementById('orb-error');

function showFallback(message) {
  if (fallback) fallback.style.display = 'block';
  if (errorBanner && message) {
    errorBanner.textContent = message;
    errorBanner.hidden = false;
  }
  if (window.console) console.warn('[Addy Orb]', message);
}

async function boot() {
  if (!stage) return;

  let THREE, OrbitControls;
  try {
    THREE = await import('three');
    ({ OrbitControls } = await import('three/addons/controls/OrbitControls.js'));
  } catch (err) {
    showFallback('3D core unavailable — needs internet to load Three.js. Showing static core.');
    return;
  }

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
  } catch (err) {
    showFallback('WebGL is disabled in this browser. Showing static core.');
    return;
  }

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
  camera.position.set(0, 0.35, 6.2);

  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.6));
  renderer.setClearColor(0x000000, 0);
  stage.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.06;
  controls.enablePan = false;
  controls.minDistance = 3.3;
  controls.maxDistance = 11;
  controls.rotateSpeed = 0.55;
  controls.zoomSpeed = 0.9;

  const orb = new THREE.Group();
  scene.add(orb);
  const materials = [];
  let palette = { bright: 0x00e5ff, mid: 0x087f9c, dim: 0x073b52, hot: 0xd8fbff };

  const lineMaterial = (color, opacity) => {
    const material = new THREE.LineBasicMaterial({ color, transparent: true, opacity, blending: THREE.AdditiveBlending, depthWrite: false });
    materials.push(material);
    return material;
  };
  const ringGeometry = (radius, latitude, segments = 72) => {
    const points = [];
    const r = radius * Math.cos(latitude);
    const y = radius * Math.sin(latitude);
    for (let i = 0; i <= segments; i++) {
      const a = i / segments * Math.PI * 2;
      points.push(new THREE.Vector3(r * Math.cos(a), y, r * Math.sin(a)));
    }
    return new THREE.BufferGeometry().setFromPoints(points);
  };
  const meridianGeometry = (radius, longitude, segments = 72) => {
    const points = [];
    for (let i = 0; i <= segments; i++) {
      const lat = i / segments * Math.PI - Math.PI / 2;
      points.push(new THREE.Vector3(radius * Math.cos(lat) * Math.cos(longitude), radius * Math.sin(lat), radius * Math.cos(lat) * Math.sin(longitude)));
    }
    return new THREE.BufferGeometry().setFromPoints(points);
  };
  const buildShell = (radius, group) => {
    for (let i = -10; i <= 10; i++) {
      const major = i % 4 === 0;
      group.add(new THREE.Line(ringGeometry(radius, i / 10 * Math.PI / 2 * 0.93), lineMaterial(major ? palette.mid : palette.dim, major ? 0.42 : 0.13)));
    }
    for (let i = 0; i < 16; i++) {
      const major = i % 4 === 0;
      group.add(new THREE.Line(meridianGeometry(radius, i / 16 * Math.PI * 2), lineMaterial(major ? palette.mid : palette.dim, major ? 0.45 : 0.12)));
    }
  };

  const outer = new THREE.Group();
  buildShell(1.88, outer);
  orb.add(outer);
  const inner = new THREE.Group();
  for (let i = 0; i < 6; i++) {
    const points = [];
    for (let j = 0; j <= 180; j++) {
      const t = j / 180;
      const lat = t * Math.PI - Math.PI / 2;
      const lon = t * (3.2 + i * 0.18) * Math.PI * 2 + i;
      points.push(new THREE.Vector3(0.82 * Math.cos(lat) * Math.cos(lon), 0.82 * Math.sin(lat), 0.82 * Math.cos(lat) * Math.sin(lon)));
    }
    inner.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), lineMaterial(palette.bright, 0.28 + i * 0.025)));
  }
  orb.add(inner);

  const coreWire = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.IcosahedronGeometry(0.31, 1)), lineMaterial(palette.hot, 0.9));
  orb.add(coreWire);
  const core = new THREE.Mesh(new THREE.SphereGeometry(0.19, 16, 16), new THREE.MeshBasicMaterial({ color: palette.hot, transparent: true, opacity: 0.22, blending: THREE.AdditiveBlending }));
  orb.add(core);

  const debris = [];
  const debrisGeometry = new THREE.IcosahedronGeometry(0.018, 0);
  for (let i = 0; i < 110; i++) {
    const mesh = new THREE.Mesh(debrisGeometry, new THREE.MeshBasicMaterial({ color: i % 5 === 0 ? palette.bright : palette.mid, transparent: true, opacity: 0.35 + Math.random() * 0.5, blending: THREE.AdditiveBlending }));
    mesh.userData = { radius: 1.3 + Math.random() * 2.1, speed: (0.08 + Math.random() * 0.22) * (Math.random() > 0.5 ? 1 : -1), phase: Math.random() * Math.PI * 2, tilt: (Math.random() - 0.5) * 1.2 };
    debris.push(mesh);
    orb.add(mesh);
  }

  const dustPositions = new Float32Array(850 * 3);
  for (let i = 0; i < 850; i++) {
    const radius = 1.0 + Math.pow(Math.random(), 0.55) * 3.5;
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    dustPositions[i * 3] = radius * Math.sin(phi) * Math.cos(theta);
    dustPositions[i * 3 + 1] = radius * Math.cos(phi);
    dustPositions[i * 3 + 2] = radius * Math.sin(phi) * Math.sin(theta);
  }
  const dustGeometry = new THREE.BufferGeometry();
  dustGeometry.setAttribute('position', new THREE.Float32BufferAttribute(dustPositions, 3));
  const dust = new THREE.Points(dustGeometry, new THREE.PointsMaterial({ color: palette.mid, size: 0.025, transparent: true, opacity: 0.45, blending: THREE.AdditiveBlending, depthWrite: false }));
  orb.add(dust);

  function updatePalette(character) {
    palette = character === 'nova'
      ? { bright: 0xb777ff, mid: 0x6e31a1, dim: 0x311553, hot: 0xf0dcff }
      : { bright: 0x00e5ff, mid: 0x087f9c, dim: 0x073b52, hot: 0xd8fbff };
    const values = [palette.bright, palette.mid, palette.dim, palette.hot];
    materials.forEach((material, index) => material.color.setHex(values[index % values.length]));
    core.material.color.setHex(palette.hot);
    dust.material.color.setHex(palette.mid);
    debris.forEach((mesh, index) => mesh.material.color.setHex(index % 5 === 0 ? palette.bright : palette.mid));
  }

  const stateLabel = document.getElementById('core-state-label');
  const linkLabel = document.getElementById('voice-link-label');
  const getVisual = () => (window.getAddyVisualState ? window.getAddyVisualState() : { state: 'idle', character: 'addy', playbackVolume: 0 });
  window.addEventListener('addy:statechange', (event) => updatePalette(event.detail.character));

  const rotateBy = (theta, phi) => {
    const offset = camera.position.clone().sub(controls.target);
    const spherical = new THREE.Spherical().setFromVector3(offset);
    spherical.theta -= theta;
    spherical.phi = THREE.MathUtils.clamp(spherical.phi - phi, 0.08, Math.PI - 0.08);
    offset.setFromSpherical(spherical);
    camera.position.copy(controls.target).add(offset);
    camera.lookAt(controls.target);
  };
  const zoomBy = (factor) => {
    const offset = camera.position.clone().sub(controls.target);
    offset.setLength(THREE.MathUtils.clamp(offset.length() * factor, controls.minDistance, controls.maxDistance));
    camera.position.copy(controls.target).add(offset);
  };
  const resetView = () => { camera.position.set(0, 0.35, 6.2); controls.target.set(0, 0, 0); controls.update(); };

  const video = document.getElementById('gesture-video');
  const overlay = document.getElementById('gesture-overlay');
  const preview = document.getElementById('gesture-preview');
  const gestureStatus = document.getElementById('gesture-status');
  const gestureError = document.getElementById('gesture-error');
  const gestureToggle = document.getElementById('gesture-toggle');
  let tracker = null;
  let cameraStream = null;
  let gestureRaf = 0;
  let lastVideoTime = -1;
  let handStates = new Map();
  let previousMode = 'idle';
  let previousGrab = null;
  let previousDistance = null;
  const distance = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);

  async function startGestures() {
    if (tracker) return;
    gestureError.hidden = true;
    gestureToggle.textContent = 'INITIALIZING…';
    try {
      cameraStream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480, facingMode: 'user' }, audio: false });
      video.srcObject = cameraStream;
      await video.play();
      const vision = await import('https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.35/+esm');
      const fileset = await vision.FilesetResolver.forVisionTasks('https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.35/wasm');
      const options = { baseOptions: { modelAssetPath: 'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task', delegate: 'GPU' }, runningMode: 'VIDEO', numHands: 2, minHandDetectionConfidence: 0.6, minHandPresenceConfidence: 0.6, minTrackingConfidence: 0.6 };
      try {
        tracker = await vision.HandLandmarker.createFromOptions(fileset, options);
      } catch (_) {
        tracker = await vision.HandLandmarker.createFromOptions(fileset, { ...options, baseOptions: { ...options.baseOptions, delegate: 'CPU' } });
      }
      preview.hidden = false;
      gestureToggle.textContent = 'GESTURES ON';
      gestureToggle.setAttribute('aria-pressed', 'true');
      gestureLoop();
    } catch (error) {
      stopGestures();
      gestureError.textContent = error?.name === 'NotAllowedError' ? 'CAMERA ACCESS DENIED' : 'TRACKING INIT FAILED';
      gestureError.hidden = false;
    }
  }
  function stopGestures() {
    cancelAnimationFrame(gestureRaf);
    tracker?.close(); tracker = null;
    cameraStream?.getTracks().forEach((track) => track.stop()); cameraStream = null;
    if (video) video.srcObject = null;
    preview.hidden = true;
    gestureToggle.textContent = 'GESTURES OFF'; gestureToggle.setAttribute('aria-pressed', 'false');
    handStates.clear(); previousMode = 'idle'; previousGrab = null; previousDistance = null;
    const context = overlay?.getContext('2d'); context?.clearRect(0, 0, overlay.width, overlay.height);
  }
  function processHands(landmarks) {
    const context = overlay.getContext('2d');
    context.clearRect(0, 0, overlay.width, overlay.height);

    const pinched = [];
    landmarks.forEach((landmark, index) => {
      const scale = distance(landmark[0], landmark[9]);
      const ratio = distance(landmark[4], landmark[8]) / Math.max(scale, 0.0001);
      const raw = { x: 1 - (landmark[4].x + landmark[8].x) / 2, y: (landmark[4].y + landmark[8].y) / 2 };
      const state = handStates.get(index) || { pinching: false, grab: { x: raw.x, y: raw.y } };
      if (state.pinching && ratio > 0.45) state.pinching = false;
      if (!state.pinching && ratio < 0.32) state.pinching = true;
      // Smooth the live point in place, but push a COPY into pinched so the
      // current vs previous delta is never comparing the same object.
      state.grab.x += (raw.x - state.grab.x) * 0.45;
      state.grab.y += (raw.y - state.grab.y) * 0.45;
      handStates.set(index, state);
      if (state.pinching) pinched.push({ x: state.grab.x, y: state.grab.y });
      // Draw the pinch indicator (always, even when not pinching)
      const a = landmark[4], b = landmark[8];
      context.strokeStyle = state.pinching ? '#d8fbff' : 'rgba(216,251,255,0.5)';
      context.beginPath();
      context.moveTo((1 - a.x) * overlay.width, a.y * overlay.height);
      context.lineTo((1 - b.x) * overlay.width, b.y * overlay.height);
      context.stroke();
    });

    const mode = pinched.length > 1 ? 'zoom' : pinched.length === 1 ? 'spin' : 'idle';
    if (mode !== previousMode) { previousGrab = null; previousDistance = null; previousMode = mode; }
    if (mode === 'spin') {
      if (previousGrab) rotateBy((pinched[0].x - previousGrab.x) * 5.0, (pinched[0].y - previousGrab.y) * 5.0);
      previousGrab = pinched[0] ? { x: pinched[0].x, y: pinched[0].y } : null;
    }
    if (mode === 'zoom') {
      const d = distance(pinched[0], pinched[1]);
      if (previousDistance) zoomBy(THREE.MathUtils.clamp(previousDistance / d, 0.85, 1.18));
      previousDistance = d;
    }
    gestureStatus.textContent = landmarks.length
      ? `${landmarks.length} HAND${landmarks.length > 1 ? 'S' : ''} · ${mode.toUpperCase()}`
      : 'SHOW HANDS';
  }
  // Only run the (expensive) model when the webcam actually has a new frame.
  function gestureLoop() {
    if (!tracker) return;
    gestureRaf = requestAnimationFrame(gestureLoop);
    if (video.readyState >= 2 && video.currentTime !== lastVideoTime) {
      lastVideoTime = video.currentTime;
      const result = tracker.detectForVideo(video, performance.now());
      if (result && result.landmarks) processHands(result.landmarks);
    }
  }

  gestureToggle?.addEventListener('click', () => tracker ? stopGestures() : startGestures());
  document.getElementById('orb-zoom-in')?.addEventListener('click', () => zoomBy(0.72));
  document.getElementById('orb-zoom-out')?.addEventListener('click', () => zoomBy(1.38));
  document.getElementById('orb-reset')?.addEventListener('click', resetView);
  window.addEventListener('keydown', (event) => {
    if (event.target.matches('input, select, textarea')) return;
    const key = event.key.toLowerCase();
    if (key === 'g') tracker ? stopGestures() : startGestures();
    if (key === 'r') resetView();
    if (event.key === '+' || event.key === '=') zoomBy(0.72);
    if (event.key === '-' || event.key === '_') zoomBy(1.38);
  });

  const clock = new THREE.Clock();
  function animate() {
    requestAnimationFrame(animate);
    const elapsed = clock.getElapsedTime();
    const visual = getVisual();
    updatePalette(visual.character);
    const activity = visual.state === 'listening' ? 0.22 + visual.playbackVolume * 2.5 : visual.state === 'speaking' ? 0.3 + visual.playbackVolume * 2.8 : visual.state === 'thinking' ? 0.35 : 0.08;
    outer.rotation.y += 0.0012 + activity * 0.004;
    outer.rotation.x = Math.sin(elapsed * 0.2) * 0.05;
    inner.rotation.y -= 0.003 + activity * 0.006;
    coreWire.rotation.x += 0.008; coreWire.rotation.y += 0.011;
    const pulse = 1 + Math.sin(elapsed * (visual.state === 'thinking' ? 2.8 : 1.2)) * activity * 0.34;
    core.scale.setScalar(pulse); coreWire.scale.setScalar(1 + activity * 0.45);
    debris.forEach((mesh) => { const u = mesh.userData; const a = elapsed * u.speed + u.phase; mesh.position.set(u.radius * Math.cos(a), Math.sin(a * 0.8) * u.radius * 0.25 * Math.sin(u.tilt), u.radius * Math.sin(a) * Math.cos(u.tilt)); mesh.rotation.x += 0.01; mesh.rotation.z += 0.008; });
    dust.rotation.y += 0.0003;
    stateLabel.textContent = (visual.state || 'idle').toUpperCase();
    linkLabel.textContent = visual.state === 'error' ? 'FAULT' : visual.state === 'speaking' ? 'TRANSMITTING' : 'SYNCED';
    controls.update();
    renderer.render(scene, camera);
  }
  function resize() {
    const width = stage.clientWidth || 360;
    const height = stage.clientHeight || 360;
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height, false);
  }
  new ResizeObserver(resize).observe(stage);
  resize();
  updatePalette('addy');
  if (fallback) fallback.style.display = 'none';
  animate();
  window.addyOrb = { rotateBy, zoomBy, zoomIn: () => zoomBy(0.72), zoomOut: () => zoomBy(1.38), resetView, stopGestures };
}

boot();
