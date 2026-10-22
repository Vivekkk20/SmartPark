/**
 * SmartPark 3D Smart Parking Lot Viewer
 * High-performance Three.js interactive 3D visualization.
 * Supports:
 * - Distinct Zone A (Two-Wheeler: S01-S06) and Zone B (Four-Wheeler: S07-S12)
 * - Low-poly 3D car models for four-wheelers and motorcycle models for two-wheelers
 * - Real backend data binding via /api/status
 * - Touch & orbit controls, smooth zone focus, and 2D fallback
 */
(function () {
  'use strict';

  // ─── Guard ─────────────────────────────────────────────────────────────────
  if (typeof THREE === 'undefined') {
    showFallback('Three.js library unavailable – showing 2D view.');
    return;
  }

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ─── DOM refs ──────────────────────────────────────────────────────────────
  const container  = document.getElementById('viewer-3d');
  const loadingEl  = document.getElementById('viewer-loading');
  const fallbackEl = document.getElementById('viewer-fallback');
  const infoPanel  = document.getElementById('slot-info-panel');
  const sipCode    = document.getElementById('sip-code');
  const sipCat     = document.getElementById('sip-category');
  const sipStatus  = document.getElementById('sip-status');
  const sipVehicle = document.getElementById('sip-vehicle');
  const sipSince   = document.getElementById('sip-since');
  const sipAdv     = document.getElementById('sip-adv');
  const sipAdvRow  = document.getElementById('sip-adv-row');
  const sipExitRow = document.getElementById('sip-exit-row');

  const btnReset   = document.getElementById('btn-reset-cam');
  const btnCam2w   = document.getElementById('btn-cam-2w');
  const btnCam4w   = document.getElementById('btn-cam-4w');
  const btnTop     = document.getElementById('btn-top-cam');
  const btnToggle  = document.getElementById('btn-toggle-view');

  if (!container) return;

  // ─── Palette ───────────────────────────────────────────────────────────────
  const COL = {
    availFloor:   0x10b981, // Emerald green
    occFloor:     0xf97316, // Vibrant orange
    availEdge:    0x34d399,
    occEdge:      0xfb923c,
    selected:     0x22d3ee, // Bright cyan
    road:         0x141a29,
    roadMarking:  0xfacc15, // Golden yellow
    ground:       0x0a0f1d,
    curb:         0x252e45,
    carBody:      0x38bdf8,
    carRoof:      0x0f172a,
    bikeBody:     0x22d3ee,
    wheel:        0x111827,
    lightWarm:    0xfef08a,
    lightRed:     0xef4444,
  };

  // ─── State ─────────────────────────────────────────────────────────────────
  let slotData      = (typeof SLOTS_INIT !== 'undefined') ? SLOTS_INIT : [];
  let is3D          = true;
  let selectedMesh  = null;
  const slotMeshes  = {}; // slot_code -> Mesh
  const vehicleGroups = {}; // slot_code -> THREE.Group
  const slotPositions = {}; // slot_code -> { x, z, category }

  // ─── Scene & Renderer ──────────────────────────────────────────────────────
  const W = container.clientWidth || 700;
  const H = 360;

  const renderer = new THREE.WebGLRenderer({ antialias: !reducedMotion, alpha: true, powerPreference: "high-performance" });
  renderer.setSize(W, H);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = !reducedMotion;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  container.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0a101d);
  scene.fog = new THREE.FogExp2(0x0a101d, 0.016);

  // Camera
  const camera = new THREE.PerspectiveCamera(46, W / H, 0.1, 250);
  const CAM_VIEWS = {
    default: { theta: -0.25, phi: Math.PI / 3.4, radius: 36, target: { x: 0, y: 0, z: 0 } },
    two_wheeler: { theta: -0.55, phi: Math.PI / 3.2, radius: 22, target: { x: -8.5, y: 0, z: 0 } },
    four_wheeler: { theta: 0.15, phi: Math.PI / 3.2, radius: 24, target: { x: 8.5, y: 0, z: 0 } },
    top: { theta: 0, phi: 0.05, radius: 42, target: { x: 0, y: 0, z: 0 } },
  };

  let spherical = { ...CAM_VIEWS.default };
  let currentTarget = { ...CAM_VIEWS.default.target };

  function updateCamera() {
    camera.position.x = currentTarget.x + spherical.radius * Math.sin(spherical.phi) * Math.sin(spherical.theta);
    camera.position.y = currentTarget.y + spherical.radius * Math.cos(spherical.phi);
    camera.position.z = currentTarget.z + spherical.radius * Math.sin(spherical.phi) * Math.cos(spherical.theta);
    camera.lookAt(currentTarget.x, currentTarget.y, currentTarget.z);
  }

  // Lights
  const ambientLight = new THREE.AmbientLight(0x94a3b8, 0.65);
  scene.add(ambientLight);

  const sunLight = new THREE.DirectionalLight(0xffffff, 1.1);
  sunLight.position.set(16, 32, 14);
  sunLight.castShadow = !reducedMotion;
  sunLight.shadow.mapSize.set(1024, 1024);
  sunLight.shadow.camera.near = 10;
  sunLight.shadow.camera.far = 70;
  sunLight.shadow.camera.left = -25;
  sunLight.shadow.camera.right = 25;
  sunLight.shadow.camera.top = 25;
  sunLight.shadow.camera.bottom = -25;
  scene.add(sunLight);

  const cyanAccent = new THREE.DirectionalLight(0x22d3ee, 0.35);
  cyanAccent.position.set(-18, 12, -10);
  scene.add(cyanAccent);

  // ─── Orbit Controls ────────────────────────────────────────────────────────
  let isPointerDown = false;
  let lastX = 0, lastY = 0;
  let pointerDownX = 0, pointerDownY = 0;
  let isDragging = false;

  renderer.domElement.addEventListener('pointerdown', e => {
    isPointerDown = true;
    lastX = e.clientX;
    lastY = e.clientY;
    pointerDownX = e.clientX;
    pointerDownY = e.clientY;
    isDragging = false;
    renderer.domElement.setPointerCapture(e.pointerId);
  });

  renderer.domElement.addEventListener('pointermove', e => {
    if (Math.abs(e.clientX - pointerDownX) > 4 || Math.abs(e.clientY - pointerDownY) > 4) {
      isDragging = true;
    }
    if (!isPointerDown) return;
    const dx = e.clientX - lastX;
    const dy = e.clientY - lastY;
    lastX = e.clientX;
    lastY = e.clientY;
    spherical.theta -= dx * 0.007;
    spherical.phi = Math.max(0.12, Math.min(Math.PI / 2.05, spherical.phi + dy * 0.007));
    updateCamera();
  });

  renderer.domElement.addEventListener('pointerup', () => { isPointerDown = false; });

  renderer.domElement.addEventListener('wheel', e => {
    e.preventDefault();
    spherical.radius = Math.max(12, Math.min(60, spherical.radius + e.deltaY * 0.04));
    updateCamera();
  }, { passive: false });

  // Touch Support
  let lastTouchDist = null;
  renderer.domElement.addEventListener('touchstart', e => {
    if (e.touches.length === 1) { lastX = e.touches[0].clientX; lastY = e.touches[0].clientY; }
    if (e.touches.length === 2) {
      lastTouchDist = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY);
    }
  });

  renderer.domElement.addEventListener('touchmove', e => {
    e.preventDefault();
    if (e.touches.length === 1) {
      const dx = e.touches[0].clientX - lastX;
      const dy = e.touches[0].clientY - lastY;
      lastX = e.touches[0].clientX;
      lastY = e.touches[0].clientY;
      spherical.theta -= dx * 0.007;
      spherical.phi = Math.max(0.12, Math.min(Math.PI / 2.05, spherical.phi + dy * 0.007));
      updateCamera();
    }
    if (e.touches.length === 2 && lastTouchDist !== null) {
      const dist = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY);
      spherical.radius = Math.max(12, Math.min(60, spherical.radius - (dist - lastTouchDist) * 0.05));
      lastTouchDist = dist;
      updateCamera();
    }
  }, { passive: false });

  renderer.domElement.addEventListener('touchend', () => { lastTouchDist = null; });

  // ─── Camera Buttons ────────────────────────────────────────────────────────
  function transitionToView(targetView) {
    spherical.theta = targetView.theta;
    spherical.phi = targetView.phi;
    spherical.radius = targetView.radius;
    currentTarget = { ...targetView.target };
    updateCamera();
  }

  if (btnReset) btnReset.addEventListener('click', () => transitionToView(CAM_VIEWS.default));
  if (btnCam2w) btnCam2w.addEventListener('click', () => transitionToView(CAM_VIEWS.two_wheeler));
  if (btnCam4w) btnCam4w.addEventListener('click', () => transitionToView(CAM_VIEWS.four_wheeler));
  if (btnTop)   btnTop.addEventListener('click',   () => transitionToView(CAM_VIEWS.top));
  if (btnToggle) btnToggle.addEventListener('click', toggleView);

  // Expose global for dashboard category tabs
  window.smartPark3D = {
    focusZone: function (zone) {
      if (zone === 'two_wheeler') transitionToView(CAM_VIEWS.two_wheeler);
      else if (zone === 'four_wheeler') transitionToView(CAM_VIEWS.four_wheeler);
      else transitionToView(CAM_VIEWS.default);
    }
  };

  document.getElementById('slot-info-close')?.addEventListener('click', () => {
    infoPanel?.classList.remove('visible');
    if (selectedMesh) {
      selectedMesh.material.color.set(selectedMesh.userData.baseColor);
      selectedMesh = null;
    }
  });

  // ─── 3D Text Badge Sprite Generator ────────────────────────────────────────
  function createTextSprite(text, is2W) {
    const canvas = document.createElement('canvas');
    canvas.width = 128;
    canvas.height = 64;
    const ctx = canvas.getContext('2d');

    // Background pill
    ctx.fillStyle = is2W ? 'rgba(6, 78, 99, 0.85)' : 'rgba(30, 58, 138, 0.85)';
    ctx.roundRect(8, 12, 112, 40, 10);
    ctx.fill();

    ctx.strokeStyle = is2W ? '#22d3ee' : '#60a5fa';
    ctx.lineWidth = 3;
    ctx.stroke();

    // Text
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 22px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, 64, 32);

    const texture = new THREE.CanvasTexture(canvas);
    texture.minFilter = THREE.LinearFilter;
    const spriteMat = new THREE.SpriteMaterial({ map: texture, transparent: true });
    const sprite = new THREE.Sprite(spriteMat);
    sprite.scale.set(2.2, 1.1, 1);
    return sprite;
  }

  // ─── Vehicle 3D Models ─────────────────────────────────────────────────────
  // 1. Sleek Low-Poly Four-Wheeler Car
  function createCarModel(colorHex = COL.carBody) {
    const car = new THREE.Group();

    // Lower chassis
    const bodyGeo = new THREE.BoxGeometry(1.65, 0.52, 3.4);
    const bodyMat = new THREE.MeshLambertMaterial({ color: colorHex });
    const body = new THREE.Mesh(bodyGeo, bodyMat);
    body.position.y = 0.42;
    body.castShadow = true;
    car.add(body);

    // Cabin / Roof glass
    const roofGeo = new THREE.BoxGeometry(1.25, 0.42, 1.75);
    const roofMat = new THREE.MeshLambertMaterial({ color: 0x0f172a });
    const roof = new THREE.Mesh(roofGeo, roofMat);
    roof.position.set(0, 0.84, -0.2);
    roof.castShadow = true;
    car.add(roof);

    // Wheels
    const wheelGeo = new THREE.CylinderGeometry(0.24, 0.24, 0.2, 10);
    const wheelMat = new THREE.MeshLambertMaterial({ color: COL.wheel });
    const hubMat = new THREE.MeshBasicMaterial({ color: 0x94a3b8 });

    [[-0.88, -1.05], [0.88, -1.05], [-0.88, 1.05], [0.88, 1.05]].forEach(([wx, wz]) => {
      const wheel = new THREE.Mesh(wheelGeo, wheelMat);
      wheel.rotation.z = Math.PI / 2;
      wheel.position.set(wx, 0.24, wz);
      wheel.castShadow = true;
      car.add(wheel);

      const hub = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.1, 0.21, 6), hubMat);
      hub.rotation.z = Math.PI / 2;
      hub.position.set(wx, 0.24, wz);
      car.add(hub);
    });

    // Headlights (front facing +Z)
    const hlMat = new THREE.MeshBasicMaterial({ color: COL.lightWarm });
    const hlGeo = new THREE.BoxGeometry(0.26, 0.14, 0.05);
    [-0.55, 0.55].forEach(hx => {
      const hl = new THREE.Mesh(hlGeo, hlMat);
      hl.position.set(hx, 0.45, 1.71);
      car.add(hl);
    });

    // Taillights (rear facing -Z)
    const tlMat = new THREE.MeshBasicMaterial({ color: COL.lightRed });
    [-0.55, 0.55].forEach(tx => {
      const tl = new THREE.Mesh(hlGeo, tlMat);
      tl.position.set(tx, 0.48, -1.71);
      car.add(tl);
    });

    return car;
  }

  // 2. Sleek Low-Poly Two-Wheeler Motorcycle / Scooter
  function createMotorcycleModel(colorHex = COL.bikeBody) {
    const bike = new THREE.Group();

    // Frame / body
    const frameGeo = new THREE.BoxGeometry(0.42, 0.48, 1.7);
    const frameMat = new THREE.MeshLambertMaterial({ color: colorHex });
    const frame = new THREE.Mesh(frameGeo, frameMat);
    frame.position.y = 0.48;
    frame.castShadow = true;
    bike.add(frame);

    // Seat
    const seatGeo = new THREE.BoxGeometry(0.38, 0.14, 0.7);
    const seatMat = new THREE.MeshLambertMaterial({ color: 0x18181b });
    const seat = new THREE.Mesh(seatGeo, seatMat);
    seat.position.set(0, 0.76, -0.2);
    bike.add(seat);

    // Handlebars
    const barGeo = new THREE.BoxGeometry(0.85, 0.06, 0.06);
    const barMat = new THREE.MeshLambertMaterial({ color: 0x94a3b8 });
    const bar = new THREE.Mesh(barGeo, barMat);
    bar.position.set(0, 0.88, 0.55);
    bike.add(bar);

    // Front fork angled
    const forkGeo = new THREE.CylinderGeometry(0.04, 0.04, 0.65, 6);
    const fork = new THREE.Mesh(forkGeo, barMat);
    fork.rotation.x = -Math.PI / 10;
    fork.position.set(0, 0.5, 0.68);
    bike.add(fork);

    // Wheels (aligned along Z axis)
    const bikeWheelGeo = new THREE.CylinderGeometry(0.28, 0.28, 0.12, 12);
    const wheelMat = new THREE.MeshLambertMaterial({ color: COL.wheel });

    // Front wheel (+Z)
    const fw = new THREE.Mesh(bikeWheelGeo, wheelMat);
    fw.rotation.z = Math.PI / 2;
    fw.position.set(0, 0.28, 0.82);
    fw.castShadow = true;
    bike.add(fw);

    // Rear wheel (-Z)
    const rw = new THREE.Mesh(bikeWheelGeo, wheelMat);
    rw.rotation.z = Math.PI / 2;
    rw.position.set(0, 0.28, -0.75);
    rw.castShadow = true;
    bike.add(rw);

    // Headlight
    const hl = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.09, 0.08, 8), new THREE.MeshBasicMaterial({ color: COL.lightWarm }));
    hl.rotation.x = Math.PI / 2;
    hl.position.set(0, 0.78, 0.76);
    bike.add(hl);

    return bike;
  }

  // ─── Build Parking Lot Geometry ────────────────────────────────────────────
  function buildParkingLot() {
    // Total scene bounds
    const SCENE_W = 34;
    const SCENE_D = 22;

    // Ground plane
    const groundGeo = new THREE.PlaneGeometry(SCENE_W + 12, SCENE_D + 12);
    const groundMat = new THREE.MeshLambertMaterial({ color: COL.ground });
    const ground = new THREE.Mesh(groundGeo, groundMat);
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    scene.add(ground);

    // Central Asphalt Road (Runs along Z-axis through center)
    const roadW = 7.0;
    const roadGeo = new THREE.PlaneGeometry(roadW, SCENE_D);
    const roadMat = new THREE.MeshLambertMaterial({ color: COL.road });
    const road = new THREE.Mesh(roadGeo, roadMat);
    road.rotation.x = -Math.PI / 2;
    road.position.set(0, 0.015, 0);
    road.receiveShadow = true;
    scene.add(road);

    // Yellow dashed road center divider
    const dashMat = new THREE.LineDashedMaterial({ color: COL.roadMarking, dashSize: 0.8, gapSize: 0.6, linewidth: 2 });
    const dashPoints = [new THREE.Vector3(0, 0.03, -SCENE_D / 2 + 1), new THREE.Vector3(0, 0.03, SCENE_D / 2 - 1)];
    const dashGeo = new THREE.BufferGeometry().setFromPoints(dashPoints);
    const dashLine = new THREE.Line(dashGeo, dashMat);
    dashLine.computeLineDistances();
    scene.add(dashLine);

    // White outer road boundary lines
    [-roadW / 2 + 0.1, roadW / 2 - 0.1].forEach(rx => {
      const p = [new THREE.Vector3(rx, 0.03, -SCENE_D / 2), new THREE.Vector3(rx, 0.03, SCENE_D / 2)];
      const g = new THREE.BufferGeometry().setFromPoints(p);
      scene.add(new THREE.Line(g, new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.35 })));
    });

    // ── Zone A: Two-Wheeler (West / Left side: X < 0) ─────────────────────────
    // 6 slots: S01–S06 arranged in 3 columns x 2 rows
    // Narrower slots: Width 2.1, Depth 4.0
    const TW_SLOT_W = 2.2, TW_SLOT_D = 4.0;
    const TW_GAP_X  = 0.4, TW_GAP_Z  = 0.5;
    const TW_COLS   = 3;
    const TW_START_X = -roadW / 2 - (TW_COLS * (TW_SLOT_W + TW_GAP_X)) / 2 - 0.5;
    const TW_START_Z = -(TW_SLOT_D + TW_GAP_Z) / 2;

    // Zone A Ground Pad (Cyan tint)
    const pad2wGeo = new THREE.PlaneGeometry(TW_COLS * (TW_SLOT_W + TW_GAP_X) + 1.6, 2 * (TW_SLOT_D + TW_GAP_Z) + 1.2);
    const pad2wMat = new THREE.MeshLambertMaterial({ color: 0x112133 });
    const pad2w = new THREE.Mesh(pad2wGeo, pad2wMat);
    pad2w.rotation.x = -Math.PI / 2;
    pad2w.position.set(TW_START_X, 0.012, 0);
    pad2w.receiveShadow = true;
    scene.add(pad2w);

    // ── Zone B: Four-Wheeler (East / Right side: X > 0) ────────────────────────
    // 6 slots: S07–S12 arranged in 3 columns x 2 rows
    // Standard car slots: Width 3.4, Depth 5.8
    const FW_SLOT_W = 3.5, FW_SLOT_D = 5.8;
    const FW_GAP_X  = 0.5, FW_GAP_Z  = 0.6;
    const FW_COLS   = 3;
    const FW_START_X = roadW / 2 + (FW_COLS * (FW_SLOT_W + FW_GAP_X)) / 2 + 0.5;
    const FW_START_Z = -(FW_SLOT_D + FW_GAP_Z) / 2;

    // Zone B Ground Pad (Blue tint)
    const pad4wGeo = new THREE.PlaneGeometry(FW_COLS * (FW_SLOT_W + FW_GAP_X) + 1.8, 2 * (FW_SLOT_D + FW_GAP_Z) + 1.4);
    const pad4wMat = new THREE.MeshLambertMaterial({ color: 0x131f38 });
    const pad4w = new THREE.Mesh(pad4wGeo, pad4wMat);
    pad4w.rotation.x = -Math.PI / 2;
    pad4w.position.set(FW_START_X, 0.012, 0);
    pad4w.receiveShadow = true;
    scene.add(pad4w);

    // Zone Entrance Signage Poles
    buildZoneSign(-roadW / 2 - 1.2, 0, -SCENE_D / 2 + 2, 'ZONE A · 2-WHEELER', 0x22d3ee);
    buildZoneSign(roadW / 2 + 1.2,  0, -SCENE_D / 2 + 2, 'ZONE B · 4-WHEELER', 0x60a5fa);

    // ── Build Slots ──────────────────────────────────────────────────────────
    slotData.forEach((slot, idx) => {
      const is2W = (slot.category === 'two_wheeler') || (idx < 6);
      let posX = 0, posZ = 0, slotW = 0, slotD = 0;

      if (is2W) {
        // Zone A: index 0..5
        const col = idx % TW_COLS;
        const row = Math.floor(idx / TW_COLS);
        slotW = TW_SLOT_W;
        slotD = TW_SLOT_D;
        posX = (TW_START_X - (TW_COLS - 1) * (TW_SLOT_W + TW_GAP_X) / 2) + col * (TW_SLOT_W + TW_GAP_X);
        posZ = (row === 0) ? -slotD / 2 - TW_GAP_Z / 2 : slotD / 2 + TW_GAP_Z / 2;
      } else {
        // Zone B: index 6..11
        const relIdx = idx - 6;
        const col = relIdx % FW_COLS;
        const row = Math.floor(relIdx / FW_COLS);
        slotW = FW_SLOT_W;
        slotD = FW_SLOT_D;
        posX = (FW_START_X - (FW_COLS - 1) * (FW_SLOT_W + FW_GAP_X) / 2) + col * (FW_SLOT_W + FW_GAP_X);
        posZ = (row === 0) ? -slotD / 2 - FW_GAP_Z / 2 : slotD / 2 + FW_GAP_Z / 2;
      }

      slotPositions[slot.slot_code] = { x: posX, z: posZ, category: slot.category || (is2W ? 'two_wheeler' : 'four_wheeler') };

      const isOccupied = slot.status === 'occupied';

      // Floor Tile Mesh
      const floorGeo = new THREE.BoxGeometry(slotW - 0.12, 0.08, slotD - 0.12);
      const baseColor = isOccupied ? COL.occFloor : COL.availFloor;
      const floorMat = new THREE.MeshLambertMaterial({
        color: baseColor,
        transparent: true,
        opacity: isOccupied ? 0.7 : 0.45,
      });
      const floorMesh = new THREE.Mesh(floorGeo, floorMat);
      floorMesh.position.set(posX, 0.045, posZ);
      floorMesh.receiveShadow = true;
      floorMesh.userData = {
        slotCode: slot.slot_code,
        category: slot.category || (is2W ? 'two_wheeler' : 'four_wheeler'),
        baseColor: baseColor,
        isOccupied: isOccupied,
        slotInfo: slot,
      };
      scene.add(floorMesh);
      slotMeshes[slot.slot_code] = floorMesh;

      // Neon Border Outline
      const edgeGeo = new THREE.EdgesGeometry(floorGeo);
      const edgeMat = new THREE.LineBasicMaterial({
        color: isOccupied ? COL.occEdge : (is2W ? 0x22d3ee : COL.availEdge),
        transparent: true,
        opacity: 0.85,
      });
      const edgeLines = new THREE.LineSegments(edgeGeo, edgeMat);
      edgeLines.position.copy(floorMesh.position);
      scene.add(edgeLines);

      // 3D Text Badge Sprite floating over the slot
      const sprite = createTextSprite(slot.slot_code, is2W);
      const labelZ = (posZ < 0) ? posZ - slotD / 2 + 0.5 : posZ + slotD / 2 - 0.5;
      sprite.position.set(posX, 0.9, labelZ);
      scene.add(sprite);

      // If occupied, attach 3D model
      if (isOccupied) {
        addVehicleModel(slot.slot_code, is2W, posX, posZ);
      }
    });

    // Outer Perimeter Curbs
    buildPerimeters(SCENE_W, SCENE_D);
  }

  function addVehicleModel(slotCode, is2W, x, z) {
    if (vehicleGroups[slotCode]) {
      scene.remove(vehicleGroups[slotCode]);
      delete vehicleGroups[slotCode];
    }
    const model = is2W ? createMotorcycleModel() : createCarModel();
    // Rotate to face driving lane
    if (x < 0) {
      // Zone A (West): Vehicles face East toward center lane
      model.rotation.y = Math.PI / 2;
    } else {
      // Zone B (East): Vehicles face West toward center lane
      model.rotation.y = -Math.PI / 2;
    }
    model.position.set(x, 0.08, z);
    scene.add(model);
    vehicleGroups[slotCode] = model;
  }

  function removeVehicleModel(slotCode) {
    if (vehicleGroups[slotCode]) {
      scene.remove(vehicleGroups[slotCode]);
      delete vehicleGroups[slotCode];
    }
  }

  function buildZoneSign(x, y, z, text, colHex) {
    const postGeo = new THREE.CylinderGeometry(0.08, 0.08, 2.8, 8);
    const postMat = new THREE.MeshLambertMaterial({ color: 0x334155 });
    const post = new THREE.Mesh(postGeo, postMat);
    post.position.set(x, 1.4, z);
    post.castShadow = true;
    scene.add(post);

    const signGeo = new THREE.BoxGeometry(2.4, 0.6, 0.1);
    const signMat = new THREE.MeshLambertMaterial({ color: 0x0f172a });
    const sign = new THREE.Mesh(signGeo, signMat);
    sign.position.set(x, 2.5, z);
    sign.castShadow = true;
    scene.add(sign);

    const light = new THREE.PointLight(colHex, 0.8, 6);
    light.position.set(x, 2.7, z + 0.3);
    scene.add(light);
  }

  function buildPerimeters(w, d) {
    const curbMat = new THREE.MeshLambertMaterial({ color: COL.curb });
    const curbH = 0.22, curbT = 0.3;
    [
      [0, 0, d / 2 + curbT / 2, w + curbT * 2, curbT],
      [0, 0, -d / 2 - curbT / 2, w + curbT * 2, curbT],
      [w / 2 + curbT / 2, 0, 0, curbT, d],
      [-w / 2 - curbT / 2, 0, 0, curbT, d],
    ].forEach(([x, y, z, cw, cd]) => {
      const geo = new THREE.BoxGeometry(cw, curbH, cd);
      const mesh = new THREE.Mesh(geo, curbMat);
      mesh.position.set(x, curbH / 2, z);
      scene.add(mesh);
    });
  }

  // ─── Raycasting Selection ──────────────────────────────────────────────────
  const raycaster = new THREE.Raycaster();
  const mouse = new THREE.Vector2();

  renderer.domElement.addEventListener('pointerup', e => {
    if (isDragging) return;
    const rect = renderer.domElement.getBoundingClientRect();
    mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

    raycaster.setFromCamera(mouse, camera);
    const meshes = Object.values(slotMeshes);
    const hits = raycaster.intersectObjects(meshes);

    if (hits.length > 0) {
      selectSlot(hits[0].object);
    }
  });

  function selectSlot(mesh) {
    if (selectedMesh && selectedMesh !== mesh) {
      selectedMesh.material.color.set(selectedMesh.userData.baseColor);
    }
    selectedMesh = mesh;
    mesh.material.color.set(COL.selected);

    const info = mesh.userData.slotInfo;
    const isOccupied = info.status === 'occupied';
    const is2W = info.category === 'two_wheeler' || (mesh.userData.category === 'two_wheeler');

    sipCode.textContent = info.slot_code;
    if (sipCat) {
      sipCat.textContent = is2W ? '🏍 Two-Wheeler (Zone A)' : '🚗 Four-Wheeler (Zone B)';
      sipCat.style.color = is2W ? 'var(--cyan)' : 'var(--blue)';
    }

    sipStatus.textContent = isOccupied ? 'Occupied 🔴' : 'Available 🟢';
    sipStatus.style.color = isOccupied ? 'var(--orange)' : 'var(--green)';

    const vehRow = document.getElementById('sip-vehicle-row');
    const sinceRow = document.getElementById('sip-since-row');

    if (isOccupied) {
      if (vehRow) vehRow.style.display = '';
      if (sinceRow) sinceRow.style.display = '';
      sipVehicle.textContent = info.vehicle_number || (IS_ADMIN ? '—' : 'Protected User Data');
      sipSince.textContent = info.entry_time ? info.entry_time.replace('T', ' ') : '—';

      if (info.advance_amount && info.advance_amount > 0 && sipAdvRow && sipAdv) {
        sipAdvRow.style.display = '';
        sipAdv.textContent = '₹' + Number(info.advance_amount).toFixed(2);
      } else if (sipAdvRow) {
        sipAdvRow.style.display = 'none';
      }

      if ((IS_ADMIN || info.is_mine) && info.session_id) {
        sipExitRow.innerHTML = `<a class="btn small primary" href="${EXIT_URL}${info.session_id}" style="width:100%;justify-content:center;">Exit & Settle Payment →</a>`;
      } else {
        sipExitRow.innerHTML = `<span style="font-size:10px;color:var(--ink3);display:block;text-align:center;">Vehicle Parked</span>`;
      }
    } else {
      if (vehRow) vehRow.style.display = 'none';
      if (sinceRow) sinceRow.style.display = 'none';
      if (sipAdvRow) sipAdvRow.style.display = 'none';
      sipExitRow.innerHTML = `<a class="btn primary small" href="/entry" style="width:100%;justify-content:center;">Park Here (${is2W ? '2W' : '4W'}) →</a>`;
    }

    infoPanel.classList.add('visible');
  }

  // ─── Apply Slot Data from Backend ──────────────────────────────────────────
  function applySlotData(slots) {
    slots.forEach(slot => {
      const mesh = slotMeshes[slot.slot_code];
      if (!mesh) return;
      const isOccupied = slot.status === 'occupied';
      const is2W = (slot.category === 'two_wheeler');
      const baseCol = isOccupied ? COL.occFloor : COL.availFloor;

      mesh.material.color.set(selectedMesh === mesh ? COL.selected : baseCol);
      mesh.userData.baseColor = baseCol;
      mesh.userData.isOccupied = isOccupied;
      mesh.userData.slotInfo = slot;

      const pos = slotPositions[slot.slot_code];
      if (pos) {
        if (isOccupied && !vehicleGroups[slot.slot_code]) {
          addVehicleModel(slot.slot_code, is2W, pos.x, pos.z);
        } else if (!isOccupied && vehicleGroups[slot.slot_code]) {
          removeVehicleModel(slot.slot_code);
        }
      }

      // Also update 2D Fallback Tile in DOM
      const tile = document.querySelector(`.slot-tile[data-slot="${slot.slot_code}"]`);
      if (tile) {
        tile.className = `slot-tile ${isOccupied ? 'occupied' : 'available'}`;
        const iconSpan = tile.querySelector('.slot-car');
        const smallText = tile.querySelector('small');
        if (iconSpan) iconSpan.textContent = isOccupied ? (is2W ? '🏍' : '🚗') : '＋';
        if (smallText) smallText.textContent = isOccupied ? 'OCCUPIED' : 'AVAILABLE';
      }
    });
  }

  // ─── Status Refresh via /api/status ────────────────────────────────────────
  async function refreshStatus() {
    try {
      const resp = await fetch('/api/status');
      if (!resp.ok) return;
      const data = await resp.json();
      slotData = data.slots;
      applySlotData(data.slots);

      // Update counters in Dashboard
      const setEl = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
      setEl('stat-total',  data.stats.total);
      setEl('stat-avail',  data.stats.available);
      setEl('stat-active', data.stats.active);
      setEl('stat-rev',    '₹' + Math.round(data.stats.revenue));

      if (data.stats.two_wheeler) {
        setEl('stat-2w-occ', `${data.stats.two_wheeler.occupied} / ${data.stats.two_wheeler.total}`);
        setEl('stat-2w-foot', `${data.stats.two_wheeler.available} free (₹${Math.round(data.rates?.two_wheeler || 10)}/hr)`);
      }
      if (data.stats.four_wheeler) {
        setEl('stat-4w-occ', `${data.stats.four_wheeler.occupied} / ${data.stats.four_wheeler.total}`);
        setEl('stat-4w-foot', `${data.stats.four_wheeler.available} free (₹${Math.round(data.rates?.four_wheeler || 20)}/hr)`);
      }
    } catch (_) {
      // Silent catch on network hiccups
    }
  }

  // ─── View Toggle 2D / 3D ───────────────────────────────────────────────────
  function toggleView() {
    is3D = !is3D;
    if (is3D) {
      container.style.display = '';
      fallbackEl.style.display = 'none';
      if (btnToggle) btnToggle.textContent = '2D Grid';
    } else {
      container.style.display = 'none';
      fallbackEl.style.display = 'block';
      if (btnToggle) btnToggle.textContent = '3D View';
    }
  }

  function showFallback(msg) {
    if (loadingEl) loadingEl.style.display = 'none';
    if (container) container.style.display = 'none';
    if (fallbackEl) fallbackEl.style.display = 'block';
    if (btnToggle) { btnToggle.textContent = '3D View'; btnToggle.disabled = true; }
    if (msg) console.warn('[SmartPark 3D]', msg);
  }

  // ─── Resize Observer ───────────────────────────────────────────────────────
  if (typeof ResizeObserver !== 'undefined') {
    new ResizeObserver(() => {
      const w = container.clientWidth;
      if (w > 0) {
        renderer.setSize(w, H);
        camera.aspect = w / H;
        camera.updateProjectionMatrix();
      }
    }).observe(container);
  }

  // ─── Render Loop ───────────────────────────────────────────────────────────
  let animFrameId;
  function animate() {
    animFrameId = requestAnimationFrame(animate);
    renderer.render(scene, camera);
  }

  // ─── Initialization ────────────────────────────────────────────────────────
  try {
    buildParkingLot();
    updateCamera();
    if (loadingEl) loadingEl.style.display = 'none';
    animate();

    // Initial status poll & schedule every 20 seconds
    refreshStatus();
    setInterval(refreshStatus, 20000);
  } catch (err) {
    showFallback('3D initialisation failed: ' + err.message);
  }

})();
