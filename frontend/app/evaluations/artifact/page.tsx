import { ArtifactPreviewClient } from "./ArtifactPreviewClient";

export default function EvaluationArtifactPage({
  searchParams
}: {
  searchParams: { runId?: string };
}) {
  return <ArtifactPreviewClient runId={searchParams.runId ?? ""} />;
}
