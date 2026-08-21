import { resizeCanvas } from "../math.js";

const SQRT_3 = Math.sqrt(3);

/** Map each arc to one top-to-bottom, alternating honeycomb column. */
export function fixtureGridPosition(arc, light) {
  return {
    column: arc,
    row: light,
  };
}

function cssColour(values, multiplier = 1) {
  const channels = values.map((value) => Math.round(Math.min(1, value * multiplier) * 255));
  return `rgb(${channels[0]} ${channels[1]} ${channels[2]})`;
}

function hexagon(context, x, y, radius) {
  context.beginPath();
  for (let corner = 0; corner < 6; corner += 1) {
    const angle = Math.PI / 6 + corner * Math.PI / 3;
    const point = [x + Math.cos(angle) * radius, y + Math.sin(angle) * radius];
    if (corner === 0) context.moveTo(...point);
    else context.lineTo(...point);
  }
  context.closePath();
}

/** A compact honeycomb view with one selectable hexagon per logical fixture. */
export class Canvas2DRenderer {
  constructor(canvas) {
    this.canvas = canvas;
    this.context = canvas.getContext("2d", { alpha: false });
    if (!this.context) throw new Error("Could not create a Canvas 2D context");
    this.cells = [];
  }

  resize() {
    return resizeCanvas(this.canvas);
  }

  layout(scene) {
    const { width, height } = this.canvas;
    const padding = Math.max(20, Math.min(width, height) * 0.045);
    const columnCount = scene.arcs;
    const rowCount = scene.lightsPerArc;
    const gridWidth = (columnCount + 0.5) * SQRT_3;
    const gridHeight = 1.5 * (rowCount - 1) + 2;
    const stepRadius = Math.min(
      (width - padding * 2) / gridWidth,
      (height - padding * 2) / gridHeight,
    );
    const drawnRadius = stepRadius;
    const occupiedWidth = gridWidth * stepRadius;
    const occupiedHeight = gridHeight * stepRadius;
    const originX = (width - occupiedWidth) / 2 + SQRT_3 * stepRadius / 2;
    const originY = (height - occupiedHeight) / 2 + stepRadius;

    this.cells = [];
    for (let arc = 0; arc < scene.arcs; arc += 1) {
      for (let light = 0; light < scene.lightsPerArc; light += 1) {
        const gridPosition = fixtureGridPosition(arc, light);
        this.cells.push({
          logicalIndex: arc * scene.lightsPerArc + light,
          arc,
          light,
          x: originX
            + (gridPosition.column + (gridPosition.row % 2) / 2) * SQRT_3 * stepRadius,
          y: originY + gridPosition.row * 1.5 * stepRadius,
          radius: drawnRadius,
        });
      }
    }
  }

  fixtureColour(scene, logicalIndex, channel) {
    const channelOffset = channel === "white" ? 1 : 0;
    const offset = (logicalIndex * 2 + channelOffset) * scene.instanceStride;
    if (scene.instanceData[offset + 15] <= 0) return [0.025, 0.035, 0.038];
    return [0, 1, 2].map((axis) => scene.instanceData[offset + 12 + axis]);
  }

  drawCell(scene, cell) {
    const context = this.context;
    const { x, y, radius, logicalIndex } = cell;
    const rgb = this.fixtureColour(scene, logicalIndex, "rgb");
    const white = this.fixtureColour(scene, logicalIndex, "white");

    context.save();
    hexagon(context, x, y, radius);
    context.clip();
    context.fillStyle = cssColour(rgb, 1.25);
    context.fillRect(x - radius, y - radius, radius, radius * 2);
    context.fillStyle = cssColour(white, 1.25);
    context.fillRect(x, y - radius, radius, radius * 2);
    context.fillStyle = "rgb(255 255 255 / 0.035)";
    context.fillRect(x - radius, y - radius, radius * 2, radius * 0.38);
    context.restore();

    hexagon(context, x, y, radius);
    const selected = scene.selectedLogicalIndices.has(logicalIndex);
    context.strokeStyle = selected ? "#72ead8" : "#31444a";
    context.lineWidth = selected
      ? Math.max(2, radius * 0.11)
      : Math.max(1, radius * 0.045);
    context.stroke();

    context.beginPath();
    context.moveTo(x, y - radius * 0.74);
    context.lineTo(x, y + radius * 0.74);
    context.strokeStyle = "rgb(5 10 12 / 0.56)";
    context.lineWidth = Math.max(1, radius * 0.045);
    context.stroke();

    if (radius >= 12) {
      context.fillStyle = selected ? "#effffc" : "#91a3a8";
      context.font = `600 ${Math.max(7, radius * 0.32)}px ui-monospace, monospace`;
      context.textAlign = "center";
      context.textBaseline = "middle";
      context.fillText(`${cell.arc}:${cell.light}`, x, y);
    }
  }

  pick(clientX, clientY) {
    const bounds = this.canvas.getBoundingClientRect();
    const x = (clientX - bounds.left) * this.canvas.width / bounds.width;
    const y = (clientY - bounds.top) * this.canvas.height / bounds.height;
    for (const cell of this.cells) {
      const dx = Math.abs(x - cell.x);
      const dy = Math.abs(y - cell.y);
      if (dx <= cell.radius * SQRT_3 / 2 && dy + dx / SQRT_3 <= cell.radius) {
        return cell.logicalIndex;
      }
    }
    return null;
  }

  render(scene) {
    if (this.resize() || this.cells.length !== scene.logicalCount) this.layout(scene);
    const context = this.context;
    const { width, height } = this.canvas;
    const background = context.createRadialGradient(
      width / 2, height / 2, 0, width / 2, height / 2, Math.max(width, height) * 0.7,
    );
    background.addColorStop(0, "#0c1819");
    background.addColorStop(0.58, "#080e10");
    background.addColorStop(1, "#040709");
    context.fillStyle = background;
    context.fillRect(0, 0, width, height);

    for (const cell of this.cells) this.drawCell(scene, cell);
  }
}
