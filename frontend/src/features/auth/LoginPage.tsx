import { LogIn } from "lucide-react";
import { useState, type FormEvent } from "react";

import { useLogin } from "../../api/auth";
import { Button, ErrorBox, Field, Input } from "../../components/ui";

export function LoginPage({ expired = false }: { expired?: boolean }) {
  const login = useLogin();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    login.mutate({ username, password });
  };

  return (
    <div className="flex min-h-full items-center justify-center bg-slate-50 p-4">
      <form
        onSubmit={submit}
        className="w-full max-w-sm space-y-5 rounded-lg bg-white p-6 shadow-sm ring-1 ring-slate-200"
        aria-label="Entrar"
      >
        <div className="flex items-center gap-2">
          <img src="/favicon.svg" alt="" className="size-8" />
          <div>
            <h1 className="text-lg font-semibold text-slate-900">Real Task Scheduler</h1>
            <p className="text-xs text-slate-500">Entre para continuar</p>
          </div>
        </div>
        {expired && !login.error && (
          <p className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800 ring-1 ring-amber-200">
            Sua sessão expirou. Entre novamente.
          </p>
        )}
        <Field label="Usuário" htmlFor="login-username">
          <Input
            id="login-username"
            autoComplete="username"
            autoFocus
            required
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </Field>
        <Field label="Senha" htmlFor="login-password">
          <Input
            id="login-password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
        <ErrorBox error={login.error} />
        <Button variant="primary" type="submit" className="w-full" loading={login.isPending} icon={<LogIn className="size-4" />}>
          Entrar
        </Button>
      </form>
    </div>
  );
}
