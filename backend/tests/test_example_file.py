"""The example export shipped in examples/ must stay importable."""

from pathlib import Path

import pytest

from tests.conftest import API

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "exemplo-export.yaml"


@pytest.mark.skipif(not EXAMPLE.exists(), reason="examples/ not available (e.g. backend-only copy)")
def test_example_export_imports_cleanly(client):
    content = EXAMPLE.read_text(encoding="utf-8")
    body = {"content": content, "activate_tasks": True}
    plan = client.post(f"{API}/transfer/import/preview", json=body).json()
    assert plan["valid"], plan["errors"]
    assert plan["header"]["scope"] == "group" and plan["header"]["groups"] == ["exemplo"]
    assert [p["key"] for p in plan["pending_secrets"]] == ["API_TOKEN"]

    report = client.post(f"{API}/transfer/import/apply", json=body).json()
    assert report["applied"] and report["summary"]["create"] == 6  # 1 group, 2 subs, 3 tasks

    tasks = {t["name"]: t for t in client.get(f"{API}/tasks").json()}
    assert tasks["relatorio-diario"]["schedule_description"] == "Todos os dias às 07:00 e 18:30"
    assert tasks["fechamento-mensal"]["schedule_description"] == "No último dia do mês às 23:00"
    assert tasks["limpar-temporarios"]["schedule_description"] == (
        "A cada 30 minutos, de segunda a sexta"
    )
