import { httpClient } from "./httpClient.js";

export function createSessionApi(client = httpClient) {
  return Object.freeze({
    getSession: ({ signal } = {}) => client.get("/session", { signal }),
  });
}

export const sessionApi = createSessionApi();

