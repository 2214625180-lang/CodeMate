import type {
  AgentRun,
  CIConfig,
  CodeFile,
  EvaluationDataset,
  EvaluationDatasetPayload,
  EvaluationGateResult,
  EvaluationRunCompare,
  EvaluationRun,
  FixEvaluationRunRequest,
  FileContent,
  FixResponse,
  RepoMemory,
  Repository,
  RepositoryStatusResponse,
  RetrievalEvaluationRunRequest,
  ReviewResponse
} from "./types";

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
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
  testCommand?: string
): Promise<FixResponse> {
  return request<FixResponse>(`/repos/${repoId}/fix`, {
    method: "POST",
    body: JSON.stringify({
      issue,
      test_command: testCommand?.trim() || null
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

export function listEvaluationRuns(limit = 20): Promise<EvaluationRun[]> {
  return request<EvaluationRun[]>(`/evaluations?limit=${String(limit)}`);
}

export function getEvaluationRun(evaluationRunId: string): Promise<EvaluationRun> {
  return request<EvaluationRun>(`/evaluations/${evaluationRunId}`);
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

export function evaluateRegressionGate(
  datasetId: string,
  candidateRunId: string
): Promise<EvaluationGateResult> {
  const params = new URLSearchParams({ candidate_run_id: candidateRunId });
  return request<EvaluationGateResult>(`/evaluations/datasets/${datasetId}/gate?${params}`);
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
