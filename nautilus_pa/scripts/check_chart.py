"""用无头 Chromium 验证 SACW 工作台并截图（三个页签 + 断言）。

Playwright 环境固定在 ``.tools/playwright``，浏览器位于
``~/.cache/ms-playwright``，两者都在持久目录，无需每次重建。

首次准备（只需执行一次）：

```bash
uv venv .tools/playwright --python 3.13
uv pip install --python .tools/playwright/bin/python playwright
.tools/playwright/bin/python -m playwright install chromium
```

用法：

```bash
.tools/playwright/bin/python scripts/check_chart.py
.tools/playwright/bin/python scripts/check_chart.py --url http://127.0.0.1:8787/ -o /tmp/sacw.png
```
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:8787/"
DEFAULT_OUTPUT = Path("chart-check.png")


def wait_for_text(
    page: object,
    selector: str,
    needles: tuple[str, ...],
    timeout_seconds: float,
) -> bool:
    """轮询元素文本（不依赖 page.evaluate 字符串求值，CSP 下也可用）。"""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        with contextlib.suppress(Exception):
            text = page.text_content(selector) or ""
            if any(needle in text for needle in needles):
                return True
        page.wait_for_timeout(150)
    return False


def build_parser() -> argparse.ArgumentParser:
    """构建命令行解析器。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL, help="工作台页面地址")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT, help="截图输出路径")
    parser.add_argument("--width", type=int, default=1680, help="视口宽度")
    parser.add_argument("--height", type=int, default=980, help="视口高度")
    parser.add_argument("--timeout", type=int, default=40, help="等待数据加载的超时秒数")
    parser.add_argument(
        "--skip-regression",
        action="store_true",
        help="跳过全套 PB 回归运行（较慢）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """渲染页面、采集诊断信息并截图。"""
    args = build_parser().parse_args(argv)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "未找到 Playwright。请先执行：\n"
            "  uv venv .tools/playwright --python 3.13\n"
            "  uv pip install --python .tools/playwright/bin/python playwright\n"
            "  .tools/playwright/bin/python -m playwright install chromium",
            file=sys.stderr,
        )
        return 2

    console: list[str] = []
    errors: list[str] = []
    bad: list[str] = []
    report: dict[str, object] = {}

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chromium", args=["--no-sandbox"])
        except Exception as exc:
            print(
                f"启动 Chromium 失败：{exc}\n"
                "若浏览器缺失，执行：.tools/playwright/bin/python -m playwright install chromium",
                file=sys.stderr,
            )
            return 2

        page = browser.new_page(viewport={"width": args.width, "height": args.height})
        page.on("console", lambda m: console.append(f"{m.type}: {m.text}"))
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on(
            "response",
            lambda r: bad.append(f"{r.status} {r.url}") if r.status >= 400 else None,
        )

        page.goto(args.url, wait_until="load")
        if not wait_for_text(page, "#status-line", ("·",), args.timeout):
            errors.append("等待数据超时")
        page.wait_for_timeout(1800)

        report["annotate"] = page.evaluate(
            """() => ({
              sacw: (document.getElementById('sacw-version') || {}).textContent || null,
              spec: (document.getElementById('spec-version') || {}).textContent || null,
              instrument: (document.getElementById('instrument') || {}).textContent || null,
              source: (document.getElementById('source-badge') || {}).textContent || null,
              dataset: (document.getElementById('dataset-badge') || {}).textContent || null,
              canOpen: (document.getElementById('can-open') || {}).textContent || null,
              macro: (document.getElementById('macro-summary') || {}).textContent || null,
              status: (document.getElementById('status-line') || {}).textContent || null,
              timeframeButtons: [...document.querySelectorAll('#timeframe-buttons button')]
                .map(b => b.textContent.trim()),
              stateRows: [...document.querySelectorAll('#state-rows tr')]
                .map(tr => [...tr.children].map(td => td.textContent.trim())),
              zoneItems: document.querySelectorAll('#zone-list li').length,
              structureItems: document.querySelectorAll('#structure-list li').length,
              annotationNotice:
                (document.getElementById('n-invalidation-notice') || {}).textContent || null,
              captions: [...document.querySelectorAll('.chart-caption')]
                .map(n => n.textContent.trim()),
              canvases: [...document.querySelectorAll('canvas')].length,
              hint: (document.getElementById('tool-hint') || {}).textContent || null,
            })""",
        )

        # 侧栏页签：标注 / 结构 / 比对 必须能切换。
        panel_tabs = {}
        for name in ("structure", "compare", "annotate"):
            page.click(f'.panel-tab[data-panel="{name}"]')
            page.wait_for_timeout(120)
            panel_tabs[name] = page.evaluate(
                """(name) => ({
                  active: document.getElementById('panel-' + name)
                    .classList.contains('active'),
                  visible: document.getElementById('panel-' + name)
                    .getBoundingClientRect().height > 0,
                })""",
                name,
            )
        report["panelTabs"] = panel_tabs

        # 全页截图（结构标注页签）
        page.screenshot(path=str(args.output), full_page=False)

        # 逐周期切换，确认图表与面板都能重绘
        timeframe_checks = []
        for code in ("1M", "1W", "1D", "4H", "1H", "15M", "3M"):
            page.click(f'#timeframe-buttons button[data-timeframe="{code}"]')
            page.wait_for_timeout(320)
            timeframe_checks.append(
                page.evaluate(
                    """(code) => ({
                      code,
                      status: (document.getElementById('status-line') || {}).textContent || null,
                      zones: document.querySelectorAll('#zone-list li').length,
                      structures: document.querySelectorAll('#structure-list li').length,
                      levels: document.querySelectorAll('#levels dd').length,
                      atrLegend: (document.getElementById('legend-atr') || {}).textContent || null,
                    })""",
                    code,
                ),
            )
        report["timeframes"] = timeframe_checks

        # 十字光标：移动到图表中部，读取图例提示
        box = page.locator("#price-chart").bounding_box()
        if box:
            page.mouse.move(box["x"] + box["width"] * 0.6, box["y"] + box["height"] * 0.4)
            page.wait_for_timeout(400)
            report["crosshair"] = page.evaluate(
                """() => ({
                  ohlc: (document.getElementById('legend-ohlc') || {}).textContent || null,
                  indicators: (document.getElementById('legend-ind') || {}).textContent || null,
                  zigzag: (document.getElementById('legend-zigzag') || {}).textContent || null,
                  atr: (document.getElementById('legend-atr') || {}).textContent || null,
                })""",
            )

        # 十字光标移动时图例文字会变长变短；图例区高度必须保持稳定，
        # 否则 ResizeObserver 会反复 resize 图表，表现为鼠标移动时闪烁。
        stability = []
        if box:
            for fraction in (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
                page.mouse.move(
                    box["x"] + box["width"] * fraction,
                    box["y"] + box["height"] * 0.35,
                )
                page.wait_for_timeout(120)
                stability.append(
                    page.evaluate(
                        """() => {
                          const head = document.querySelector('.chart-head')
                            .getBoundingClientRect();
                          const chart = document.getElementById('price-chart')
                            .getBoundingClientRect();
                          return { head: head.height, chart: chart.height };
                        }"""
                    )
                )
        report["crosshairStability"] = stability

        # 标注工具：Swing 两次点击 → 待提交面板
        # 注意：两次点击之间必须移动鼠标并等待，超过双击判定阈值，
        # 否则浏览器把第二次点击合并为 dblclick，LWC 不再触发 click 订阅。
        page.click('[data-tool="swing"]')
        if box:
            first = (box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.45)
            second = (box["x"] + box["width"] * 0.56, box["y"] + box["height"] * 0.5)
            page.mouse.move(first[0], first[1])
            page.wait_for_timeout(150)
            page.mouse.click(first[0], first[1])
            page.wait_for_timeout(700)
            page.mouse.move(second[0], second[1])
            page.wait_for_timeout(150)
            page.mouse.click(second[0], second[1])
            page.wait_for_timeout(400)
        report["swingTool"] = page.evaluate(
            """() => ({
              pendingVisible: !document.getElementById('pending-annotation')
                .classList.contains('hidden'),
              pendingText:
                (document.getElementById('pending-annotation') || {}).textContent || null,
              debug: window.SACW_DEBUG ? window.SACW_DEBUG.snapshot() : null,
            })""",
        )
        # 取消待提交，避免污染标注库
        with contextlib.suppress(Exception):
            page.click('#pending-annotation button:has-text("取消")')

        # Zone 工具：点击两个摆动点，验证后端几何预览
        page.click('[data-tool="zone"]')
        if box:
            for index, (fx, fy) in enumerate(((0.42, 0.55), (0.48, 0.6))):
                page.mouse.move(box["x"] + box["width"] * fx, box["y"] + box["height"] * fy)
                page.wait_for_timeout(150)
                page.mouse.click(box["x"] + box["width"] * fx, box["y"] + box["height"] * fy)
                page.wait_for_timeout(700 if index == 0 else 400)
        report["zoneTool"] = page.evaluate(
            """() => ({
              pendingText:
                (document.getElementById('pending-annotation') || {}).textContent || null,
              debug: window.SACW_DEBUG ? window.SACW_DEBUG.snapshot() : null,
              anchorDirs: [...document.querySelectorAll('#anchor-chips button')]
                .map(b => b.dataset.direction || null),
            })""",
        )
        with contextlib.suppress(Exception):
            page.click('#pending-annotation button:has-text("取消")')

        # 回归页签
        page.click('.tab[data-tab="regression"]')
        page.wait_for_timeout(600)
        if not args.skip_regression:
            page.click("#run-suite")
            if not wait_for_text(page, "#suite-meta", ("run ", "失败"), args.timeout):
                errors.append("回归运行超时")
            page.wait_for_timeout(500)

        report["regression"] = page.evaluate(
            """() => ({
              suiteMeta: (document.getElementById('suite-meta') || {}).textContent || null,
              caseCount: document.querySelectorAll('#case-list li').length,
              firstCase: (document.querySelector('#case-list li') || {}).textContent || null,
              summary: (document.getElementById('suite-summary') || {}).textContent || null,
            })""",
        )
        # 选中一个 READY 样本查看断言
        with contextlib.suppress(Exception):
            page.click('#case-list li:has-text("PB-34")')
            page.wait_for_timeout(300)
        report["caseDetail"] = page.evaluate(
            """() => ({
              title: (document.getElementById('case-title') || {}).textContent || null,
              facts: document.querySelectorAll('#case-facts dt').length,
              assertions: [...document.querySelectorAll('#case-assertions li')]
                .map(li => ({
                  result: li.dataset.result || null,
                  text: li.textContent.trim().slice(0, 120)
                })),
            })""",
        )
        page.screenshot(path=str(args.output.with_name("chart-check-regression.png")))

        # 数据集页签
        page.click('.tab[data-tab="dataset"]')
        page.wait_for_timeout(500)
        page.click("#build-snapshot")
        page.wait_for_timeout(1200)
        report["dataset"] = page.evaluate(
            """() => ({
              coverageRows: [...document.querySelectorAll('#coverage-rows tr')]
                .map(tr => [...tr.children].map(td => td.textContent.trim())),
              facts: [...document.querySelectorAll('#dataset-facts dt')]
                .map(dt => dt.textContent.trim()),
              groundTruth: (document.getElementById('ground-truth-hash') || {}).textContent || null,
              snapshot:
                (document.getElementById('snapshot-output') || {}).textContent.slice(0, 400),
              auditRows: document.querySelectorAll('#audit-list li').length,
            })""",
        )
        page.screenshot(path=str(args.output.with_name("chart-check-dataset.png")))
        browser.close()

    # 已确认摆动点必然 H/L 交替；若锚点面板方向单一，说明前端没有读取
    # 载荷里的 direction 字段（早期实现从空 text 推断，全部误判为 LOW），
    # 会导致 N 结构无法按 L1→H1→L2→H2 选择。
    anchor_dirs = (report.get("zoneTool") or {}).get("anchorDirs") or []
    if anchor_dirs and not {"HIGH", "LOW"}.issubset(set(anchor_dirs)):
        errors.append(
            "锚点方向异常：应同时包含 SwingHigh 与 SwingLow，实际 "
            + ",".join(str(item) for item in anchor_dirs)
        )

    stability = report.get("crosshairStability") or []
    head_heights = {round(float(item["head"]), 1) for item in stability}
    chart_heights = {round(float(item["chart"]), 1) for item in stability}
    if len(head_heights) > 1 or len(chart_heights) > 1:
        errors.append(
            "十字光标移动时图表高度不稳定（会闪烁）："
            f"图例区 {sorted(head_heights)}，主图 {sorted(chart_heights)}"
        )

    panel_tabs = report.get("panelTabs") or {}
    if any(not item.get("active") or not item.get("visible") for item in panel_tabs.values()):
        errors.append(f"侧栏页签切换异常: {panel_tabs}")

    report["url"] = args.url
    report["screenshot"] = str(args.output.resolve())
    report["pageErrors"] = errors
    report["console"] = console
    report["badResponses"] = bad
    print(json.dumps(report, ensure_ascii=False, indent=2))

    ok = not errors and not bad and not console
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
