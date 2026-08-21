async function parseJson(response, invalidResponse) {
  const body = await response.text();
  try {
    return JSON.parse(body);
  } catch {
    throw new Error(invalidResponse(response));
  }
}

export async function loadConfiguration() {
  const response = await fetch("/api/config", { cache: "no-store" });
  if (!response.ok) throw new Error(`Configuration request failed (${response.status})`);
  return response.json();
}

export async function readServer(action) {
  const response = await fetch(`/api/inspect?action=${encodeURIComponent(action)}`, {
    cache: "no-store",
  });
  const payload = await parseJson(
    response,
    ({ status }) => `Server inspection returned an invalid response (${status}).`,
  );
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload.result;
}

export async function controlFixture(payload) {
  const response = await fetch("/api/fixture", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const result = await parseJson(response, ({ headers, status }) => {
    const contentType = headers.get("Content-Type") || "unknown content type";
    return `Fixture control returned ${contentType} instead of JSON (${status}). Restart lswebui and reload this page.`;
  });
  if (!response.ok) throw new Error(result.error || `Request failed (${response.status})`);
  return result;
}
