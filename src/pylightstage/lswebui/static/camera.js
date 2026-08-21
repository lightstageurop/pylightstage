import { query, setPressed } from "./dom.js";
import { clamp, cross, normalize } from "./math.js";

const PRESETS = {
  perspective: { yaw: 0.7, pitch: 0.27, distance: 3.75 },
  front: { yaw: 0, pitch: 0, distance: 3.85 },
  top: { yaw: 0, pitch: 1.38, distance: 4.1 },
};
const MIN_PITCH = -1.42;
const MAX_PITCH = 1.42;
const MIN_DISTANCE = 2.35;
const MAX_DISTANCE = 6.2;

export const camera = { ...PRESETS.perspective };

function selectView(name, buttons) {
  Object.assign(camera, PRESETS[name]);
  setPressed(buttons, "view", name);
}

function clearViewSelection(buttons) {
  setPressed(buttons, "view", "");
}

function pickFixture(canvas, scene, clientX, clientY) {
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
  const scale = Math.tan(Math.PI / 6.3);
  const direction = normalize(forward.map(
    (value, axis) => value
      + right[axis] * ndcX * scale * bounds.width / bounds.height
      + up[axis] * ndcY * scale,
  ));

  let nearest = null;
  for (let logicalIndex = 0; logicalIndex < scene.logicalCount; logicalIndex += 1) {
    const centre = scene.getLogicalCentre(logicalIndex);
    const relative = centre.map((value, axis) => value - eye[axis]);
    const distance = relative.reduce(
      (sum, value, axis) => sum + value * direction[axis],
      0,
    );
    if (distance <= 0) continue;
    const closest = eye.map((value, axis) => value + direction[axis] * distance);
    const miss = Math.hypot(...centre.map((value, axis) => value - closest[axis]));
    if (miss <= 0.105 && (!nearest || distance < nearest.distance)) {
      nearest = { logicalIndex, distance };
    }
  }
  return nearest?.logicalIndex ?? null;
}

export function installCameraControls(canvas, scene, buttons, onSelect) {
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
    camera.pitch = clamp(camera.pitch + (event.clientY - drag.y) * 0.007, MIN_PITCH, MAX_PITCH);
    drag.x = event.clientX;
    drag.y = event.clientY;
    clearViewSelection(buttons);
  });

  const endDrag = (event) => {
    if (drag?.id !== event.pointerId) return;
    const wasClick = Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) < 5;
    drag = null;
    if (!wasClick) return;
    const logicalIndex = pickFixture(canvas, scene, event.clientX, event.clientY);
    if (logicalIndex !== null) {
      onSelect(logicalIndex, {
        additive: event.shiftKey,
        toggle: event.ctrlKey || event.metaKey,
      });
    }
  };
  canvas.addEventListener("pointerup", endDrag);
  canvas.addEventListener("pointercancel", endDrag);

  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    camera.distance = clamp(
      camera.distance * Math.exp(event.deltaY * 0.001),
      MIN_DISTANCE,
      MAX_DISTANCE,
    );
    clearViewSelection(buttons);
  }, { passive: false });

  canvas.addEventListener("keydown", (event) => {
    const key = event.key.toLowerCase();
    if (key === "r") selectView("perspective", buttons);
    else if (event.key === "ArrowLeft") camera.yaw += 0.09;
    else if (event.key === "ArrowRight") camera.yaw -= 0.09;
    else if (event.key === "ArrowUp") camera.pitch = clamp(camera.pitch - 0.09, MIN_PITCH, MAX_PITCH);
    else if (event.key === "ArrowDown") camera.pitch = clamp(camera.pitch + 0.09, MIN_PITCH, MAX_PITCH);
    else if (event.key === "+" || event.key === "=") camera.distance = Math.max(MIN_DISTANCE, camera.distance - 0.18);
    else if (event.key === "-" || event.key === "_") camera.distance = Math.min(MAX_DISTANCE, camera.distance + 0.18);
    else return;
    if (key !== "r") clearViewSelection(buttons);
    event.preventDefault();
  });

  for (const button of buttons) {
    button.addEventListener("click", () => selectView(button.dataset.view, buttons));
  }
  query("#reset-view").addEventListener("click", () => selectView("perspective", buttons));
}
