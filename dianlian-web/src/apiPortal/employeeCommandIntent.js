export function fingerprintEmployeeCommand(payload) {
  return JSON.stringify(payload);
}

export function prepareStableEmployeeCommand(previous, {
  prefix,
  payload,
  randomUUID = globalThis.crypto?.randomUUID?.bind(globalThis.crypto),
}) {
  const fingerprint = fingerprintEmployeeCommand(payload);
  if (previous?.fingerprint === fingerprint) return previous;
  if (typeof randomUUID !== "function") throw new Error("crypto.randomUUID is required to create idempotency keys");
  return {
    fingerprint,
    key: `${prefix}:${randomUUID()}`,
  };
}
