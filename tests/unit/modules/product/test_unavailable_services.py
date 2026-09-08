"""Missing composition fails closed instead of producing partial commands."""

from collections.abc import Callable
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from erp.modules.product.api.creation import get_creation
from erp.modules.product.api.queries import get_queries
from erp.modules.product.api.updates import get_updates
from erp.platform.errors import ApplicationError


@pytest.mark.parametrize("dependency", [get_creation, get_queries, get_updates])
def test_missing_service_returns_unavailable(dependency: Callable[[Request], object]) -> None:
    request = Request({"type": "http", "app": SimpleNamespace(state=SimpleNamespace())})
    with pytest.raises(ApplicationError) as captured:
        dependency(request)
    assert captured.value.status_code == 503
