"""Unit tests for base URL validation."""

import pytest

from mealie_mcp.config import Config


def test_https_required_by_default():
    with pytest.raises(ValueError, match="HTTPS"):
        Config(
            mealie_base_url="http://mealie.selfhosted.svc.cluster.local:9000",
            mealie_api_token="tok",
        )


def test_insecure_http_opt_in():
    c = Config(
        mealie_base_url="http://mealie.selfhosted.svc.cluster.local:9000",
        mealie_api_token="tok",
        allow_insecure_http=True,
    )
    assert c.mealie_base_url == "http://mealie.selfhosted.svc.cluster.local:9000"


def test_insecure_http_from_env(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_HTTP", "true")
    c = Config(
        mealie_base_url="http://mealie.selfhosted.svc.cluster.local:9000",
        mealie_api_token="tok",
    )
    assert c.allow_insecure_http is True


def test_missing_token_errors():
    with pytest.raises(ValueError, match="MEALIE_API_TOKEN"):
        Config(mealie_base_url="https://mealie.example.com", mealie_api_token="")
