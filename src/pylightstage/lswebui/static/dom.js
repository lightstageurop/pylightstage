export function query(selector, root = document) {
  const element = root.querySelector(selector);
  if (!element) throw new Error(`Required interface element is missing: ${selector}`);
  return element;
}

export function queryAll(selector, root = document) {
  return [...root.querySelectorAll(selector)];
}

export function errorMessage(error) {
  return error instanceof Error ? error.message : String(error);
}

export function setPressed(buttons, dataName, value) {
  for (const button of buttons) {
    const active = button.dataset[dataName] === value;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  }
}
