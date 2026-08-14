const VERTICAL_RGB_LIGHTS = new Set([0, 2, 4, 6, 7, 9, 11, 13]);

const RGB_OFF = [0.035, 0.065, 0.07];
const WHITE_OFF = [0.07, 0.068, 0.06];

export function polarizedChannel(arc, light, polarization) {
  if (polarization === "up") return "rgbw";
  const rgbIsVertical = (arc % 2 === 0) === VERTICAL_RGB_LIGHTS.has(light);
  if (polarization === "pp") return rgbIsVertical ? "rgb" : "white";
  return rgbIsVertical ? "white" : "rgb";
}

/** Renderer-neutral state for the paired physical fixtures in a 12-by-14 LightStage. */
export class StageScene {
  constructor(arcs = 12, lightsPerArc = 14) {
    this.arcs = arcs;
    this.lightsPerArc = lightsPerArc;
    this.logicalCount = arcs * lightsPerArc;
    this.physicalPerFixture = 2;
    this.count = this.logicalCount * this.physicalPerFixture;
    this.instanceStride = 16;
    // position + padding, horizontal tangent + padding, vertical tangent + padding, colour.rgba
    this.instanceData = new Float32Array(this.count * this.instanceStride);
    this.fixtures = [];
    this.visibility = { rgb: true, white: true };
    this.selectedLogicalIndex = null;
    this.version = 0;
    this.#buildLayout();
  }

  #buildLayout() {
    const radius = 1.46;
    const pairSpacing = 0.11;
    for (let arc = 0; arc < this.arcs; arc += 1) {
      const azimuth = (arc / this.arcs) * Math.PI * 2;
      const horizontal = [-Math.sin(azimuth), 0, Math.cos(azimuth)];
      for (let light = 0; light < this.lightsPerArc; light += 1) {
        const logicalIndex = arc * this.lightsPerArc + light;
        const elevation = -1.08 + (light / (this.lightsPerArc - 1)) * 2.16;
        const ringRadius = radius * Math.cos(elevation);
        const centre = [
          ringRadius * Math.cos(azimuth),
          radius * Math.sin(elevation),
          ringRadius * Math.sin(azimuth),
        ];
        const vertical = [
          -Math.sin(elevation) * Math.cos(azimuth),
          Math.cos(elevation),
          -Math.sin(elevation) * Math.sin(azimuth),
        ];
        // This mirrors pylightstage.utils._VERTICAL_RGB_LIGHTS and polarized_color().
        const rgbIsVertical = (arc % 2 === 0) === VERTICAL_RGB_LIGHTS.has(light);
        const pairAxis = rgbIsVertical ? vertical : horizontal;
        const orientation = rgbIsVertical ? "vertical" : "horizontal";

        this.#writePhysicalFixture(
          logicalIndex * 2,
          centre,
          pairAxis,
          pairSpacing / 2,
          horizontal,
          vertical,
          RGB_OFF,
        );
        this.#writePhysicalFixture(
          logicalIndex * 2 + 1,
          centre,
          pairAxis,
          -pairSpacing / 2,
          horizontal,
          vertical,
          WHITE_OFF,
        );
        this.fixtures.push({
          arc,
          light,
          orientation,
          rgbIsVertical,
          intensity: { rgb: [0, 0, 0], white: [0, 0, 0] },
        });
      }
    }
    this.version += 1;
  }

  #writePhysicalFixture(index, centre, pairAxis, displacement, horizontal, vertical, colour) {
    const offset = index * this.instanceStride;
    for (let axis = 0; axis < 3; axis += 1) {
      this.instanceData[offset + axis] = centre[axis] + pairAxis[axis] * displacement;
      this.instanceData[offset + 4 + axis] = horizontal[axis];
      this.instanceData[offset + 8 + axis] = vertical[axis];
      this.instanceData[offset + 12 + axis] = colour[axis];
    }
    this.instanceData[offset + 15] = 1;
  }

  setLayerVisibility(channel, visible) {
    if (!(channel in this.visibility)) throw new RangeError(`Unknown fixture layer: ${channel}`);
    this.visibility[channel] = Boolean(visible);
    for (let logicalIndex = 0; logicalIndex < this.logicalCount; logicalIndex += 1) {
      const physicalIndex = logicalIndex * 2 + (channel === "white" ? 1 : 0);
      const selected = logicalIndex === this.selectedLogicalIndex;
      this.instanceData[physicalIndex * this.instanceStride + 15] = visible ? (selected ? 2 : 1) : 0;
    }
    this.version += 1;
  }

  setFixture(arc, light, channel, colour, bumpVersion = true) {
    if (arc < 0 || arc >= this.arcs || light < 0 || light >= this.lightsPerArc) {
      throw new RangeError(`Fixture ${arc}:${light} is outside the stage layout`);
    }
    if (channel !== "rgb" && channel !== "white") {
      throw new RangeError(`Unknown physical fixture channel: ${channel}`);
    }
    const physicalIndex = (arc * this.lightsPerArc + light) * 2 + (channel === "white" ? 1 : 0);
    const offset = physicalIndex * this.instanceStride + 12;
    this.instanceData[offset] = colour[0];
    this.instanceData[offset + 1] = colour[1];
    this.instanceData[offset + 2] = colour[2];
    const logicalIndex = arc * this.lightsPerArc + light;
    const selected = logicalIndex === this.selectedLogicalIndex;
    this.instanceData[offset + 3] = this.visibility[channel] ? (selected ? 2 : (colour[3] ?? 1)) : 0;
    if (bumpVersion) this.version += 1;
  }

  selectFixture(logicalIndex) {
    if (!Number.isInteger(logicalIndex) || logicalIndex < 0 || logicalIndex >= this.logicalCount) {
      throw new RangeError(`Logical fixture ${logicalIndex} is outside the stage layout`);
    }
    const previous = this.selectedLogicalIndex;
    this.selectedLogicalIndex = logicalIndex;
    for (const index of [previous, logicalIndex]) {
      if (index === null) continue;
      for (const [channel, channelOffset] of [["rgb", 0], ["white", 1]]) {
        const alphaOffset = (index * 2 + channelOffset) * this.instanceStride + 15;
        this.instanceData[alphaOffset] = this.visibility[channel]
          ? (index === logicalIndex ? 2 : 1)
          : 0;
      }
    }
    this.version += 1;
  }

  getLogicalCentre(logicalIndex) {
    const rgbOffset = logicalIndex * 2 * this.instanceStride;
    const whiteOffset = rgbOffset + this.instanceStride;
    return [0, 1, 2].map(
      (axis) => (this.instanceData[rgbOffset + axis] + this.instanceData[whiteOffset + axis]) / 2,
    );
  }

  setFixtureIntensity(arc, light, channel, intensity) {
    const values = intensity.map((value) => Math.max(0, Math.min(255, Number(value))));
    const logicalIndex = arc * this.lightsPerArc + light;
    this.fixtures[logicalIndex].intensity[channel] = [...values];
    let colour;
    if (channel === "rgb") {
      colour = RGB_OFF.map((base, index) => base + (values[index] / 255) * 0.9);
    } else {
      const [warm, neutral, cool] = values.map((value) => value / 255);
      colour = [
        WHITE_OFF[0] + warm * 0.58 + neutral * 0.42 + cool * 0.2,
        WHITE_OFF[1] + warm * 0.36 + neutral * 0.48 + cool * 0.4,
        WHITE_OFF[2] + warm * 0.16 + neutral * 0.38 + cool * 0.58,
      ].map((value) => Math.min(1, value));
    }
    this.setFixture(arc, light, channel, colour);
  }
}
