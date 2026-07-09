import { EvaluationAdminGate } from "./EvaluationAdminGate";

export default function EvaluationsLayout({ children }: { children: React.ReactNode }) {
  return <EvaluationAdminGate>{children}</EvaluationAdminGate>;
}
