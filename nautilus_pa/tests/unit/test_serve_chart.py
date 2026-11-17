"""SACW HTTP 服务的请求来源与安全头约束。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "serve_chart.py"
_SPEC = importlib.util.spec_from_file_location("sacw_serve_chart", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
serve_chart = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(serve_chart)


def test_same_origin_request_is_allowed() -> None:
    headers = {"Origin": "http://127.0.0.1:8787", "Host": "127.0.0.1:8787"}
    assert serve_chart._is_cross_site(headers) is False


def test_missing_origin_is_allowed_for_local_clients() -> None:
    assert serve_chart._is_cross_site({}) is False
    assert serve_chart._is_cross_site({"Host": "127.0.0.1:8787"}) is False


def test_cross_site_fetch_metadata_is_rejected() -> None:
    assert serve_chart._is_cross_site({"Sec-Fetch-Site": "cross-site"}) is True
    assert serve_chart._is_cross_site({"Sec-Fetch-Site": "same-site"}) is True


def test_foreign_origin_is_rejected() -> None:
    headers = {"Origin": "https://evil.example", "Host": "127.0.0.1:8787"}
    assert serve_chart._is_cross_site(headers) is True


def test_origin_host_mismatch_is_rejected() -> None:
    headers = {"Origin": "http://127.0.0.1:9999", "Host": "127.0.0.1:8787"}
    assert serve_chart._is_cross_site(headers) is True


def test_security_headers_cover_script_and_framing() -> None:
    headers = dict(serve_chart._SECURITY_HEADERS)
    assert "script-src 'self'" in headers["Content-Security-Policy"]
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["X-Content-Type-Options"] == "nosniff"
