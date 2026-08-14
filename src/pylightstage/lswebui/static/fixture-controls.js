import { controlFixture } from "./api.js";
import { errorMessage, query, queryAll } from "./dom.js";
import { clamp } from "./math.js";
import { polarizedChannel } from "./scene.js";

const DEFAULT_STATUS = "Changes are sent only when you press Apply or Turn off.";

export function installFixtureControls(scene, available) {
  const form = query("#fixture-control");
  const fieldset = query("fieldset", form);
  const status = query("#control-status");
  const colour = query("#fixture-color");
  const polarization = query("#fixture-polarization");
  const inputs = [0, 1, 2].map((index) => query(`#intensity-${index}`));
  const ranges = [0, 1, 2].map((index) => query(`#intensity-${index}-range`));

  function selectedChannel() {
    const fixture = scene.fixtures[scene.selectedLogicalIndex];
    if (form.elements.selector.value === "polarized") {
      return polarizedChannel(fixture.arc, fixture.light, polarization.value);
    }
    return colour.value === "w" ? "white" : colour.value;
  }

  function setIntensity(values) {
    values.forEach((value, index) => {
      inputs[index].value = String(value);
      ranges[index].value = String(value);
    });
  }

  function updateDescription(loadValues = true) {
    if (scene.selectedLogicalIndex === null) return;
    const selector = form.elements.selector.value;
    query("#direct-control").hidden = selector !== "direct";
    query("#polarized-control").hidden = selector !== "polarized";

    const channel = selectedChannel();
    const labels = channel === "rgb"
      ? ["R", "G", "B"]
      : channel === "white" ? ["W", "N", "C"] : ["1", "2", "3"];
    labels.forEach((label, index) => {
      query(`label[for="intensity-${index}"]`).textContent = label;
    });

    const fixture = scene.fixtures[scene.selectedLogicalIndex];
    if (loadValues) {
      setIntensity(channel === "white" ? fixture.intensity.white : fixture.intensity.rgb);
    }

    const routingNote = query("#routing-note");
    if (channel === "rgbw") {
      routingNote.textContent = "Updates both RGB and white physical cylinders.";
    } else if (selector === "polarized") {
      routingNote.textContent = `Routes to the ${channel === "rgb" ? "RGB" : "white"} cylinder for this fixture's polarization.`;
    } else {
      routingNote.textContent = `Updates only the ${channel === "rgb" ? "RGB" : "white"} physical cylinder.`;
    }
  }

  function readIntensity() {
    const values = inputs.map((input) => clamp(Number(input.value) || 0, 0, 255));
    setIntensity(values);
    return values;
  }

  function updateLocalFixture(fixture, request, intensity) {
    const channel = request.selector === "direct"
      ? request.color
      : polarizedChannel(fixture.arc, fixture.light, request.polarization);
    if (channel === "rgb" || channel === "rgbw") {
      scene.setFixtureIntensity(fixture.arc, fixture.light, "rgb", intensity);
    }
    if (channel === "white" || channel === "rgbw") {
      scene.setFixtureIntensity(fixture.arc, fixture.light, "white", intensity);
    }
  }

  async function send(action) {
    if (scene.selectedLogicalIndex === null) return;
    const fixture = scene.fixtures[scene.selectedLogicalIndex];
    const intensity = action === "clear" ? [0, 0, 0] : readIntensity();
    const request = {
      action,
      selector: form.elements.selector.value,
      arc: fixture.arc,
      light: fixture.light,
      intensity,
      color: colour.value,
      polarization: polarization.value,
    };
    const buttons = queryAll("button", form);
    buttons.forEach((button) => { button.disabled = true; });
    status.textContent = `${action === "clear" ? "Turning off" : "Applying"} Arc ${fixture.arc}, Light ${fixture.light}…`;
    status.dataset.state = "working";
    try {
      await controlFixture(request);
      updateLocalFixture(fixture, request, intensity);
      if (action === "clear") setIntensity(intensity);
      status.textContent = `Arc ${fixture.arc}, Light ${fixture.light} ${action === "clear" ? "turned off" : "updated"}.`;
      status.dataset.state = "success";
    } catch (error) {
      status.textContent = errorMessage(error);
      status.dataset.state = "error";
    } finally {
      buttons.forEach((button) => { button.disabled = false; });
    }
  }

  inputs.forEach((input, index) => {
    input.addEventListener("input", () => { ranges[index].value = input.value; });
    ranges[index].addEventListener("input", () => { input.value = ranges[index].value; });
  });
  queryAll('input[name="selector"]').forEach((input) => {
    input.addEventListener("change", () => updateDescription());
  });
  colour.addEventListener("change", () => updateDescription());
  polarization.addEventListener("change", () => updateDescription());
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    send("set");
  });
  query("#clear-fixture").addEventListener("click", () => send("clear"));

  return function selectFixture(logicalIndex) {
    scene.selectFixture(logicalIndex);
    const fixture = scene.fixtures[logicalIndex];
    query("#selection-title").textContent = `Arc ${fixture.arc} · Light ${fixture.light}`;
    query("#selection-orientation").textContent = fixture.orientation;
    query("#selection-empty").hidden = true;
    fieldset.disabled = !available;
    status.textContent = available
      ? DEFAULT_STATUS
      : "Restart lswebui to load the fixture-control endpoint.";
    if (available) delete status.dataset.state;
    else status.dataset.state = "error";
    updateDescription();
  };
}
