import { SnapshotViewerClient } from "./SnapshotViewerClient";

export default function EvaluationDatasetSnapshotsPage({
  searchParams
}: {
  searchParams: { datasetId?: string };
}) {
  return <SnapshotViewerClient initialDatasetId={searchParams.datasetId ?? ""} />;
}
