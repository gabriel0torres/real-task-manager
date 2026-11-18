import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <div className="py-20 text-center">
      <h1 className="text-2xl font-semibold text-slate-800">Página não encontrada</h1>
      <Link to="/" className="mt-4 inline-block text-sm text-indigo-600 hover:underline">
        Voltar ao painel
      </Link>
    </div>
  );
}
