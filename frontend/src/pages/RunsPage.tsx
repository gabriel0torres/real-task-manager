import { Card, PageHeader } from "../components/ui";
import { RunHistory } from "../features/runs/RunHistory";

export function RunsPage() {
  return (
    <>
      <PageHeader title="Execuções" subtitle="Histórico de todas as tarefas." />
      <Card>
        <RunHistory />
      </Card>
    </>
  );
}
