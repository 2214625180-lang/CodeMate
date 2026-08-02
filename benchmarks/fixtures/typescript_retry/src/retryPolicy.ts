export interface RetryPolicy {
  maxRetries: number;
  retryableCodes: ReadonlySet<string>;
}

export const paymentRetryPolicy: RetryPolicy = {
  maxRetries: 2,
  retryableCodes: new Set(["ETIMEDOUT", "ECONNRESET"])
};
