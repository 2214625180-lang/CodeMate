import { EvaluationAdminGate } from "@/app/evaluations/EvaluationAdminGate";

export default function MCPOperationsLayout({ children }: { children: React.ReactNode }) {
  return <EvaluationAdminGate label="MCP 运维">{children}</EvaluationAdminGate>;
}
