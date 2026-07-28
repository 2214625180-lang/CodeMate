export type RepositoryStatus =
  | "pending"
  | "cloning"
  | "parsing"
  | "embedding"
  | "indexed"
  | "failed";

export type Repository = {
  id: string;
  name: string;
  tenant_id: string | null;
  repo_url: string;
  local_path: string | null;
  status: RepositoryStatus;
  error_message: string | null;
  language_summary: Record<string, number>;
  last_commit_hash: string | null;
  file_count: number;
  chunk_count: number;
  indexed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type RepositoryStatusResponse = {
  id: string;
  status: RepositoryStatus;
  error_message: string | null;
  file_count: number;
  chunk_count: number;
};

export type CodeFile = {
  id: string;
  file_path: string;
  language: string;
  content_hash: string;
  line_count: number;
  size_bytes: number;
  imports: string[];
  exports: string[];
};

export type FileContent = {
  file_path: string;
  language: string | null;
  start_line: number;
  end_line: number;
  content: string;
};

export type CodeCitation = {
  chunk_id: string;
  repo_id: string | null;
  repo_name: string | null;
  file_path: string;
  start_line: number | null;
  end_line: number | null;
  symbol_name: string | null;
  symbol_type: string | null;
};

export type ReviewFinding = {
  severity: "info" | "low" | "medium" | "high";
  file_path: string | null;
  start_line: number | null;
  end_line: number | null;
  title: string;
  body: string;
  suggestion: string | null;
};

export type ReviewResponse = {
  summary: string;
  changed_files: string[];
  findings: ReviewFinding[];
  citations: CodeCitation[];
};

export type RepoMemory = {
  repo_id: string;
  summary: string | null;
  data: {
    modules?: { path: string; file_count: number }[];
    key_files?: { path: string; language: string; lines: number; size_bytes: number }[];
    dependencies?: { frameworks?: string[]; dependencies?: string[] };
    symbols?: { name: string; type: string | null; path: string; lines: (number | null)[] }[];
    [key: string]: unknown;
  };
  updated_at: string | null;
};

export type CIConfig = {
  repo_id: string;
  detected_configs: string[];
  ecosystem: string[];
  package_manager: string | null;
  test_commands: string[];
  workflow_path: string;
  workflow_yaml: string;
  applied_path: string | null;
};

export type AgentRunStatus =
  | "pending"
  | "running"
  | "waiting_approval"
  | "waiting_reconciliation"
  | "success"
  | "failed";

export type MCPToolApproval = {
  id: string;
  run_id: string;
  qualified_name: string;
  server_name: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  arguments_hash: string;
  policy_snapshot: string;
  status: string;
  decision: string | null;
  decision_note: string | null;
  decided_by: string | null;
  decided_provider: string | null;
  version: number;
  requested_at: string;
  expires_at: string;
  decided_at: string | null;
  execution_started_at: string | null;
  execution_finished_at: string | null;
  result: Record<string, unknown> | null;
  error_message: string | null;
};

export type MCPToolExecution = {
  id: string;
  run_id: string;
  approval_id: string | null;
  qualified_name: string;
  server_name: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  arguments_hash: string;
  idempotency_key: string;
  idempotency_mode: string;
  status: string;
  attempt_count: number;
  recovery_count: number;
  deduplication_hits: number;
  retry_safe: boolean;
  lease_owner: string | null;
  lease_expires_at: string | null;
  result: Record<string, unknown> | null;
  error_message: string | null;
  reconciliation_note: string | null;
  reconciled_by: string | null;
  reconciled_provider: string | null;
  version: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  reconciled_at: string | null;
  updated_at: string;
};

export type MCPServerHealth = {
  server_name: string;
  public_url: string | null;
  operational_status: "healthy" | "unhealthy" | "unknown";
  circuit_state: "closed" | "open" | "half_open";
  manual_open: boolean;
  consecutive_failures: number;
  total_requests: number;
  total_transport_successes: number;
  total_transport_failures: number;
  circuit_rejections: number;
  circuit_open_count: number;
  total_probes: number;
  failed_probes: number;
  last_probe_status: string;
  last_probe_at: string | null;
  last_success_at: string | null;
  last_failure_at: string | null;
  last_latency_ms: number | null;
  last_error: string | null;
  protocol_version: string | null;
  server_info: Record<string, unknown> | null;
  opened_at: string | null;
  cooldown_until: string | null;
  version: number;
  updated_at: string;
};

export type MCPOperationsAlert = {
  severity: "warning" | "critical";
  type: string;
  server_name: string;
  execution_id?: string;
  message: string;
};

export type MCPOperationsOverview = {
  generated_at: string;
  window_minutes: number;
  summary: {
    executions: number;
    succeeded: number;
    failed: number;
    unknown: number;
    executing: number;
    deduplication_hits: number;
    recovery_count: number;
    pending_approvals: number;
    open_circuits: number;
    unhealthy_servers: number;
    requests_per_minute: number;
  };
  latency_ms: { p50: number; p95: number; p99: number };
  servers: MCPServerHealth[];
  per_server: Array<{
    server_name: string;
    calls: number;
    succeeded: number;
    failed: number;
    unknown: number;
    error_rate: number;
    latency_ms: { p50: number; p95: number; p99: number };
  }>;
  per_tool: Array<{
    qualified_name: string;
    calls: number;
    succeeded: number;
    failed: number;
    unknown: number;
    latency_ms: { p50: number; p95: number; p99: number };
  }>;
  alerts: MCPOperationsAlert[];
  recent_executions: Array<{
    id: string;
    run_id: string;
    approval_id: string | null;
    qualified_name: string;
    server_name: string;
    tool_name: string;
    arguments: Record<string, unknown>;
    status: string;
    attempt_count: number;
    recovery_count: number;
    deduplication_hits: number;
    retry_safe: boolean;
    error_message: string | null;
    created_at: string;
    started_at: string | null;
    finished_at: string | null;
    updated_at: string;
    latency_ms: number | null;
  }>;
};

export type SecurityAuditDeliveryStatus = {
  event_id: string | null;
  configured_sinks: string[];
  counts: Record<string, number>;
  oldest_undelivered_seconds: number;
  deliveries: Array<{
    id: string;
    event_id: string;
    sink: string;
    payload_sha256: string;
    status: string;
    attempt_count: number;
    delivered_at: string | null;
    remote_receipt: Record<string, unknown> | null;
    last_error: string | null;
    created_at: string;
  }>;
};

export type MCPComplianceReport = {
  schema_version: number;
  generated_at?: string;
  environment?: string;
  status: "compliant" | "non_compliant" | "missing";
  report_sha256?: string;
  controls: Array<{
    id: string;
    title: string;
    status: "passed" | "failed";
    evidence: Record<string, unknown>;
  }>;
};

export type MCPRegistryCredential = {
  id: string;
  auth_type: "bearer" | "oauth2_client_credentials";
  key_version: number;
  encryption_provider: "aws" | "local" | "legacy" | "invalid";
  kms_key_id: string;
  expires_at: string | null;
  last_refreshed_at: string | null;
  last_error: string | null;
  version: number;
  created_at: string;
  updated_at: string;
};

export type MCPRegistryServer = {
  id: string;
  name: string;
  url: string;
  enabled: boolean;
  allowed_tools: string[];
  tool_policies: Record<string, "auto" | "approval_required" | "deny">;
  agent_context_tools: Array<Record<string, unknown>>;
  idempotency_mode: "none" | "metadata";
  validation_status: "unvalidated" | "valid" | "invalid";
  validation_error: string | null;
  protocol_version: string | null;
  server_info: Record<string, unknown> | null;
  capabilities: Record<string, unknown> | null;
  tools_snapshot: Array<Record<string, unknown>> | null;
  validated_at: string | null;
  credential: MCPRegistryCredential | null;
  version: number;
  created_by: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
};

export type MCPRegistryRevision = {
  id: string;
  version: number;
  action: string;
  snapshot: Record<string, unknown>;
  actor: string;
  created_at: string;
};

export type MCPTenant = {
  id: string;
  slug: string;
  name: string;
  has_client_token: boolean;
};

export type MCPTenantMembership = {
  id: string;
  provider: string;
  subject: string;
  role: "admin" | "approver" | "member";
};

export type MCPTenantBinding = {
  id: string;
  server_name: string;
  enabled: boolean;
};

export type MCPAccessGrant = {
  id: string;
  repo_id: string | null;
  principal_type: "user" | "role" | "service" | "agent" | "*";
  principal_id: string;
  server_name: string;
  tool_name: string;
  permissions: Array<"discover" | "execute" | "approve">;
  effect: "allow" | "deny";
  expires_at: string | null;
};

export type MCPDelegatedProvider = {
  id: string;
  tenant_id: string;
  server_name: string;
  authorization_url: string;
  token_url: string;
  client_id: string;
  has_client_secret: boolean;
  scopes: string[];
  redirect_uri: string;
  version: number;
};

export type MCPDelegatedIdentity = {
  id: string;
  tenant_id: string;
  server_name: string;
  subject_provider: string;
  subject: string;
  scopes: string[];
  expires_at: string | null;
  revoked: boolean;
  version: number;
  created_at: string;
  updated_at: string;
};

export type MCPQuotaPolicy = {
  id: string;
  tenant_id: string;
  repo_id: string | null;
  principal_type: "user" | "role" | "service" | "agent" | "*";
  principal_id: string;
  server_name: string;
  tool_name: string;
  rate_limit_per_minute: number | null;
  daily_call_limit: number | null;
  daily_cost_limit: number | null;
  concurrent_limit: number | null;
  run_call_limit: number | null;
  max_run_duration_seconds: number | null;
  call_cost_units: number;
  warning_threshold: number;
  enabled: boolean;
  frozen: boolean;
  temporary_override: Record<string, number> | null;
  temporary_override_expires_at: string | null;
  reset_at: string | null;
  version: number;
  created_by: string;
  updated_by: string;
  created_at: string;
  updated_at: string;
};

export type MCPQuotaPolicyUsage = MCPQuotaPolicy & {
  effective_limits: {
    rate_limit_per_minute: number | null;
    daily_call_limit: number | null;
    daily_cost_limit: number | null;
    concurrent_limit: number | null;
    run_call_limit: number | null;
    max_run_duration_seconds: number | null;
    call_cost_units: number;
  };
  usage: {
    minute_calls: number;
    daily_calls: number;
    daily_cost: number;
    run_calls: number;
    active_concurrency: number;
    concurrency_retry_after: number | null;
  };
  utilization: number;
};

export type MCPQuotaOverview = {
  generated_at: string;
  window_days: number;
  summary: {
    calls: number;
    cost_units: number;
    rejections: number;
    active_concurrency: number;
    delegated_user_calls: number;
  };
  policies: MCPQuotaPolicyUsage[];
  per_server: Array<[string, number]>;
  per_tool: Array<[string, number]>;
  per_principal: Array<[string, number]>;
  alerts: Array<{
    severity: "warning" | "critical";
    type: string;
    policy_id?: string;
    message: string;
  }>;
  recent_rejections: Array<{
    id: string;
    policy_id: string | null;
    run_id: string | null;
    principal: string;
    server_name: string;
    tool_name: string;
    reason: string;
    retry_after_seconds: number | null;
    created_at: string;
  }>;
  recent_events: Array<{
    id: string;
    run_id: string | null;
    principal: string;
    server_name: string;
    tool_name: string;
    cost_units: number;
    status: string;
    delegated: boolean;
    created_at: string;
    released_at: string | null;
  }>;
};

export type AgentStep = {
  id: string;
  run_id: string;
  step_type: string;
  tool_name: string | null;
  input_json: unknown;
  output_json: unknown;
  duration_ms: number | null;
  created_at: string;
};

export type AgentRun = {
  id: string;
  repo_id: string;
  task_type: string;
  tenant_id: string | null;
  principal_type: string;
  principal_id: string;
  delegated_identity_id: string | null;
  user_input: string;
  test_command: string | null;
  status: AgentRunStatus;
  final_diff: string | null;
  final_summary: string | null;
  failure_reason: string | null;
  test_result: Record<string, unknown> | null;
  iterations: number;
  feedback_status: string | null;
  feedback_note: string | null;
  feedback_at: string | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
  steps: AgentStep[];
};

export type FixResponse = {
  run_id: string;
  status: AgentRunStatus;
};

export type RetrievalEvaluationCase = {
  case_id?: string | null;
  repo_id: string;
  question: string;
  expected_file: string;
  expected_lines?: Record<string, unknown> | unknown[] | null;
};

export type RetrievalEvaluationRunRequest = {
  name?: string | null;
  dataset_id?: string | null;
  dataset_version?: number | null;
  dataset_snapshot_id?: string | null;
  top_k?: number;
  cases: RetrievalEvaluationCase[];
};

export type FixEvaluationCase = {
  case_id?: string | null;
  repo_id: string;
  issue: string;
  test_command?: string | null;
  expected_status?: "success" | "failed";
  expected_diff_contains?: string[];
};

export type FixEvaluationRunRequest = {
  name?: string | null;
  dataset_id?: string | null;
  dataset_version?: number | null;
  dataset_snapshot_id?: string | null;
  require_tests_ran?: boolean;
  cases: FixEvaluationCase[];
};

export type EvaluationDataset = {
  id: string;
  name: string;
  task_type: "retrieval" | "fix";
  description: string | null;
  version: number;
  baseline_run_id: string | null;
  gate_policy_json: EvaluationGatePolicy;
  cases_json: Record<string, unknown>[];
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type EvaluationDatasetSnapshot = {
  id: string;
  dataset_id: string;
  name: string;
  task_type: "retrieval" | "fix";
  description: string | null;
  version: number;
  baseline_run_id: string | null;
  gate_policy_json: EvaluationGatePolicy;
  cases_json: Record<string, unknown>[];
  metadata_json: Record<string, unknown>;
  created_at: string;
};

export type EvaluationDatasetPayload = {
  name: string;
  task_type: "retrieval" | "fix";
  description?: string | null;
  version?: number;
  baseline_run_id?: string | null;
  gate_policy_json?: EvaluationGatePolicy;
  cases_json: Record<string, unknown>[];
  metadata_json?: Record<string, unknown>;
};

export type EvaluationSnapshotBackfillRequest = {
  run_id?: string | null;
  task_type?: "retrieval" | "fix" | null;
  limit?: number | null;
  dry_run?: boolean;
  create_missing_snapshots?: boolean;
  include_details?: boolean;
};

export type EvaluationSnapshotBackfillResult = {
  dry_run: boolean;
  scanned: number;
  backfilled: number;
  skipped: number;
  created_snapshots: number;
  status_counts: Record<string, number>;
  details: Record<string, unknown>[];
};

export type EvaluationResult = {
  id: string;
  evaluation_run_id: string | null;
  case_id: string | null;
  repo_id: string | null;
  task_type: "retrieval" | "fix";
  status: string | null;
  question: string | null;
  expected_file: string | null;
  expected_lines: Record<string, unknown> | unknown[] | null;
  result_json: Record<string, unknown> | unknown[] | null;
  passed: boolean | null;
  latency_ms: number | null;
  score: number | null;
  failure_category: string | null;
  agent_run_id: string | null;
  provider: string | null;
  model: string | null;
  metadata_json: Record<string, unknown>;
  created_at: string;
};

export type EvaluationRun = {
  id: string;
  name: string | null;
  task_type: "retrieval" | "fix";
  status: "running" | "completed" | "failed";
  dataset_id: string | null;
  dataset_version: number | null;
  dataset_snapshot_id: string | null;
  case_count: number;
  passed_count: number;
  failed_count: number;
  metrics_json: Record<string, unknown>;
  config_snapshot: Record<string, unknown>;
  request_json: Record<string, unknown>;
  created_at: string;
  finished_at: string | null;
  results: EvaluationResult[];
};

export type EvaluationHistoryRun = {
  id: string;
  name: string | null;
  task_type: "retrieval" | "fix";
  status: "running" | "completed" | "failed";
  dataset_version: number | null;
  dataset_snapshot_id: string | null;
  gate_status: "passed" | "failed" | "inconclusive" | "not_evaluated";
  primary_metric_name: string;
  primary_metric_value: number | null;
  primary_metric_delta: number | null;
  pass_rate: number | null;
  case_count: number;
  passed_count: number;
  failed_count: number;
  avg_latency_sec: number | null;
  avg_tool_calls: number | null;
  failure_distribution: Record<string, number>;
  regressions: number | null;
  improvements: number | null;
  provider: string | null;
  model: string | null;
  created_at: string;
  finished_at: string | null;
};

export type EvaluationHistoryFilters = {
  limit?: number;
  createdAfter?: string | null;
  createdBefore?: string | null;
  status?: "running" | "completed" | "failed" | null;
  gateStatus?: "passed" | "failed" | "inconclusive" | "not_evaluated" | null;
  provider?: string | null;
  model?: string | null;
};

export type EvaluationHistory = {
  dataset: EvaluationDataset;
  baseline_run_id: string | null;
  primary_metric_name: string;
  filters: Record<string, unknown>;
  summary: Record<string, unknown>;
  gate_status_counts: Record<string, number>;
  runs: EvaluationHistoryRun[];
};

export type EvaluationRunArtifact = {
  artifact_version: string;
  generated_at: string;
  run: {
    id: string;
    name: string | null;
    task_type: "retrieval" | "fix";
    status: "running" | "completed" | "failed";
    dataset_id: string | null;
    dataset_version: number | null;
    dataset_snapshot_id: string | null;
    case_count: number;
    passed_count: number;
    failed_count: number;
    metrics_json: Record<string, unknown>;
    config_snapshot: Record<string, unknown>;
    request_json: Record<string, unknown>;
    created_at: string;
    finished_at: string | null;
  };
  summary: Record<string, unknown>;
  cases: EvaluationArtifactCase[];
};

export type EvaluationArtifactCase = {
  evaluation_id: string;
  case_id: string | null;
  repo_id: string | null;
  task_type: "retrieval" | "fix";
  prompt: string | null;
  expected_file: string | null;
  expected_lines: Record<string, unknown> | unknown[] | null;
  status: string | null;
  passed: boolean | null;
  score: number | null;
  latency_ms: number | null;
  failure_category: string | null;
  provider: string | null;
  model: string | null;
  metadata_json: Record<string, unknown>;
  result_json: Record<string, unknown> | unknown[] | null;
  agent_trace: EvaluationArtifactAgentTrace | null;
};

export type EvaluationArtifactAgentTrace = {
  run_id: string;
  status: string;
  user_input: string;
  test_command: string | null;
  iterations: number;
  final_summary: string | null;
  failure_reason: string | null;
  test_result: Record<string, unknown> | null;
  steps_by_type: Record<string, number>;
  steps: {
    id: string;
    step_type: string;
    tool_name: string | null;
    input_json: Record<string, unknown> | unknown[] | null;
    output_json: Record<string, unknown> | unknown[] | null;
    duration_ms: number | null;
    created_at: string;
  }[];
};

export type EvaluationMetricDelta = {
  name: string;
  baseline: number | null;
  candidate: number | null;
  delta: number | null;
  percent_delta: number | null;
  direction: "higher_is_better" | "lower_is_better" | "neutral";
};

export type EvaluationCaseComparison = {
  case_id: string;
  status:
    | "regressed"
    | "improved"
    | "unchanged_pass"
    | "unchanged_fail"
    | "baseline_only"
    | "candidate_only";
  question: string | null;
  expected_file: string | null;
  baseline_passed: boolean | null;
  candidate_passed: boolean | null;
  baseline_status: string | null;
  candidate_status: string | null;
  baseline_failure_category: string | null;
  candidate_failure_category: string | null;
  baseline_latency_ms: number | null;
  candidate_latency_ms: number | null;
  latency_delta_ms: number | null;
  baseline_result: Record<string, unknown> | unknown[] | null;
  candidate_result: Record<string, unknown> | unknown[] | null;
};

export type EvaluationRunCompare = {
  baseline_run: EvaluationRun;
  candidate_run: EvaluationRun;
  compatible: boolean;
  compatibility_warnings: string[];
  verdict: "pass" | "regression" | "inconclusive";
  primary_metric: string;
  metric_deltas: EvaluationMetricDelta[];
  summary: Record<string, unknown>;
  failure_distribution_delta: Record<string, number>;
  case_comparisons: EvaluationCaseComparison[];
};

export type EvaluationGatePolicy = {
  max_primary_metric_drop: number;
  max_regressed_cases: number;
  allow_incompatible: boolean;
  require_matching_dataset_snapshot: boolean;
  max_avg_latency_increase_sec: number | null;
  max_avg_tool_call_increase: number | null;
};

export type EvaluationGateCheck = {
  name: string;
  passed: boolean | null;
  observed: number | string | boolean | null;
  threshold: number | string | boolean | null;
  message: string;
};

export type EvaluationGateResult = {
  dataset: EvaluationDataset;
  baseline_run: EvaluationRun;
  candidate_run: EvaluationRun;
  status: "passed" | "failed" | "inconclusive";
  policy: EvaluationGatePolicy;
  checks: EvaluationGateCheck[];
  comparison: EvaluationRunCompare;
};

export type TraceEventType =
  | "plan"
  | "tool_call"
  | "tool_result"
  | "observation"
  | "approval_required"
  | "approval_decision"
  | "mcp_execution"
  | "patch"
  | "test_result"
  | "reflection"
  | "final"
  | "error";

export type TraceEvent = {
  id: string;
  run_id: string;
  type: TraceEventType;
  tool_name: string | null;
  input: unknown;
  output: unknown;
  duration_ms: number | null;
  created_at: string;
};
