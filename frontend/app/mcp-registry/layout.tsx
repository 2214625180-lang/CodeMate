import { EvaluationAdminGate } from "@/app/evaluations/EvaluationAdminGate";

export default function MCPRegistryLayout({ children }: { children: React.ReactNode }) {
  return <EvaluationAdminGate label="MCP 服务注册">{children}</EvaluationAdminGate>;
}
