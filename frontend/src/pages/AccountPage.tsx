import { useMe } from "../api/auth";
import { useToast } from "../components/Toast";
import { Card, PageHeader } from "../components/ui";
import { ChangePasswordForm } from "../features/auth/ChangePasswordForm";
import { formatDateTime } from "../lib/format";

export function AccountPage() {
  const { data: user } = useMe();
  const toast = useToast();
  return (
    <>
      <PageHeader
        title="Minha conta"
        subtitle={user ? `${user.username} · último acesso ${formatDateTime(user.last_login_at)}` : undefined}
      />
      <Card title="Trocar senha">
        <p className="mb-4 text-sm text-slate-500">Ao trocar a senha, as sessões abertas em outros navegadores são encerradas.</p>
        <ChangePasswordForm onDone={() => toast.success("Senha alterada.")} />
      </Card>
    </>
  );
}
