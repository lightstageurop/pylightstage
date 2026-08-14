import { loadConfiguration, readServer } from "./api.js";
import { camera, installCameraControls } from "./camera.js";
import { errorMessage, query, queryAll, setPressed } from "./dom.js";
import { installFixtureControls } from "./fixture-controls.js";
import { Canvas2DRenderer } from "./renderers/canvas2d.js";
import { WebGPURenderer } from "./renderers/webgpu.js";
import { StageScene } from "./scene.js";

const canvas = query("#stage-view");
const gridCanvas = query("#grid-view");
const canvasShell = query("#canvas-shell");
const backend = query("#renderer-backend");
const endpoint = query("#stage-endpoint");
const status = query("#service-status");
const connectionStatusDot = query(".mini-status");
const fallbackNote = query("#fallback-note");
const viewButtons = queryAll("[data-view]");
const modeButtons = queryAll(".view-mode-switch [data-mode]");
let activeMode = "3d";

const CONNECTIVITY_CHECK_INTERVAL_MS = 3000;

function setConnectivityStatus(state, message, detail = "") {
  status.textContent = message;
  status.dataset.state = state;
  status.title = detail;
  connectionStatusDot.dataset.state = state;
}

async function checkConnectivity() {
  try {
    await readServer("get-mode");
    setConnectivityStatus("ready", "Ready", "LightStage server is reachable.");
  } catch (error) {
    setConnectivityStatus("error", "Unavailable", errorMessage(error));
  } finally {
    window.setTimeout(checkConnectivity, CONNECTIVITY_CHECK_INTERVAL_MS);
  }
}

async function createRenderers() {
  const renderers = { grid: new Canvas2DRenderer(gridCanvas), webgpu: null };
  if (!navigator.gpu) return renderers;
  try {
    renderers.webgpu = await WebGPURenderer.create(canvas);
  } catch (error) {
    console.warn("WebGPU initialization failed; using the 2D grid", error);
  }
  return renderers;
}

function setMode(mode, renderers) {
  if (mode === "3d" && !renderers.webgpu) return;
  activeMode = mode;
  canvas.hidden = mode !== "3d";
  gridCanvas.hidden = mode !== "2d";
  canvasShell.dataset.mode = mode;
  query("#interaction-hint-3d").hidden = mode !== "3d";
  query("#interaction-hint-2d").hidden = mode !== "2d";
  query("#camera-controls").hidden = mode !== "3d";
  query("#view-kind").textContent = mode.toUpperCase();
  backend.textContent = mode === "3d" ? "WebGPU" : "Canvas 2D";
  setPressed(modeButtons, "mode", mode);
}

function installModeControls(renderers) {
  const threeDimensional = modeButtons.find((button) => button.dataset.mode === "3d");
  threeDimensional.disabled = !renderers.webgpu;
  threeDimensional.title = renderers.webgpu
    ? "Show the 3D stage"
    : "WebGPU is unavailable";
  modeButtons.forEach((button) => {
    button.addEventListener("click", () => setMode(button.dataset.mode, renderers));
  });
  if (renderers.webgpu) {
    setMode("3d", renderers);
  } else {
    fallbackNote.hidden = false;
    fallbackNote.textContent = "WebGPU is unavailable, so the 2D grid is the only view in this session.";
    setMode("2d", renderers);
  }
}

function installInspector() {
  const form = query("#server-inspector");
  const result = query("#inspect-result");
  const button = query("button", form);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    button.disabled = true;
    result.hidden = false;
    result.textContent = "Reading…";
    result.dataset.state = "working";
    try {
      result.textContent = JSON.stringify(await readServer(form.elements.action.value), null, 2);
      result.dataset.state = "success";
    } catch (error) {
      result.textContent = errorMessage(error);
      result.dataset.state = "error";
    } finally {
      button.disabled = false;
    }
  });
}

function installSceneControls(scene, gridRenderer, selectFixture) {
  query("#show-rgb").addEventListener("change", (event) => {
    scene.setLayerVisibility("rgb", event.currentTarget.checked);
  });
  query("#show-white").addEventListener("change", (event) => {
    scene.setLayerVisibility("white", event.currentTarget.checked);
  });
  installCameraControls(canvas, scene, viewButtons, selectFixture);
  gridCanvas.addEventListener("click", (event) => {
    const logicalIndex = gridRenderer.pick(event.clientX, event.clientY);
    if (logicalIndex !== null) selectFixture(logicalIndex);
  });
}

function startRendering(scene, renderers) {
  const frame = () => {
    if (activeMode === "3d") renderers.webgpu.render(scene, camera);
    else renderers.grid.render(scene);
    requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}

async function start() {
  try {
    const config = await loadConfiguration();
    endpoint.textContent = config.lightstage_uri;
    endpoint.title = config.lightstage_uri;
    setConnectivityStatus("checking", "Checking", `Checking ${config.lightstage_uri}…`);
    checkConnectivity();

    const renderers = await createRenderers();
    const scene = new StageScene();
    const selectFixture = installFixtureControls(
      scene,
      config.features?.fixture_control === true,
    );
    installInspector();
    installSceneControls(scene, renderers.grid, selectFixture);
    installModeControls(renderers);
    startRendering(scene, renderers);
  } catch (error) {
    const detail = errorMessage(error);
    setConnectivityStatus("error", "Unavailable", detail);
    fallbackNote.hidden = false;
    fallbackNote.textContent = detail;
  }
}

start();
