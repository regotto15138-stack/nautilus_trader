"""启动 SACW 结构标注与参数校准工作台（规格 V1.4.8 / SACW V1.1.2）。

零第三方框架：HTTP 层使用标准库 ``http.server``；数据库使用 ``sqlite3``。

数据来源二选一：

- ``--catalog PATH``：读取采集器产出的 Parquet 数据目录（默认 ``nautilus_pa/catalog``）；
- ``--demo``：生成确定性的合成序列。

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

from pa_trend.application import paths
from pa_trend.application.annotation_store import SacwStore
from pa_trend.application.data_service import DEFAULT_DEMO_BARS, DataService
from pa_trend.application.regression import RegressionRunner, load_cases, validate_cases
from pa_trend.config.validation import Stage, validate_startup
from pa_trend.presentation.api import ApiRouter, read_body, route_path

WEB_DIR = paths.WEB_DIR
DEFAULT_CONFIGS = paths.DEFAULT_CONFIGS_DIR
DEFAULT_CATALOG = paths.DEFAULT_CATALOG_DIR
DEFAULT_STORE = paths.PROJECT_ROOT / "var" / "sacw.sqlite3"
DEFAULT_INSTRUMENT = "ETH-USDT-SWAP.OKX"

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".png": "image/png",
}


def build_handler(router: ApiRouter, *, web_dir: Path) -> type[BaseHTTPRequestHandler]:
    """构造绑定到给定路由与静态目录的请求处理器。"""

    class SacwRequestHandler(BaseHTTPRequestHandler):
        """静态文件 + JSON API 请求处理器。"""

        server_version = "SACW/1.1.2"

        def do_GET(self) -> None:
            self._dispatch("GET")

        def do_POST(self) -> None:
            self._dispatch("POST")

        def do_PATCH(self) -> None:
            self._dispatch("PATCH")

        def _dispatch(self, method: str) -> None:
            path, query = route_path(self.path)
            if not path.startswith("/api/"):
                self._serve_static(path)
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
    return parser


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

    router = ApiRouter(
        service=service,
        store=store,
        regression=regression,
        configs_dir=args.configs,
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
    print(f"数据来源: {service.source}（合约 {service.instrument_id}）")
    if not args.demo:
        print(f"数据目录: {catalog_dir}")
    print(f"数据集: {dataset.dataset_id}（hash {dataset.data_hash[:12]}）")
    print(f"配置哈希: {service.config_hash[:12]}")
    print(f"标注项目: {project['name']} ({project['project_id']})")
    print(f"数据库: {args.store}")
    print(f"会话偏移: UTC+{service.session_offset_hours}")
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
