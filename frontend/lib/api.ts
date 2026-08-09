import type {
  AgentRun,
  CIConfig,
  CodeFile,
  EvaluationDataset,
  EvaluationDatasetPayload,
  EvaluationDatasetSnapshot,
  EvaluationGateResult,
  EvaluationHistory,
  EvaluationHistoryFilters,
  EvaluationRunArtifact,
  EvaluationRunCompare,
  EvaluationRun,
  EvaluationSnapshotBackfillRequest,
  EvaluationSnapshotBackfillResult,
  FixEvaluationRunRequest,
  FileContent,
  FixResponse,
  MCPComplianceReport,
  MCPOperationsOverview,
  MCPToolApproval,
  MCPToolExecution,
  MCPServerHealth,
  MCPRegistryCredential,
  MCPRegistryRevision,
  MCPRegistryServer,
  MCPAccessGrant,
  MCPDelegatedIdentity,
  MCPDelegatedProvider,
  MCPQuotaOverview,
  MCPQuotaPolicy,
  MCPTenant,
  MCPTenantBinding,
  MCPTenantMembership,
  RepoMemory,
  Repository,
  RepositoryStatusResponse,
  RetrievalEvaluationRunRequest,
  ReviewResponse,
  SecurityAuditDeliveryStatus
} from "./types";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(backendApiUrl(path), {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers ?? {})
    },
    cache: "no-store"
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed with status ${response.status}`);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export function backendApiUrl(path: string): string {
  if (!path.startsWith("/")) {
    throw new Error("Backend API paths must start with '/'");
  }
  return `/api/backend${path}`;
}

export function listRepositories(): Promise<Repository[]> {
  return request<Repository[]>("/repos");
}

export function createRepository(repoUrl: string): Promise<Repository> {
  return request<Repository>("/repos", {
    method: "POST",
    body: JSON.stringify({ repo_url: repoUrl })
  });
}

export function getRepository(repoId: string): Promise<Repository> {
  return request<Repository>(`/repos/${repoId}`);
}

export function getRepositoryStatus(repoId: string): Promise<RepositoryStatusResponse> {
  return request<RepositoryStatusResponse>(`/repos/${repoId}/status`);
}

export function getRepoMemory(repoId: string): Promise<RepoMemory> {
  return request<RepoMemory>(`/repos/${repoId}/memory`);
}

export function refreshRepoMemory(repoId: string): Promise<RepoMemory> {
  return request<RepoMemory>(`/repos/${repoId}/memory/refresh`, {
    method: "POST"
  });
}

export function inspectCI(repoId: string): Promise<CIConfig> {
  return request<CIConfig>(`/repos/${repoId}/ci`);
}

export function writeCIWorkflow(repoId: string): Promise<CIConfig> {
  return request<CIConfig>(`/repos/${repoId}/ci/workflow`, {
    method: "POST"
  });
}

export function reindexRepository(repoId: string, full = false): Promise<Repository> {
  return request<Repository>(`/repos/${repoId}/reindex?full=${String(full)}`, {
    method: "POST"
  });
}

export function listRepositoryFiles(repoId: string): Promise<CodeFile[]> {
  return request<CodeFile[]>(`/repos/${repoId}/files`);
}

export function getFileContent(
  repoId: string,
  path: string,
  startLine?: number | null,
  endLine?: number | null
): Promise<FileContent> {
  const params = new URLSearchParams({ path });
  if (startLine) {
    params.set("start_line", String(startLine));
  }
  if (endLine) {
    params.set("end_line", String(endLine));
  }
  return request<FileContent>(`/repos/${repoId}/files/content?${params.toString()}`);
}

export function createFixRun(
  repoId: string,
  issue: string,
  testCommand?: string,
  delegatedIdentity?: { identityId: string; delegationToken: string }
): Promise<FixResponse> {
  const delegatedIdentityId = delegatedIdentity?.identityId.trim() || null;
  const delegationToken = delegatedIdentity?.delegationToken.trim() || null;
  const canDelegate = delegatedIdentityId !== null && delegationToken !== null;
  return request<FixResponse>(`/repos/${repoId}/fix`, {
    method: "POST",
    body: JSON.stringify({
      issue,
      test_command: testCommand?.trim() || null,
      delegated_identity_id: canDelegate ? delegatedIdentityId : null,
      delegation_token: canDelegate ? delegationToken : null
    })
  });
}

export function reviewRepository(
  repoId: string,
  payload: {
    diff?: string;
    base_ref?: string;
    head_ref?: string;
    question?: string;
  }
): Promise<ReviewResponse> {
  return request<ReviewResponse>(`/repos/${repoId}/review`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getRun(runId: string): Promise<AgentRun> {
  return request<AgentRun>(`/runs/${runId}`);
}

export function submitRunFeedback(
  runId: string,
  status: "accepted" | "rejected" | "modified",
  note?: string
): Promise<{ run_id: string; feedback_status: string; feedback_note: string | null }> {
  return request(`/runs/${runId}/feedback`, {
    method: "POST",
    body: JSON.stringify({ status, note: note?.trim() || null })
  });
}

export function listRunMCPApprovals(runId: string): Promise<MCPToolApproval[]> {
  return request<MCPToolApproval[]>(`/mcp-approvals/runs/${runId}`);
}

export function decideMCPApproval(
  approvalId: string,
  decision: "approve" | "reject",
  expectedVersion: number,
  note?: string
): Promise<MCPToolApproval> {
  return request<MCPToolApproval>(`/mcp-approvals/${approvalId}/decision`, {
    method: "POST",
    body: JSON.stringify({
      decision,
      expected_version: expectedVersion,
      note: note?.trim() || null
    })
  });
}

export function listRunMCPExecutions(runId: string): Promise<MCPToolExecution[]> {
  return request<MCPToolExecution[]>(`/mcp-executions/runs/${runId}`);
}

export function reconcileMCPExecution(
  executionId: string,
  action: "confirm_succeeded" | "confirm_failed" | "retry",
  expectedVersion: number,
  note?: string
): Promise<{ execution: MCPToolExecution; job_id: string | null }> {
  return request(`/mcp-executions/${executionId}/reconcile`, {
    method: "POST",
    body: JSON.stringify({
      action,
      expected_version: expectedVersion,
      note: note?.trim() || null
    })
  });
}

export function getMCPOperationsOverview(
  windowMinutes = 60
): Promise<MCPOperationsOverview> {
  return request(`/mcp-operations/overview?window_minutes=${String(windowMinutes)}`);
}

export function getSecurityAuditDeliveryStatus(): Promise<SecurityAuditDeliveryStatus> {
  return request("/mcp-operations/security-audit");
}

export function deliverSecurityAuditNow(): Promise<Record<string, number>> {
  return request("/mcp-operations/security-audit/deliver", { method: "POST" });
}

export function requeueSecurityAuditDeadLetters(): Promise<{ requeued: number }> {
  return request("/mcp-operations/security-audit/requeue-dead-letters", { method: "POST" });
}

export function getMCPComplianceReport(): Promise<MCPComplianceReport> {
  return request("/mcp-operations/compliance/latest");
}

export function scanMCPCompliance(): Promise<{ job_id: string }> {
  return request("/mcp-operations/compliance/scan", { method: "POST" });
}

export function probeMCPServers(serverName?: string): Promise<{ job_id: string }> {
  const path = serverName
    ? `/mcp-operations/servers/${encodeURIComponent(serverName)}/probe`
    : "/mcp-operations/probes";
  return request(path, { method: "POST" });
}

export function controlMCPCircuit(
  serverName: string,
  action: "open" | "close" | "reset",
  expectedVersion: number
): Promise<MCPServerHealth> {
  return request(`/mcp-operations/servers/${encodeURIComponent(serverName)}/circuit`, {
    method: "POST",
    body: JSON.stringify({ action, expected_version: expectedVersion })
  });
}

export function listMCPRegistryServers(): Promise<MCPRegistryServer[]> {
  return request("/mcp-registry/servers");
}

export function createMCPRegistryServer(payload: {
  name: string;
  url: string;
  enabled: boolean;
  allowed_tools: string[];
  tool_policies: Record<string, "auto" | "approval_required" | "deny">;
  idempotency_mode: "none" | "metadata";
}): Promise<MCPRegistryServer> {
  return request("/mcp-registry/servers", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function updateMCPRegistryServer(
  server: MCPRegistryServer,
  changes: Partial<Pick<MCPRegistryServer, "name" | "url" | "enabled" | "allowed_tools" | "tool_policies" | "idempotency_mode">>
): Promise<MCPRegistryServer> {
  return request(`/mcp-registry/servers/${server.id}`, {
    method: "PATCH",
    body: JSON.stringify({ ...changes, expected_version: server.version })
  });
}

export function deleteMCPRegistryServer(server: MCPRegistryServer): Promise<void> {
  return request(`/mcp-registry/servers/${server.id}`, {
    method: "DELETE",
    body: JSON.stringify({ expected_version: server.version })
  });
}

export function validateMCPRegistryServer(serverId: string): Promise<MCPRegistryServer> {
  return request(`/mcp-registry/servers/${serverId}/validate`, { method: "POST" });
}

export function setMCPRegistryCredential(
  serverId: string,
  payload: Record<string, unknown>
): Promise<MCPRegistryCredential> {
  return request(`/mcp-registry/servers/${serverId}/credential`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export function deleteMCPRegistryCredential(serverId: string): Promise<void> {
  return request(`/mcp-registry/servers/${serverId}/credential`, { method: "DELETE" });
}

export function listMCPRegistryRevisions(serverId: string): Promise<MCPRegistryRevision[]> {
  return request(`/mcp-registry/servers/${serverId}/revisions`);
}

export function restoreMCPRegistryRevision(
  server: MCPRegistryServer,
  revisionId: string
): Promise<MCPRegistryServer> {
  return request(`/mcp-registry/servers/${server.id}/revisions/${revisionId}/restore`, {
    method: "POST",
    body: JSON.stringify({ expected_version: server.version })
  });
}

export function listMCPTenants(): Promise<MCPTenant[]> {
  return request("/mcp-tenancy/tenants");
}

export function createMCPTenant(slug: string, name: string): Promise<MCPTenant> {
  return request("/mcp-tenancy/tenants", {
    method: "POST",
    body: JSON.stringify({ slug, name })
  });
}

export function rotateMCPTenantClientToken(
  tenantId: string
): Promise<{ tenant_id: string; client_token: string }> {
  return request(`/mcp-tenancy/tenants/${tenantId}/client-token`, { method: "POST" });
}

export function assignRepositoryToMCPTenant(tenantId: string, repoId: string): Promise<void> {
  return request(`/mcp-tenancy/tenants/${tenantId}/repositories/${repoId}`, { method: "PUT" });
}

export function listMCPTenantMemberships(tenantId: string): Promise<MCPTenantMembership[]> {
  return request(`/mcp-tenancy/tenants/${tenantId}/memberships`);
}

export function createMCPTenantMembership(
  tenantId: string,
  payload: Omit<MCPTenantMembership, "id">
): Promise<MCPTenantMembership> {
  return request(`/mcp-tenancy/tenants/${tenantId}/memberships`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function listMCPTenantBindings(tenantId: string): Promise<MCPTenantBinding[]> {
  return request(`/mcp-tenancy/tenants/${tenantId}/bindings`);
}

export function bindMCPTenantServer(
  tenantId: string,
  serverName: string,
  enabled = true
): Promise<MCPTenantBinding> {
  return request(`/mcp-tenancy/tenants/${tenantId}/bindings`, {
    method: "POST",
    body: JSON.stringify({ server_name: serverName, enabled })
  });
}

export function listMCPAccessGrants(tenantId: string): Promise<MCPAccessGrant[]> {
  return request(`/mcp-tenancy/tenants/${tenantId}/grants`);
}

export function createMCPAccessGrant(
  tenantId: string,
  payload: Omit<MCPAccessGrant, "id">
): Promise<MCPAccessGrant> {
  return request(`/mcp-tenancy/tenants/${tenantId}/grants`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function deleteMCPAccessGrant(grantId: string): Promise<void> {
  return request(`/mcp-tenancy/grants/${grantId}`, { method: "DELETE" });
}

export function listMCPDelegatedProviders(tenantId: string): Promise<MCPDelegatedProvider[]> {
  return request(`/mcp-tenancy/tenants/${tenantId}/oauth/providers`);
}

export function configureMCPDelegatedProvider(
  tenantId: string,
  payload: Record<string, unknown>
): Promise<MCPDelegatedProvider> {
  return request(`/mcp-tenancy/tenants/${tenantId}/oauth/providers`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function startMCPDelegatedAuthorization(
  providerId: string
): Promise<{ authorization_url: string }> {
  return request(`/mcp-tenancy/oauth/providers/${providerId}/authorize`, { method: "POST" });
}

export function listMCPDelegatedIdentities(tenantId: string): Promise<MCPDelegatedIdentity[]> {
  return request(`/mcp-tenancy/tenants/${tenantId}/identities`);
}

export function revokeMCPDelegatedIdentity(identityId: string): Promise<MCPDelegatedIdentity> {
  return request(`/mcp-tenancy/identities/${identityId}/revoke`, { method: "POST" });
}

export function listMCPQuotaPolicies(tenantId: string): Promise<MCPQuotaPolicy[]> {
  return request(`/mcp-quotas/tenants/${tenantId}/policies`);
}

export function createMCPQuotaPolicy(
  tenantId: string,
  payload: Record<string, unknown>
): Promise<MCPQuotaPolicy> {
  return request(`/mcp-quotas/tenants/${tenantId}/policies`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function updateMCPQuotaPolicy(
  policy: MCPQuotaPolicy,
  changes: Record<string, unknown>
): Promise<MCPQuotaPolicy> {
  return request(`/mcp-quotas/policies/${policy.id}`, {
    method: "PATCH",
    body: JSON.stringify({ ...changes, expected_version: policy.version })
  });
}

export function disableMCPQuotaPolicy(policyId: string): Promise<void> {
  return request(`/mcp-quotas/policies/${policyId}`, { method: "DELETE" });
}

export function resetMCPQuotaPolicy(policy: MCPQuotaPolicy): Promise<MCPQuotaPolicy> {
  return request(`/mcp-quotas/policies/${policy.id}/reset`, {
    method: "POST",
    body: JSON.stringify({ expected_version: policy.version })
  });
}

export function temporarilyAdjustMCPQuotaPolicy(
  policy: MCPQuotaPolicy,
  overrides: Record<string, number>,
  durationSeconds: number
): Promise<MCPQuotaPolicy> {
  return request(`/mcp-quotas/policies/${policy.id}/temporary-adjustment`, {
    method: "POST",
    body: JSON.stringify({
      ...overrides,
      duration_seconds: durationSeconds,
      expected_version: policy.version
    })
  });
}

export function getMCPQuotaOverview(
  tenantId: string,
  windowDays = 1
): Promise<MCPQuotaOverview> {
  return request(`/mcp-quotas/tenants/${tenantId}/overview?window_days=${windowDays}`);
}

export function reconcileMCPQuotaUsage(
  tenantId: string,
  repair = false
): Promise<Record<string, unknown>> {
  return request(`/mcp-quotas/tenants/${tenantId}/reconcile`, {
    method: "POST",
    body: JSON.stringify({ repair })
  });
}

export function applyMCPQuotaRetention(
  tenantId: string,
  retentionDays: number,
  dryRun: boolean
): Promise<{ events: number; rejections: number; dry_run: boolean }> {
  return request(`/mcp-quotas/tenants/${tenantId}/retention`, {
    method: "POST",
    body: JSON.stringify({ retention_days: retentionDays, dry_run: dryRun })
  });
}

export function listEvaluationRuns(limit = 20): Promise<EvaluationRun[]> {
  return request<EvaluationRun[]>(`/evaluations?limit=${String(limit)}`);
}

export function getEvaluationRun(evaluationRunId: string): Promise<EvaluationRun> {
  return request<EvaluationRun>(`/evaluations/${evaluationRunId}`);
}

export function getEvaluationRunArtifact(
  evaluationRunId: string,
  options?: { includeAgentSteps?: boolean; maxPayloadChars?: number }
): Promise<EvaluationRunArtifact> {
  const params = new URLSearchParams({
    include_agent_steps: String(options?.includeAgentSteps ?? true),
    max_payload_chars: String(options?.maxPayloadChars ?? 12000)
  });
  return request<EvaluationRunArtifact>(`/evaluations/${evaluationRunId}/artifact?${params}`);
}

export function compareEvaluationRuns(
  baselineRunId: string,
  candidateRunId: string
): Promise<EvaluationRunCompare> {
  const params = new URLSearchParams({
    baseline_run_id: baselineRunId,
    candidate_run_id: candidateRunId
  });
  return request<EvaluationRunCompare>(`/evaluations/compare?${params.toString()}`);
}

export function listEvaluationDatasets(taskType?: "retrieval" | "fix"): Promise<EvaluationDataset[]> {
  const query = taskType ? `?task_type=${taskType}` : "";
  return request<EvaluationDataset[]>(`/evaluations/datasets${query}`);
}

export function getEvaluationDataset(datasetId: string): Promise<EvaluationDataset> {
  return request<EvaluationDataset>(`/evaluations/datasets/${datasetId}`);
}

export function listEvaluationDatasetSnapshots(
  datasetId: string
): Promise<EvaluationDatasetSnapshot[]> {
  return request<EvaluationDatasetSnapshot[]>(`/evaluations/datasets/${datasetId}/snapshots`);
}

export function getEvaluationDatasetSnapshot(
  snapshotId: string
): Promise<EvaluationDatasetSnapshot> {
  return request<EvaluationDatasetSnapshot>(`/evaluations/dataset-snapshots/${snapshotId}`);
}

export function backfillEvaluationDatasetSnapshots(
  datasetId: string,
  payload: EvaluationSnapshotBackfillRequest
): Promise<EvaluationSnapshotBackfillResult> {
  return request<EvaluationSnapshotBackfillResult>(
    `/evaluations/datasets/${datasetId}/snapshots/backfill`,
    {
      method: "POST",
      body: JSON.stringify(payload)
    }
  );
}

export function evaluateRegressionGate(
  datasetId: string,
  candidateRunId: string
): Promise<EvaluationGateResult> {
  const params = new URLSearchParams({ candidate_run_id: candidateRunId });
  return request<EvaluationGateResult>(`/evaluations/datasets/${datasetId}/gate?${params}`);
}

export function getEvaluationDatasetHistory(
  datasetId: string,
  filters: EvaluationHistoryFilters = {}
): Promise<EvaluationHistory> {
  const params = new URLSearchParams({ limit: String(filters.limit ?? 30) });
  if (filters.createdAfter) {
    params.set("created_after", filters.createdAfter);
  }
  if (filters.createdBefore) {
    params.set("created_before", filters.createdBefore);
  }
  if (filters.status) {
    params.set("status", filters.status);
  }
  if (filters.gateStatus) {
    params.set("gate_status", filters.gateStatus);
  }
  if (filters.provider?.trim()) {
    params.set("provider", filters.provider.trim());
  }
  if (filters.model?.trim()) {
    params.set("model", filters.model.trim());
  }
  return request<EvaluationHistory>(`/evaluations/datasets/${datasetId}/history?${params}`);
}

export function createEvaluationDataset(
  payload: EvaluationDatasetPayload
): Promise<EvaluationDataset> {
  return request<EvaluationDataset>("/evaluations/datasets", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function updateEvaluationDataset(
  datasetId: string,
  payload: Partial<EvaluationDatasetPayload>
): Promise<EvaluationDataset> {
  return request<EvaluationDataset>(`/evaluations/datasets/${datasetId}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export function deleteEvaluationDataset(datasetId: string): Promise<void> {
  return request<void>(`/evaluations/datasets/${datasetId}`, {
    method: "DELETE"
  });
}

export function runRetrievalEvaluation(
  payload: RetrievalEvaluationRunRequest
): Promise<EvaluationRun> {
  return request<EvaluationRun>("/evaluations/retrieval", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function runFixEvaluation(payload: FixEvaluationRunRequest): Promise<EvaluationRun> {
  return request<EvaluationRun>("/evaluations/fix", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}
