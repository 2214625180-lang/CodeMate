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

export type AgentRunStatus = "pending" | "running" | "success" | "failed";

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
