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
  const selectionEmpty = query("#selection-empty");
  const selectionSummary = query("#selection-summary");
  const selectionChips = query("#selection-chips");
  let selectedTargets = [];

  function targetKey(target) {
    if (target.target === "fixture") return `fixture:${target.arc}:${target.light}`;
    if (target.target === "arc") return `arc:${target.arc}`;
    return `horizontal_arc:${target.light}`;
  }

  function targetName(target, compact = false) {
    if (target.target === "fixture") {
      return compact ? `F ${target.arc}:${target.light}` : `Arc ${target.arc}, Light ${target.light}`;
    }
    if (target.target === "arc") return compact ? `A ${target.arc}` : `Arc ${target.arc}`;
    return compact ? `H ${target.light}` : `Horizontal arc ${target.light}`;
  }

  function targetFromFixture(fixture) {
    const brush = query('input[name="selection-brush"]:checked').value;
    if (brush === "arc") return { target: "arc", arc: fixture.arc };
    if (brush === "horizontal_arc") {
      return { target: "horizontal_arc", light: fixture.light };
    }
    return { target: "fixture", arc: fixture.arc, light: fixture.light };
  }

  function targetFixtures(target) {
    if (target.target === "arc") {
      return scene.fixtures.filter((fixture) => fixture.arc === target.arc);
    }
    if (target.target === "horizontal_arc") {
      return scene.fixtures.filter((fixture) => fixture.light === target.light);
    }
    return [scene.fixtures[target.arc * scene.lightsPerArc + target.light]];
  }

  function selectedFixtures() {
    const indices = new Set();
    selectedTargets.forEach((target) => {
      targetFixtures(target).forEach((fixture) => {
        indices.add(fixture.arc * scene.lightsPerArc + fixture.light);
      });
    });
    return [...indices].sort((left, right) => left - right)
      .map((logicalIndex) => scene.fixtures[logicalIndex]);
  }

  function setIntensity(values) {
    values.forEach((value, index) => {
      inputs[index].value = String(value);
      ranges[index].value = String(value);
    });
  }

  function selectedChannel() {
    const fixture = scene.fixtures[scene.selectedLogicalIndex];
    if (form.elements.selector.value === "polarized") {
      return polarizedChannel(fixture.arc, fixture.light, polarization.value);
    }
    return colour.value === "w" ? "white" : colour.value;
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
    } else if (selector === "polarized" && selectedFixtures().length > 1) {
      routingNote.textContent = "Routes each selected fixture through the physical cylinder matching its polarization.";
    } else if (selector === "polarized") {
      routingNote.textContent = `Routes to the ${channel === "rgb" ? "RGB" : "white"} cylinder for this fixture's polarization.`;
    } else {
      routingNote.textContent = `Updates only the ${channel === "rgb" ? "RGB" : "white"} physical cylinder.`;
    }
  }

  function resetStatus(hasSelection) {
    status.textContent = available
      ? (hasSelection ? DEFAULT_STATUS : "Paint a selection on the stage to enable controls.")
      : "Restart lswebui to load the fixture-control endpoint.";
    if (available) delete status.dataset.state;
    else status.dataset.state = "error";
  }

  function renderSelectionSummary() {
    selectionChips.replaceChildren();
    selectedTargets.forEach((target) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "selection-chip";
      chip.textContent = targetName(target, true);
      chip.title = `${targetName(target)} — click to remove`;
      chip.setAttribute("aria-label", `Remove ${targetName(target)} from selection`);
      chip.addEventListener("click", () => {
        const key = targetKey(target);
        selectedTargets = selectedTargets.filter((candidate) => targetKey(candidate) !== key);
        syncSelection();
      });
      selectionChips.append(chip);
    });
  }

  function syncSelection(preferredLogicalIndex = null) {
    const fixtures = selectedFixtures();
    const logicalIndices = fixtures.map(
      (fixture) => fixture.arc * scene.lightsPerArc + fixture.light,
    );
    const primaryLogicalIndex = logicalIndices.includes(preferredLogicalIndex)
      ? preferredLogicalIndex
      : (logicalIndices.at(-1) ?? null);
    scene.selectFixtures(logicalIndices, primaryLogicalIndex);

    const hasSelection = logicalIndices.length > 0;
    fieldset.disabled = !available || !hasSelection;
    selectionEmpty.hidden = hasSelection;
    selectionSummary.hidden = !hasSelection;
    resetStatus(hasSelection);

    if (!hasSelection) {
      query("#selection-title").textContent = "No fixture selected";
      query("#selection-orientation").textContent = "Idle";
      return;
    }

    query("#selection-title").textContent = selectedTargets.length === 1
      ? targetName(selectedTargets[0])
      : `${selectedTargets.length} targets selected`;
    query("#selection-orientation").textContent = `${logicalIndices.length} fixture${logicalIndices.length === 1 ? "" : "s"}`;
    query("#selection-count").textContent = `${logicalIndices.length} fixture${logicalIndices.length === 1 ? "" : "s"} · ${selectedTargets.length} target${selectedTargets.length === 1 ? "" : "s"}`;
    renderSelectionSummary();
    updateDescription();
  }

  function readIntensity() {
    const values = inputs.map((input) => clamp(Number(input.value) || 0, 0, 255));
    setIntensity(values);
    return values;
  }

  function updateLocalSelection(request, intensity) {
    selectedFixtures().forEach((fixture) => {
      const channel = request.selector === "direct"
        ? request.color
        : polarizedChannel(fixture.arc, fixture.light, request.polarization);
      if (channel === "rgb" || channel === "rgbw") {
        scene.setFixtureIntensity(fixture.arc, fixture.light, "rgb", intensity);
      }
      if (channel === "white" || channel === "rgbw") {
        scene.setFixtureIntensity(fixture.arc, fixture.light, "white", intensity);
      }
    });
  }

  async function send(action) {
    if (selectedTargets.length === 0) return;
    const intensity = action === "clear" ? [0, 0, 0] : readIntensity();
    const request = {
      action,
      targets: selectedTargets.map((target) => ({ ...target })),
      selector: form.elements.selector.value,
      intensity,
      color: colour.value,
      polarization: polarization.value,
    };
    const buttons = queryAll("button", form);
    buttons.forEach((button) => { button.disabled = true; });
    const name = selectedTargets.length === 1
      ? targetName(selectedTargets[0])
      : `${selectedTargets.length} selected targets`;
    status.textContent = `${action === "clear" ? "Turning off" : "Applying"} ${name}…`;
    status.dataset.state = "working";
    try {
      await controlFixture(request);
      updateLocalSelection(request, intensity);
      if (action === "clear") setIntensity(intensity);
      status.textContent = `${name} ${action === "clear" ? "turned off" : "updated"}.`;
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
  query("#clear-selection").addEventListener("click", () => {
    selectedTargets = [];
    syncSelection();
  });
  resetStatus(false);

  return function selectFixture(logicalIndex, modifiers = {}) {
    const fixture = scene.fixtures[logicalIndex];
    const target = targetFromFixture(fixture);
    const key = targetKey(target);
    const existingIndex = selectedTargets.findIndex(
      (candidate) => targetKey(candidate) === key,
    );

    if (modifiers.toggle) {
      if (existingIndex === -1) selectedTargets.push(target);
      else selectedTargets.splice(existingIndex, 1);
    } else if (modifiers.additive) {
      if (existingIndex === -1) selectedTargets.push(target);
    } else {
      selectedTargets = [target];
    }
    syncSelection(logicalIndex);
  };
}
