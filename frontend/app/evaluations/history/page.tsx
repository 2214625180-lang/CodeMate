import { HistoryDashboardClient } from "./HistoryDashboardClient";

export default function EvaluationHistoryPage({
  searchParams
}: {
  searchParams: { datasetId?: string };
}) {
  return <HistoryDashboardClient initialDatasetId={searchParams.datasetId ?? ""} />;
}
