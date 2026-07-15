import { ArtifactPreviewClient } from "./ArtifactPreviewClient";

export default async function EvaluationArtifactPage({
  searchParams
}: {
  searchParams: Promise<{ runId?: string }>;
}) {
  const { runId = "" } = await searchParams;
  return <ArtifactPreviewClient runId={runId} />;
}
