const DEFAULT_REQUEST_TIMEOUT_MS = 5000;

export function readRequestTimeout(env) {
  const configured = Number(env.REQUEST_TIMEOUT_MS ?? DEFAULT_REQUEST_TIMEOUT_MS);
  if (!Number.isFinite(configured)) {
    return DEFAULT_REQUEST_TIMEOUT_MS;
  }
  return configured;
}

export function loadServerConfig(env) {
  return {
    port: Number(env.PORT ?? 3000),
    requestTimeoutMs: readRequestTimeout(env)
  };
}
