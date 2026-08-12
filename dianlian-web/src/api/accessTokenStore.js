let accessToken = null;
let unauthorizedHandler = null;
let refreshInFlight = null;

export function getAccessToken() {
  return accessToken;
}

export function setAccessToken(value) {
  const normalized = String(value ?? "").trim();
  if (!normalized) throw new TypeError("accessToken is required");
  accessToken = normalized;
}

export function clearAccessToken() {
  accessToken = null;
}

export function configureUnauthorizedHandler(handler) {
  if (handler !== null && typeof handler !== "function") {
    throw new TypeError("unauthorizedHandler must be a function or null");
  }
  unauthorizedHandler = handler;
}

export async function recoverUnauthorizedSession() {
  if (!unauthorizedHandler) return false;
  if (!refreshInFlight) {
    refreshInFlight = Promise.resolve()
      .then(() => unauthorizedHandler())
      .then((token) => {
        if (!token) return false;
        setAccessToken(token);
        return true;
      })
      .catch(() => {
        clearAccessToken();
        return false;
      })
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}
