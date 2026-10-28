import { t } from "./i18n.js";

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

export function postJson(url, body, timeoutMs, signal) {
  const init = { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  return request(url, init, timeoutMs, signal);
}

export function getJson(url, timeoutMs, signal) {
  return request(url, {}, timeoutMs, signal);
}

// A caller's own abort (a newer search replacing an older one) surfaces as AbortError for it to
// ignore; running out of time is a failure the user should see.
async function request(url, init, timeoutMs, signal) {
  const timeout = AbortSignal.timeout(timeoutMs);
  try {
    const response = await fetch(url, { ...init, signal: signal ? AbortSignal.any([signal, timeout]) : timeout });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new ApiError(response.status, typeof payload.detail === "string" ? payload.detail : `HTTP ${response.status}`);
    }
    return payload;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (signal?.aborted) throw error;
    throw new ApiError(0, timeout.aborted ? t("network.timeout") : t("network.offline"));
  }
}
