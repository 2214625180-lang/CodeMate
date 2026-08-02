export async function withRetry(operation, maxRetries) {
  let attempt = 0;
  while (attempt <= maxRetries) {
    try {
      return await operation();
    } catch (error) {
      attempt += 1;
      if (attempt >= maxRetries) {
        throw error;
      }
    }
  }
  throw new Error("retry loop terminated unexpectedly");
}
