"""启动 SACW 结构标注与参数校准工作台（规格 V1.4.8 / SACW V1.1.2）。

零第三方框架：HTTP 层使用标准库 ``http.server``；数据库使用 ``sqlite3``。

数据来源二选一：

- ``--catalog PATH``：读取采集器产出的 Parquet 数据目录（默认 ``nautilus_pa/catalog``）；
- ``--demo``：生成确定性的合成序列。

数据补齐默认经 Windows 侧代理 http://172.21.192.1:7890 访问 OKX（WSL 直连通常
不通）；用 `--proxy-url` 覆盖，传空字符串表示不走代理。

示例
----
python scripts/serve_chart.py --port 8787
python scripts/serve_chart.py --demo --port 8787
"""

from __future__ import annotations

import argparse
import errno
import json
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from pa_trend.application import paths
from pa_trend.application.annotation_store import SacwStore
from pa_trend.application.data_service import DEFAULT_DEMO_BARS, DataService
from pa_trend.application.market_sync import MarketSyncService
from pa_trend.application.regression import RegressionRunner, load_cases, validate_cases
from pa_trend.config.validation import Stage, validate_startup
from pa_trend.presentation.api import ApiRouter, read_body, route_path

WEB_DIR = paths.WEB_DIR
DEFAULT_CONFIGS = paths.DEFAULT_CONFIGS_DIR
DEFAULT_CATALOG = paths.DEFAULT_CATALOG_DIR
DEFAULT_STORE = paths.PROJECT_ROOT / "var" / "sacw.sqlite3"
DEFAULT_INSTRUMENT = "ETH-USDT-SWAP.OKX"

#: 按需补齐默认使用的 OKX 代理（WSL 内直连通常不通，走 Windows 侧 Clash 等代理）。
#: 可用 --proxy-url 覆盖；传空字符串表示直连。
DEFAULT_PROXY_URL = "http://172.21.192.1:7890"

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".png": "image/png",
}

#: 工作台是本地单机工具，请求体保持上限，避免异常请求占用内存。
MAX_BODY_BYTES = 2 * 1024 * 1024

#: 写操作必须满足的浏览器来源约束；GET 不受影响。
_WRITE_METHODS = frozenset({"POST", "PATCH", "DELETE"})

_SECURITY_HEADERS = (
    (
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
        "object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    ),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
)


class HeadersLike(Protocol):
    """请求头的最小读取接口。"""

    def get(self, name: str, default: str | None = None) -> str | None:
        """读取一个请求头。"""
        ...


def _is_cross_site(headers: HeadersLike) -> bool:
    """判断写请求是否来自其他站点（浏览器 CSRF / DNS rebinding）。"""
    site = str(headers.get("Sec-Fetch-Site") or "").strip().lower()
    if site and site not in {"same-origin", "none"}:
        return True
    origin = str(headers.get("Origin") or "").strip()
    if not origin:
        return False
    host = str(headers.get("Host") or "").strip().lower()
    try:
        parsed = urlparse(origin)
    except ValueError:
        return True
    return not host or parsed.netloc.lower() != host


def build_handler(router: ApiRouter, *, web_dir: Path) -> type[BaseHTTPRequestHandler]:
    """构造绑定到给定路由与静态目录的请求处理器。"""

    class SacwRequestHandler(BaseHTTPRequestHandler):
        """静态文件 + JSON API 请求处理器。"""

        server_version = "SACW"

        def version_string(self) -> str:
            """不在响应头泄露解释器版本。"""
            return self.server_version

        def do_GET(self) -> None:
            self._dispatch("GET")

        def do_POST(self) -> None:
            self._dispatch("POST")

        def do_PATCH(self) -> None:
            self._dispatch("PATCH")

        def do_DELETE(self) -> None:
            self._dispatch("DELETE")

        def _dispatch(self, method: str) -> None:
            path, query = route_path(self.path)
            if not path.startswith("/api/"):
                self._serve_static(path)
                return
            if method in _WRITE_METHODS:
                rejected = self._reject_unsafe_write()
                if rejected:
                    return
            try:
                body = read_body(self)
            except Exception as exc:
                self._send_json(
                    {
                        "data": None,
                        "meta": {"request_id": "-"},
                        "error": {"code": "INVALID_JSON", "message": str(exc)},
                    },
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            status, envelope = router.dispatch(
                method=method,
                path=path,
                query=query,
                body=body,
            )
            self._send_json(envelope, status=status)

        def _reject_unsafe_write(self) -> bool:
            """写请求的跨站与请求体边界检查；被拒绝时返回 True。"""
            if _is_cross_site(self.headers):
                self._send_json(
                    {
                        "data": None,
                        "meta": {"request_id": "-"},
                        "error": {
                            "code": "CROSS_ORIGIN_BLOCKED",
                            "message": "cross-site write requests are not allowed",
                        },
                    },
                    status=HTTPStatus.FORBIDDEN,
                )
                return True
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length < 0:
                self._send_json(
                    {
                        "data": None,
                        "meta": {"request_id": "-"},
                        "error": {"code": "INVALID_LENGTH", "message": "invalid Content-Length"},
                    },
                    status=HTTPStatus.BAD_REQUEST,
                )
                return True
            if length > MAX_BODY_BYTES:
                self._send_json(
                    {
                        "data": None,
                        "meta": {"request_id": "-"},
                        "error": {"code": "BODY_TOO_LARGE", "message": "request body too large"},
                    },
                    status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                )
                return True
            if length:
                content_type = str(self.headers.get("Content-Type") or "")
                media_type = content_type.split(";", 1)[0].strip().lower()
                if media_type != "application/json":
                    self._send_json(
                        {
                            "data": None,
                            "meta": {"request_id": "-"},
                            "error": {
                                "code": "UNSUPPORTED_MEDIA_TYPE",
                                "message": "write requests must use application/json",
                            },
                        },
                        status=HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                    )
                    return True
            return False

        def _send_security_headers(self) -> None:
            for name, value in _SECURITY_HEADERS:
                self.send_header(name, value)

        def _serve_static(self, url_path: str) -> None:
            resolved = self._resolve_static(url_path)
            if resolved is None:
                self.send_error(HTTPStatus.NOT_FOUND, "not found")
                return
            try:
                body = resolved.read_bytes()
            except OSError:
                self.send_error(HTTPStatus.NOT_FOUND, "not found")
                return
            content_type = _CONTENT_TYPES.get(
                resolved.suffix.lower(),
                "application/octet-stream",
            )
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self._send_security_headers()
            self.end_headers()
            self.wfile.write(body)

        def _resolve_static(self, url_path: str) -> Path | None:
            relative = url_path.lstrip("/") or "index.html"
            root = web_dir.resolve()
            try:
                candidate = (root / relative).resolve()
            except (OSError, ValueError):
                return None
            if not candidate.is_relative_to(root):
                return None
            return candidate if candidate.is_file() else None

        def _send_json(self, payload: object, *, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self._send_security_headers()
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            sys.stderr.write(f"[sacw] {format % args}\n")

    return SacwRequestHandler


def build_parser() -> argparse.ArgumentParser:
    """构建命令行解析器。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog",
        type=Path,
        default=DEFAULT_CATALOG,
        help=f"Parquet 数据目录（默认 {DEFAULT_CATALOG}）",
    )
    parser.add_argument("--demo", action="store_true", help="使用合成数据")
    parser.add_argument(
        "--demo-bars",
        type=int,
        default=DEFAULT_DEMO_BARS,
        help="合成数据每个周期的根数",
    )
    parser.add_argument("--configs", type=Path, default=DEFAULT_CONFIGS, help="配置目录")
    parser.add_argument(
        "--store",
        type=Path,
        default=DEFAULT_STORE,
        help=f"SACW SQLite 数据库（默认 {DEFAULT_STORE}）",
    )
    parser.add_argument("--instrument", default=DEFAULT_INSTRUMENT, help="合约标识")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认仅本机）")
    parser.add_argument("--port", type=int, default=8787, help="监听端口")
    parser.add_argument("--code-commit", default=None, help="用于回归记录的代码版本")
    parser.add_argument(
        "--session-offset-hours",
        type=int,
        default=None,
        help="会话偏移小时数；缺省取 research.session_offset_hours",
    )
    parser.add_argument(
        "--proxy-url",
        default=DEFAULT_PROXY_URL,
        help=(
            f"按需补齐时传给采集器的 OKX 代理（默认 {DEFAULT_PROXY_URL}）；"
            "传空字符串表示直连"
        ),
    )
    parser.add_argument(
        "--sync-timeout-secs",
        type=float,
        default=300.0,
        help="单次按需补齐的等待上限（默认 300 秒）",
    )
    return parser


def _build_sync_service(
    args: argparse.Namespace,
    catalog_dir: Path,
    service: DataService,
) -> MarketSyncService | None:
    """按运行模式构建按需补齐服务（合成数据下不提供）。"""
    if args.demo:
        return None
    return MarketSyncService(
        catalog_dir=catalog_dir,
        configs_dir=args.configs,
        instrument_id=args.instrument,
        session_offset_hours=service.session_offset_hours,
        proxy_url=args.proxy_url,
        timeout_secs=args.sync_timeout_secs,
    )


def _report_startup_freshness(sync: MarketSyncService) -> None:
    """启动时报告数据新鲜度（只读，不去补齐）。

    工作台不替用户访问交易所：这里只把「落后多少」讲清楚，补齐由页面上的
    「实时」按钮按需触发，或另开常驻的采集器进程。
    """
    freshness = sync.freshness()
    if not freshness["stale"]:
        print(f"数据新鲜度: 全部周期已追平当前 UTC（{freshness['nowUtc']}）")
        return

    print("数据新鲜度: 以下周期落后于当前 UTC", file=sys.stderr)
    for row in freshness["timeframes"]:
        if not row["behind"]:
            continue
        print(
            f"  - {row['timeframe']}: 末根 {row['lastOpen']} "
            f"缺 {row['tailMissingClosed']} 根已收盘 K 线",
            file=sys.stderr,
        )
    print(
        "  提示：打开页面后点击右上角「实时」按钮补齐，"
        "或运行 scripts/run_collector.py 常驻采集。",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    """启动工作台。"""
    args = build_parser().parse_args(argv)

    catalog_dir = paths.resolve_catalog_dir(args.catalog)
    if not args.demo and not catalog_dir.is_dir():
        print(f"数据目录不存在: {catalog_dir}", file=sys.stderr)
        print("提示：先运行 scripts/run_collector.py 采集，或加 --demo 查看合成数据。",
              file=sys.stderr)
        return 2
    if not (WEB_DIR / "index.html").is_file():
        print(f"缺少前端文件: {WEB_DIR / 'index.html'}", file=sys.stderr)
        return 2

    service = DataService(
        instrument_id=args.instrument,
        configs_dir=args.configs,
        catalog_path=catalog_dir,
        demo=args.demo,
        demo_bars=args.demo_bars,
        session_offset_hours=args.session_offset_hours,
    )

    try:
        validate_startup(service.config, Stage.RESEARCH_STRUCTURE)
        service.ensure_built()
    except Exception as exc:
        print(f"启动失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3

    store = SacwStore(args.store)
    project = store.ensure_project(actor="serve_chart")
    cases = load_cases(args.configs)
    problems = validate_cases(cases)
    if problems:
        print("回归样本自检发现问题：", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)

    dataset = service.dataset_info()
    store.upsert_market_dataset(
        dataset_id=dataset.dataset_id,
        instrument_id=dataset.instrument_id,
        range_start="-" if dataset.range_start_ns is None else str(dataset.range_start_ns),
        range_end="-" if dataset.range_end_ns is None else str(dataset.range_end_ns),
        timeframe_set=list(dataset.timeframes),
        data_hash=dataset.data_hash,
        source=dataset.source,
    )

    regression = RegressionRunner(
        store=store,
        config=service.config,
        config_hash=service.config_hash,
        code_commit=args.code_commit,
        dataset_hash=dataset.data_hash,
        configs_dir=args.configs,
    )
    regression.sync_cases(cases)

    sync = _build_sync_service(args, catalog_dir, service)
    if sync is not None:
        _report_startup_freshness(sync)

    router = ApiRouter(
        service=service,
        store=store,
        regression=regression,
        configs_dir=args.configs,
        sync=sync,
    )
    handler = build_handler(router, web_dir=WEB_DIR)
    try:
        server = ThreadingHTTPServer((args.host, args.port), handler)
    except OSError as exc:
        # 端口被占用是最常见的启动失败：给出可操作提示，而不是原始 traceback。
        if exc.errno in (errno.EADDRINUSE, errno.EACCES):
            print(f"端口 {args.port} 不可用（{exc.strerror}）。", file=sys.stderr)
            print(
                f"提示：可能已有工作台在运行（浏览器打开 http://{args.host}:{args.port}/ ），"
                f"或换一个端口：--port {args.port + 1}",
                file=sys.stderr,
            )
            print(
                f"     查看占用进程：lsof -i :{args.port}（macOS/Linux）"
                f" 或 netstat -ano | findstr :{args.port}（Windows）",
                file=sys.stderr,
            )
        else:
            print(f"无法监听 {args.host}:{args.port}: {exc}", file=sys.stderr)
        store.close()
        return 4

    url = f"http://{args.host}:{args.port}/"
    print(f"SACW 工作台已启动: {url}")
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        print(
            "警告：工作台没有身份认证，且写接口会直接修改本地标注库；"
            "对外监听时请放在可信内网或反向代理鉴权之后。",
            file=sys.stderr,
        )
    print(f"数据来源: {service.source}（合约 {service.instrument_id}）")
    if not args.demo:
        print(f"数据目录: {catalog_dir}")
    print(f"数据集: {dataset.dataset_id}（hash {dataset.data_hash[:12]}）")
    print(f"配置哈希: {service.config_hash[:12]}")
    print(f"标注项目: {project['name']} ({project['project_id']})")
    print(f"数据库: {args.store}")
    print(f"会话偏移: UTC+{service.session_offset_hours}")
    if sync is not None:
        print(f"补齐代理: {args.proxy_url or '不使用代理（直连）'}")
    print("按 Ctrl+C 停止")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止…")
    finally:
        server.server_close()
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
