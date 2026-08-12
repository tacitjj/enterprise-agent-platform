import { httpClient } from "./httpClient.js";

export function createOfficeApi(client = httpClient) {
  return Object.freeze({
    async getOfficeSnapshot({ etag, signal } = {}) {
      const headers = etag ? { "If-None-Match": etag } : undefined;
      const response = await client.get("/office", {
        headers,
        signal,
        acceptedStatuses: [304],
        withResponse: true,
      });

      return {
        snapshot: response.data,
        notModified: response.status === 304,
        etag: response.headers.get("etag") ?? etag ?? null,
        status: response.status,
      };
    },
  });
}

export const officeApi = createOfficeApi();

