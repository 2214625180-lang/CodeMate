import { loadServerConfig } from "./config.js";

export function createServerOptions(env) {
  const config = loadServerConfig(env);
  return {
    port: config.port,
    headersTimeout: config.requestTimeoutMs
  };
}
