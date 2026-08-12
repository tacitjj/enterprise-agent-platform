import { apiDataSource } from "./apiDataSource.js";

export const DATA_SOURCE_MODE = Object.freeze({
  PROTOTYPE: "prototype",
  API: "api",
});

function runtimeEnvironment() {
  return import.meta.env ?? {};
}

export function resolveDataSourceMode(environment = runtimeEnvironment()) {
  const configuredMode = environment.VITE_DATA_SOURCE;
  const production = environment.PROD === true || environment.MODE === "production";
  if ((configuredMode === undefined || String(configuredMode).trim() === "") && production) {
    throw new Error("VITE_DATA_SOURCE must be explicitly set for production builds");
  }
  const mode = String(configuredMode ?? DATA_SOURCE_MODE.PROTOTYPE).trim().toLowerCase();
  if (!Object.values(DATA_SOURCE_MODE).includes(mode)) {
    throw new Error(`Unsupported VITE_DATA_SOURCE: ${mode}`);
  }
  return mode;
}

export function selectDataSource({
  mode = resolveDataSourceMode(),
  apiSource = apiDataSource,
  prototypeSource,
} = {}) {
  const normalizedMode = String(mode).trim().toLowerCase();
  if (normalizedMode === DATA_SOURCE_MODE.API) return apiSource;
  if (normalizedMode !== DATA_SOURCE_MODE.PROTOTYPE) {
    throw new Error(`Unsupported data source mode: ${normalizedMode}`);
  }
  if (!prototypeSource) {
    throw new Error("prototypeSource is required when VITE_DATA_SOURCE=prototype");
  }
  return prototypeSource;
}
