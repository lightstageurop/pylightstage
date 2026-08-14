import { Canvas2DRenderer } from "./renderers/canvas2d.js";
import { WebGPURenderer } from "./renderers/webgpu.js";
import { polarizedChannel, StageScene } from "./scene.js";

const canvas = document.querySelector("#stage-view");
const gridCanvas = document.querySelector("#grid-view");
const canvasShell = document.querySelector("#canvas-shell");
const backend = document.querySelector("#renderer-backend");
const endpoint = document.querySelector("#stage-endpoint");
const status = document.querySelector("#service-status");
const fallbackNote = document.querySelector("#fallback-note");
const viewButtons = [...document.querySelectorAll("[data-view]")];
const modeButtons = [...document.querySelectorAll(".view-mode-switch [data-mode]")];
const controlForm = document.querySelector("#fixture-control");
const controlFieldset = controlForm.querySelector("fieldset");
const controlStatus = document.querySelector("#control-status");
const intensityInputs = [0, 1, 2].map((index) => document.querySelector(`#intensity-${index}`));
const intensityRanges = [0, 1, 2].map((index) => document.querySelector(`#intensity-${index}-range`));
let fixtureControlAvailable = false;
let activeMode = "3d";

const CAMERA_PRESETS = {
  perspective: { yaw: 0.7, pitch: 0.27, distance: 3.75 },
  front: { yaw: 0, pitch: 0, distance: 3.85 },
  top: { yaw: 0, pitch: 1.38, distance: 4.1 },
};

const camera = { ...CAMERA_PRESETS.perspective };

async function loadConfiguration() {
  const response = await fetch("/api/config", { cache: "no-store" });
  if (!response.ok) throw new Error(`Configuration request failed (${response.status})`);
  return response.json();
}

async function createRenderers() {
  const renderers = { grid: new Canvas2DRenderer(gridCanvas), webgpu: null };
  if (navigator.gpu) {
    try {
      renderers.webgpu = await WebGPURenderer.create(canvas);
    } catch (error) {
      console.warn("WebGPU initialization failed; using the 2D grid", error);
    }
  }
  return renderers;
}

function setMode(mode, renderers) {
  if (mode === "3d" && !renderers.webgpu) return;
  activeMode = mode;
  canvas.hidden = mode !== "3d";
  gridCanvas.hidden = mode !== "2d";
  canvasShell.dataset.mode = mode;
  document.querySelector("#interaction-hint-3d").hidden = mode !== "3d";
  document.querySelector("#interaction-hint-2d").hidden = mode !== "2d";
  document.querySelector("#camera-controls").hidden = mode !== "3d";
  document.querySelector("#view-kind").textContent = mode.toUpperCase();
  backend.textContent = mode === "3d" ? "WebGPU" : "Canvas 2D";
  for (const button of modeButtons) {
    const active = button.dataset.mode === mode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  }
}

function selectView(name) {
  Object.assign(camera, CAMERA_PRESETS[name]);
  for (const button of viewButtons) {
    const active = button.dataset.view === name;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  }
}

function clearViewSelection() {
  for (const button of viewButtons) {
    button.classList.remove("active");
    button.setAttribute("aria-pressed", "false");
  }
}

function normalize(vector) {
  const length = Math.hypot(...vector) || 1;
  return vector.map((value) => value / length);
}

function cross(left, right) {
  return [
    left[1] * right[2] - left[2] * right[1],
    left[2] * right[0] - left[0] * right[2],
    left[0] * right[1] - left[1] * right[0],
  ];
}

function pickFixture(scene, clientX, clientY) {
  const bounds = canvas.getBoundingClientRect();
  const ndcX = ((clientX - bounds.left) / bounds.width) * 2 - 1;
  const ndcY = 1 - ((clientY - bounds.top) / bounds.height) * 2;
  const horizontalDistance = Math.cos(camera.pitch) * camera.distance;
  const eye = [
    Math.sin(camera.yaw) * horizontalDistance,
    Math.sin(camera.pitch) * camera.distance,
    Math.cos(camera.yaw) * horizontalDistance,
  ];
  const forward = normalize(eye.map((value) => -value));
  const right = normalize(cross(forward, [0, 1, 0]));
  const up = normalize(cross(right, forward));
  const tangent = Math.tan(Math.PI / 6.3);
  const aspect = bounds.width / bounds.height;
  const direction = normalize([0, 1, 2].map(
    (axis) => forward[axis] + right[axis] * ndcX * tangent * aspect + up[axis] * ndcY * tangent,
  ));

  let best = null;
  for (let logicalIndex = 0; logicalIndex < scene.logicalCount; logicalIndex += 1) {
    const centre = scene.getLogicalCentre(logicalIndex);
    const relative = centre.map((value, axis) => value - eye[axis]);
    const distanceAlongRay = relative.reduce((sum, value, axis) => sum + value * direction[axis], 0);
    if (distanceAlongRay <= 0) continue;
    const closest = eye.map((value, axis) => value + direction[axis] * distanceAlongRay);
    const missDistance = Math.hypot(...centre.map((value, axis) => value - closest[axis]));
    if (missDistance <= 0.105 && (!best || distanceAlongRay < best.distanceAlongRay)) {
      best = { logicalIndex, distanceAlongRay };
    }
  }
  return best?.logicalIndex ?? null;
}

function installCameraControls(scene, onSelect) {
  let drag = null;

  canvas.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    drag = {
      id: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      startX: event.clientX,
      startY: event.clientY,
    };
    canvas.setPointerCapture(event.pointerId);
  });

  canvas.addEventListener("pointermove", (event) => {
    if (!drag || drag.id !== event.pointerId) return;
    camera.yaw -= (event.clientX - drag.x) * 0.008;
    camera.pitch = Math.max(-1.42, Math.min(1.42, camera.pitch + (event.clientY - drag.y) * 0.007));
    drag.x = event.clientX;
    drag.y = event.clientY;
    clearViewSelection();
  });

  const endDrag = (event) => {
    if (drag?.id !== event.pointerId) return;
    const wasClick = Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) < 5;
    drag = null;
    if (wasClick) {
      const logicalIndex = pickFixture(scene, event.clientX, event.clientY);
      if (logicalIndex !== null) onSelect(logicalIndex);
    }
  };
  canvas.addEventListener("pointerup", endDrag);
  canvas.addEventListener("pointercancel", endDrag);

  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    camera.distance = Math.max(2.35, Math.min(6.2, camera.distance * Math.exp(event.deltaY * 0.001)));
    clearViewSelection();
  }, { passive: false });

  canvas.addEventListener("keydown", (event) => {
    const key = event.key.toLowerCase();
    if (key === "r") selectView("perspective");
    else if (event.key === "ArrowLeft") camera.yaw += 0.09;
    else if (event.key === "ArrowRight") camera.yaw -= 0.09;
    else if (event.key === "ArrowUp") camera.pitch = Math.max(-1.42, camera.pitch - 0.09);
    else if (event.key === "ArrowDown") camera.pitch = Math.min(1.42, camera.pitch + 0.09);
    else if (event.key === "+" || event.key === "=") camera.distance = Math.max(2.35, camera.distance - 0.18);
    else if (event.key === "-" || event.key === "_") camera.distance = Math.min(6.2, camera.distance + 0.18);
    else return;
    if (key !== "r") clearViewSelection();
    event.preventDefault();
  });

  for (const button of viewButtons) {
    button.addEventListener("click", () => selectView(button.dataset.view));
  }
  document.querySelector("#reset-view").addEventListener("click", () => selectView("perspective"));
}

function installGridControls(renderer, onSelect) {
  gridCanvas.addEventListener("click", (event) => {
    const logicalIndex = renderer.pick(event.clientX, event.clientY);
    if (logicalIndex !== null) onSelect(logicalIndex);
  });
}

function installModeControls(renderers) {
  const threeDimensionalButton = modeButtons.find((button) => button.dataset.mode === "3d");
  threeDimensionalButton.disabled = !renderers.webgpu;
  threeDimensionalButton.title = renderers.webgpu ? "Show the 3D stage" : "WebGPU is unavailable";
  for (const button of modeButtons) {
    button.addEventListener("click", () => setMode(button.dataset.mode, renderers));
  }
  if (renderers.webgpu) {
    setMode("3d", renderers);
  } else {
    fallbackNote.hidden = false;
    fallbackNote.textContent = "WebGPU is unavailable, so the 2D grid is the only view in this session.";
    setMode("2d", renderers);
  }
}

function selectedControlChannel(scene) {
  const selector = controlForm.elements.selector.value;
  if (selector === "direct") {
    const color = document.querySelector("#fixture-color").value;
    return color === "w" ? "white" : color;
  }
  const fixture = scene.fixtures[scene.selectedLogicalIndex];
  return polarizedChannel(fixture.arc, fixture.light, document.querySelector("#fixture-polarization").value);
}

function updateControlDescription(scene, loadValues = true) {
  if (scene.selectedLogicalIndex === null) return;
  const selector = controlForm.elements.selector.value;
  document.querySelector("#direct-control").hidden = selector !== "direct";
  document.querySelector("#polarized-control").hidden = selector !== "polarized";
  const channel = selectedControlChannel(scene);
  const labels = channel === "rgb" ? ["R", "G", "B"] : channel === "white" ? ["W", "N", "C"] : ["1", "2", "3"];
  intensityInputs.forEach((_input, index) => {
    document.querySelector(`label[for="intensity-${index}"]`).textContent = labels[index];
  });

  const fixture = scene.fixtures[scene.selectedLogicalIndex];
  let values = fixture.intensity.rgb;
  if (channel === "white") values = fixture.intensity.white;
  if (loadValues) {
    values.forEach((value, index) => {
      intensityInputs[index].value = String(value);
      intensityRanges[index].value = String(value);
    });
  }

  const routingNote = document.querySelector("#routing-note");
  if (channel === "rgbw") routingNote.textContent = "Updates both RGB and white physical cylinders.";
  else if (selector === "polarized") routingNote.textContent = `Routes to the ${channel === "rgb" ? "RGB" : "white"} cylinder for this fixture's polarization.`;
  else routingNote.textContent = `Updates only the ${channel === "rgb" ? "RGB" : "white"} physical cylinder.`;
}

function selectLogicalFixture(scene, logicalIndex) {
  scene.selectFixture(logicalIndex);
  const fixture = scene.fixtures[logicalIndex];
  document.querySelector("#selection-title").textContent = `Arc ${fixture.arc} · Light ${fixture.light}`;
  const orientation = document.querySelector("#selection-orientation");
  orientation.textContent = fixture.orientation;
  document.querySelector("#selection-empty").hidden = true;
  controlFieldset.disabled = !fixtureControlAvailable;
  if (fixtureControlAvailable) {
    controlStatus.textContent = "Changes are sent only when you press Apply or Turn off.";
    delete controlStatus.dataset.state;
  } else {
    controlStatus.textContent = "Restart lswebui to load the fixture-control endpoint.";
    controlStatus.dataset.state = "error";
  }
  updateControlDescription(scene);
}

function readIntensity() {
  return intensityInputs.map((input, index) => {
    const value = Math.max(0, Math.min(255, Number(input.value) || 0));
    input.value = String(value);
    intensityRanges[index].value = String(value);
    return value;
  });
}

function updateLocalFixture(scene, fixture, request, intensity) {
  let channel;
  if (request.selector === "direct") channel = request.color;
  else channel = polarizedChannel(fixture.arc, fixture.light, request.polarization);
  if (channel === "rgb" || channel === "rgbw") scene.setFixtureIntensity(fixture.arc, fixture.light, "rgb", intensity);
  if (channel === "white" || channel === "rgbw") scene.setFixtureIntensity(fixture.arc, fixture.light, "white", intensity);
}

async function sendFixtureControl(scene, action) {
  if (scene.selectedLogicalIndex === null) return;
  const fixture = scene.fixtures[scene.selectedLogicalIndex];
  const selector = controlForm.elements.selector.value;
  const intensity = action === "clear" ? [0, 0, 0] : readIntensity();
  const payload = {
    action,
    selector,
    arc: fixture.arc,
    light: fixture.light,
    intensity,
    color: document.querySelector("#fixture-color").value,
    polarization: document.querySelector("#fixture-polarization").value,
  };
  const buttons = [...controlForm.querySelectorAll("button")];
  buttons.forEach((button) => { button.disabled = true; });
  controlStatus.textContent = `${action === "clear" ? "Turning off" : "Applying"} Arc ${fixture.arc}, Light ${fixture.light}…`;
  controlStatus.dataset.state = "working";
  try {
    const response = await fetch("/api/fixture", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const responseBody = await response.text();
    let result;
    try {
      result = JSON.parse(responseBody);
    } catch {
      const contentType = response.headers.get("Content-Type") || "unknown content type";
      throw new Error(
        `Fixture control returned ${contentType} instead of JSON (${response.status}). Restart lswebui and reload this page.`,
      );
    }
    if (!response.ok) throw new Error(result.error || `Request failed (${response.status})`);
    updateLocalFixture(scene, fixture, payload, intensity);
    if (action === "clear") {
      intensityInputs.forEach((input, index) => {
        input.value = "0";
        intensityRanges[index].value = "0";
      });
    }
    controlStatus.textContent = `Arc ${fixture.arc}, Light ${fixture.light} ${action === "clear" ? "turned off" : "updated"}.`;
    controlStatus.dataset.state = "success";
  } catch (error) {
    controlStatus.textContent = error instanceof Error ? error.message : String(error);
    controlStatus.dataset.state = "error";
  } finally {
    buttons.forEach((button) => { button.disabled = false; });
  }
}

function installFixtureControls(scene) {
  intensityInputs.forEach((input, index) => {
    input.addEventListener("input", () => { intensityRanges[index].value = input.value; });
    intensityRanges[index].addEventListener("input", () => { input.value = intensityRanges[index].value; });
  });
  document.querySelectorAll('input[name="selector"]').forEach((input) => {
    input.addEventListener("change", () => updateControlDescription(scene));
  });
  document.querySelector("#fixture-color").addEventListener("change", () => updateControlDescription(scene));
  document.querySelector("#fixture-polarization").addEventListener("change", () => updateControlDescription(scene));
  controlForm.addEventListener("submit", (event) => {
    event.preventDefault();
    sendFixtureControl(scene, "set");
  });
  document.querySelector("#clear-fixture").addEventListener("click", () => sendFixtureControl(scene, "clear"));
}

async function start() {
  try {
    const config = await loadConfiguration();
    fixtureControlAvailable = config.features?.fixture_control === true;
    endpoint.textContent = config.lightstage_uri;
    endpoint.title = config.lightstage_uri;
    status.textContent = "Ready";
    status.dataset.state = "ready";
    const renderers = await createRenderers();
    const scene = new StageScene();

    document.querySelector("#show-rgb").addEventListener("change", (event) => {
      scene.setLayerVisibility("rgb", event.currentTarget.checked);
    });
    document.querySelector("#show-white").addEventListener("change", (event) => {
      scene.setLayerVisibility("white", event.currentTarget.checked);
    });
    installFixtureControls(scene);
    installCameraControls(scene, (logicalIndex) => selectLogicalFixture(scene, logicalIndex));
    installGridControls(renderers.grid, (logicalIndex) => selectLogicalFixture(scene, logicalIndex));
    installModeControls(renderers);

    const frame = () => {
      if (activeMode === "3d") renderers.webgpu.render(scene, camera);
      else renderers.grid.render(scene);
      requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
  } catch (error) {
    status.textContent = "Unavailable";
    status.dataset.state = "error";
    fallbackNote.hidden = false;
    fallbackNote.textContent = error instanceof Error ? error.message : String(error);
  }
}

start();
