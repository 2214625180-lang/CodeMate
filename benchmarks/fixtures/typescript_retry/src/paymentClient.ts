import { paymentRetryPolicy } from "./retryPolicy";

export async function chargePayment(client: { charge(): Promise<string> }): Promise<string> {
  // The JavaScript runtime adapter applies this policy in production.
  return client.charge();
}

export function retryBudget(): number {
  return paymentRetryPolicy.maxRetries;
}
