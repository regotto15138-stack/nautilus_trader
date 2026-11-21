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


def test_parser_defaults_to_okx_proxy() -> None:
    """不传 --proxy-url 时补齐默认走 WSL 宿主机代理。"""
    args = serve_chart.build_parser().parse_args([])
    assert args.proxy_url == serve_chart.DEFAULT_PROXY_URL
    assert args.proxy_url == "http://172.21.192.1:7890"


def test_proxy_can_be_overridden_or_disabled() -> None:
    """显式代理覆盖默认值；空字符串表示直连。"""
    overridden = serve_chart.build_parser().parse_args(
        ["--proxy-url", "http://127.0.0.1:7891"]
    )
    assert overridden.proxy_url == "http://127.0.0.1:7891"

    disabled = serve_chart.build_parser().parse_args(["--proxy-url", ""])
    assert disabled.proxy_url == ""


def test_default_proxy_is_passed_to_sync_service(tmp_path: Path) -> None:
    """默认代理要进入按需补齐服务，而不是停在参数层。"""
    args = serve_chart.build_parser().parse_args(["--catalog", str(tmp_path)])

    class _Service:
        session_offset_hours = 8

    sync = serve_chart._build_sync_service(args, tmp_path, _Service())
    assert sync is not None
    assert sync.proxy_url == serve_chart.DEFAULT_PROXY_URL
