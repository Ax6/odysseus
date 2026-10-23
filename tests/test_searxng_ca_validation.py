"""A network failure must not be mistaken for rejection of an incident chain."""

import asyncio
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
INCIDENT = json.loads((ROOT / "tests/fixtures/ca-trust/incident.json").read_text())


@pytest.fixture
def validator():
    repair = ModuleType("repair_trust")
    repair.check_bundle = lambda path: None
    spec = importlib.util.spec_from_file_location(
        "searxng_validation", ROOT / "docker/searxng/validate_image.py"
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"repair_trust": repair}):
        spec.loader.exec_module(module)
    module.__file__ = str(ROOT / "tests/fixtures/ca-trust/validate_image.py")
    return module


class RequestFailure(Exception):
    def __init__(self, code):
        super().__init__(f"curl error {code}")
        self.code = code


@pytest.mark.parametrize("code", [60, 6, 28, 35, None])
def test_live_probe_requires_certificate_errors_for_every_host(validator, code):
    hosts = []

    async def get(url, **kwargs):
        if url == "https://pypi.org/simple/certifi/":
            return SimpleNamespace(status_code=200)
        hosts.append(url.removeprefix("https://").removesuffix("/"))
        assert kwargs["allow_redirects"] is False
        if code is not None:
            raise RequestFailure(code)
        return SimpleNamespace(status_code=200)

    client = SimpleNamespace(get=get, aclose=AsyncMock())
    factory = ModuleType("searx.network.client")

    def new_client(**kwargs):
        assert kwargs["verify"] is True
        return client

    factory.new_client = new_client
    errors = ModuleType("curl_cffi.requests.exceptions")
    errors.RequestException = RequestFailure
    modules = {"searx.network.client": factory, "curl_cffi.requests.exceptions": errors}
    with patch.dict(sys.modules, modules), patch.object(sys, "path", list(sys.path)):
        if code == 60:
            asyncio.run(validator.check_https())
            assert set(hosts) == set(INCIDENT["chains"])
        else:
            expected = "unexpectedly accepted" if code is None else "inconclusive"
            with pytest.raises(RuntimeError, match=expected):
                asyncio.run(validator.check_https())
    client.aclose.assert_awaited_once()


def test_offline_probe_rejects_openssl_execution_failure(validator):
    result = SimpleNamespace(returncode=1, stderr="openssl: unknown option", stdout="")
    with patch.dict(validator.os.environ, {"SSL_CERT_FILE": "/unused.pem", "SSL_CERT_DIR": "/unused"}), \
            patch.object(validator.subprocess, "run", return_value=result):
        with pytest.raises(RuntimeError, match="not a certificate trust rejection"):
            validator.check_chains()
