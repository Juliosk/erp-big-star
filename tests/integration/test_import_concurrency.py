from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any
from uuid import uuid4

import pytest

from erp.modules.product.infrastructure.product_imports import PostgresProductImports
from tests.integration.import_api_support import command, import_api, upload

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("same_key", [False, True])
def test_parallel_commit_has_exactly_one_durable_effect(same_key: bool) -> None:
    with import_api() as fixture:
        job = upload(fixture, [["A", uuid4().hex, "Concurrent import", "PA", "UN"]])
        for action in ("validate", "preview", "confirm"):
            job = command(fixture, job, action)
        barrier = Barrier(2)

        def commit(index: int) -> tuple[int, dict[str, Any]]:
            barrier.wait(timeout=10)
            response = fixture.client.post(
                f"/api/v1/data/imports/{job['id']}/commit?company_id={fixture.data.company_id}",
                headers={
                    **fixture.headers,
                    "If-Match": f'"{job["version"]}"',
                    "Idempotency-Key": "same" if same_key else str(index),
                },
                json={"fingerprint": job["fingerprint"]},
            )
            return response.status_code, dict(response.json())

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(commit, (1, 2)))
        assert sorted(result[0] for result in results) == ([200, 200] if same_key else [200, 409])
        if same_key:
            assert sum(bool(result[1].get("idempotency_replayed")) for result in results) == 1
        assert len(fixture.client.get(fixture.url, headers=fixture.headers).json()["data"]) == 1


def test_owner_refuses_a_plan_that_changes_during_its_final_revalidation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with import_api() as fixture:
        job = upload(fixture, [["A", uuid4().hex, "Owner guarded", "PA", "UN"]])
        for action in ("validate", "preview", "confirm"):
            job = command(fixture, job, action)
        original = PostgresProductImports.validate
        calls = 0

        async def changed(self: PostgresProductImports, rows: Any) -> Any:
            nonlocal calls
            calls += 1
            return () if calls == 2 else await original(self, rows)

        monkeypatch.setattr(PostgresProductImports, "validate", changed)
        command(fixture, job, "commit", expected_status=409)
        assert fixture.client.get(fixture.url, headers=fixture.headers).json()["data"] == []
