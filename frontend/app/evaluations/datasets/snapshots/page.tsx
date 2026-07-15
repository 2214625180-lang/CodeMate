import { SnapshotViewerClient } from "./SnapshotViewerClient";

export default async function EvaluationDatasetSnapshotsPage({
  searchParams
}: {
  searchParams: Promise<{ datasetId?: string }>;
}) {
  const { datasetId = "" } = await searchParams;
  return <SnapshotViewerClient initialDatasetId={datasetId} />;
}
