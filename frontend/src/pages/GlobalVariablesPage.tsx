import { PageHeader } from "../components/ui";
import { VariablesEditor } from "../features/variables/VariablesEditor";

export function GlobalVariablesPage() {
  return (
    <>
      <PageHeader
        title="Variáveis globais"
        subtitle="Disponíveis para todas as tarefas. Grupos, subcategorias e tarefas podem sobrescrevê-las."
      />
      <VariablesEditor scope="global" ownerId={null} title="Variáveis globais" />
    </>
  );
}
