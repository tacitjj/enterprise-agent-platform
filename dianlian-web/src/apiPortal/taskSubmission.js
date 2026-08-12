const RETRYABLE_CODES = new Set(["NETWORK_ERROR", "REQUEST_TIMEOUT"]);

export function fingerprintTaskPayload(payload) {
  return JSON.stringify(payload);
}

export function prepareStableTaskSubmission(dataSource, payload, { previous } = {}) {
  const fingerprint = fingerprintTaskPayload(payload);
  if (previous?.fingerprint === fingerprint && previous.completed !== true) return previous;
  return {
    fingerprint,
    command: dataSource.prepareCreateTask(payload),
    completed: false,
  };
}

export async function executeStableTaskSubmission(submission, { signal, maxAttempts = 2 } = {}) {
  let attempt = 0;
  while (attempt < maxAttempts) {
    attempt += 1;
    try {
      const result = await submission.command.execute({ signal });
      submission.completed = true;
      return result;
    } catch (error) {
      const retryable = error?.retryable === true || RETRYABLE_CODES.has(error?.code);
      if (!retryable || attempt >= maxAttempts || signal?.aborted) throw error;
    }
  }
  throw new Error("Task submission attempts exhausted");
}
