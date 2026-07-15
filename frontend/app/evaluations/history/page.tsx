import { HistoryDashboardClient } from "./HistoryDashboardClient";

export default async function EvaluationHistoryPage({
  searchParams
}: {
  searchParams: Promise<{ datasetId?: string }>;
}) {
  const { datasetId = "" } = await searchParams;
  return <HistoryDashboardClient initialDatasetId={datasetId} />;
}
