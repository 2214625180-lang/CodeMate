import { EvaluationAdminGate } from "@/app/evaluations/EvaluationAdminGate";

export default function MCPRegistryLayout({ children }: { children: React.ReactNode }) {
  return <EvaluationAdminGate label="MCP Registry">{children}</EvaluationAdminGate>;
}
