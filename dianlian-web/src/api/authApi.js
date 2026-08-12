import {
  clearAccessToken,
  configureUnauthorizedHandler,
  setAccessToken,
} from "./accessTokenStore.js";
import { createHttpClient } from "./httpClient.js";

export function createAuthApi(client = createHttpClient({ credentials: "include" })) {
  const acceptToken = (response) => {
    const token = String(response?.accessToken ?? "").trim();
    if (!token) throw new TypeError("Authentication response did not include accessToken");
    setAccessToken(token);
    return response;
  };

  return Object.freeze({
    async login({ username, password, clientType = "WEB", deviceId = null, deviceName = null }, { signal } = {}) {
      const response = await client.post("/auth/login", {
        json: { username, password, clientType, deviceId, deviceName },
        signal,
        retryUnauthorized: false,
      });
      return acceptToken(response);
    },
    async refresh({ refreshToken = null } = {}, { signal } = {}) {
      const response = await client.post("/auth/refresh", {
        json: refreshToken ? { refreshToken } : {},
        signal,
        retryUnauthorized: false,
      });
      return acceptToken(response);
    },
    async logout({ signal } = {}) {
      try {
        await client.post("/auth/logout", { signal, retryUnauthorized: false });
      } finally {
        clearAccessToken();
      }
    },
  });
}

export const authApi = createAuthApi();
configureUnauthorizedHandler(async () => (await authApi.refresh()).accessToken);
