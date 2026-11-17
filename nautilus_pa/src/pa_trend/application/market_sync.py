"""按需补齐采集目录：以子进程方式跑一次「补齐后退出」的采集器。

工作台与采集器是两个独立进程。方案上工作台不直接访问交易所——补数一律交给
采集器完成，工作台只负责：

1. 审计目录，确认确实落后于当前 UTC；
2. 起一个 ``run_collector.py --backfill-only`` 子进程，等它把缺口落盘后退出；
3. 让 :class:`~pa_trend.application.data_service.DataService` 重新检测并刷新视图。

同一时刻只允许一个补齐任务在跑，否则两个进程会并发写同一个 Parquet 目录。
"""

from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from pa_trend.application.catalog_audit import (
    TimeframeFreshness,
    audit_catalog,
    summarize,
)
from pa_trend.application.paths import PROJECT_ROOT

#: 采集器脚本相对于项目根目录的位置。
COLLECTOR_SCRIPT = PROJECT_ROOT / "scripts" / "run_collector.py"

#: 单次补齐子进程的等待上限（秒）。超时即终止子进程并报告失败。
DEFAULT_SYNC_TIMEOUT_SECS = 300.0

#: 补齐完成后等待 Parquet 落盘可见的轮询间隔与次数。
_POST_SYNC_POLL_INTERVAL_SECS = 0.2
_POST_SYNC_POLL_ATTEMPTS = 10


@dataclass(frozen=True)
class SyncResult:
    """一次补齐尝试的结果。"""

    status: str
    message: str
    started_at_ns: int
    finished_at_ns: int
    stale_before: bool
    stale_timeframes: tuple[str, ...]
    added_bars: int
    partial: bool = False

    @property
    def ok(self) -> bool:
        """是否已经完成（含「本来就最新」的情形）。"""
        return self.status in {"up-to-date", "completed"}

    @property
    def duration_secs(self) -> float:
        """耗时（秒）。"""
        return (self.finished_at_ns - self.started_at_ns) / 1e9

    def as_dict(self) -> dict[str, object]:
        """转为可 JSON 序列化的摘要。"""
        return {
            "status": self.status,
            "ok": self.ok,
            "partial": self.partial,
            "message": self.message,
            "staleBefore": self.stale_before,
            "staleTimeframes": list(self.stale_timeframes),
            "addedBars": self.added_bars,
            "durationSecs": round(self.duration_secs, 2),
            "startedAt": _iso(self.started_at_ns),
            "finishedAt": _iso(self.finished_at_ns),
        }


def _iso(ns: int) -> str:
    return dt.datetime.fromtimestamp(ns / 1e9, tz=dt.UTC).isoformat()


def _now_ns() -> int:
    return int(time.time() * 1e9)


class MarketSyncService:
    """把「审计 → 补数 → 复核」串成一次幂等操作。"""

    def __init__(
        self,
        *,
        catalog_dir: Path,
        configs_dir: Path,
        instrument_id: str,
        session_offset_hours: int,
        proxy_url: str | None = None,
        timeout_secs: float = DEFAULT_SYNC_TIMEOUT_SECS,
        python_executable: str | None = None,
    ) -> None:
        """初始化同步服务。"""
        self.catalog_dir = catalog_dir
        self.configs_dir = configs_dir
        self.instrument_id = instrument_id
        self.session_offset_hours = session_offset_hours
        self.proxy_url = proxy_url
        self.timeout_secs = timeout_secs
        self.python_executable = python_executable or sys.executable
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ 审计

    def audit(self) -> list[TimeframeFreshness]:
        """审计目录相对当前 UTC 的新鲜度。"""
        return audit_catalog(
            catalog_dir=self.catalog_dir,
            configs_dir=self.configs_dir,
            instrument_id=self.instrument_id,
            session_offset_hours=self.session_offset_hours,
        )

    def freshness(self) -> dict[str, object]:
        """返回可直接下发给前端的汇总。"""
        return summarize(self.audit())

    # ------------------------------------------------------------------ 补齐

    @property
    def busy(self) -> bool:
        """是否已有补齐任务在跑。"""
        return self._lock.locked()

    def sync(self) -> SyncResult:
        """执行一次补齐；已在运行时直接返回 ``busy`` 结果。"""
        if not self._lock.acquire(blocking=False):
            now = _now_ns()
            return SyncResult(
                status="busy",
                message="已有补齐任务正在进行",
                started_at_ns=now,
                finished_at_ns=now,
                stale_before=True,
                stale_timeframes=(),
                added_bars=0,
            )
        try:
            return self._sync_locked()
        finally:
            self._lock.release()

    def _sync_locked(self) -> SyncResult:
        started = _now_ns()
        before = self.audit()
        stale = [item for item in before if item.behind or item.error]
        stale_names = tuple(item.timeframe.value for item in stale)
        before_missing = sum(item.tail_missing_closed + item.missing_in_gaps for item in before)

        if not stale:
            return SyncResult(
                status="up-to-date",
                message="数据已是最新，无需补齐",
                started_at_ns=started,
                finished_at_ns=_now_ns(),
                stale_before=False,
                stale_timeframes=(),
                added_bars=0,
            )

        failed = self._run_collector()
        after = self._await_settled(before_missing)
        remaining = [item for item in after if item.behind or item.error]
        after_missing = sum(
            item.tail_missing_closed + item.missing_in_gaps for item in after
        )
        gained = max(0, before_missing - after_missing)

        if failed is not None:
            return SyncResult(
                status="failed",
                message=f"采集器执行失败：{failed}",
                started_at_ns=started,
                finished_at_ns=_now_ns(),
                stale_before=True,
                stale_timeframes=stale_names,
                added_bars=gained,
            )

        if remaining:
            return SyncResult(
                status="completed",
                message=(
                    "已补齐 " + str(gained) + " 根，仍有 "
                    + "、".join(item.timeframe.value for item in remaining)
                    + " 未追平（可能尚未收盘或采集被限频）"
                ),
                started_at_ns=started,
                finished_at_ns=_now_ns(),
                stale_before=True,
                stale_timeframes=stale_names,
                added_bars=gained,
                partial=True,
            )

        return SyncResult(
            status="completed",
            message=f"已补齐 {gained} 根 K 线",
            started_at_ns=started,
            finished_at_ns=_now_ns(),
            stale_before=True,
            stale_timeframes=stale_names,
            added_bars=gained,
        )

    def _collector_command(self) -> list[str]:
        command = [
            self.python_executable,
            str(COLLECTOR_SCRIPT),
            "--backfill-only",
            "--catalog",
            str(self.catalog_dir),
            "--configs",
            str(self.configs_dir),
            "--session-offset-hours",
            str(self.session_offset_hours),
        ]
        if self.proxy_url:
            command.extend(["--proxy-url", self.proxy_url])
        return command

    def _run_collector(self) -> str | None:
        """跑一次补齐子进程；成功返回 ``None``，失败返回原因。"""
        if not COLLECTOR_SCRIPT.is_file():
            return f"找不到采集器脚本 {COLLECTOR_SCRIPT}"

        command = self._collector_command()
        env = _child_env()
        try:
            completed = subprocess.run(
                command,
                cwd=str(PROJECT_ROOT),
                env=env,
                capture_output=True,
                text=True,
                timeout=self.timeout_secs,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return f"采集器在 {self.timeout_secs:.0f} 秒内未完成"
        except OSError as exc:
            return f"无法启动采集器：{exc}"

        if completed.returncode != 0:
            tail = (completed.stderr or completed.stdout or "").strip().splitlines()
            detail = tail[-1] if tail else f"exit code {completed.returncode}"
            return detail
        return None

    def _await_settled(self, before_missing: int) -> list[TimeframeFreshness]:
        """等 Parquet 落到磁盘上可见，最多轮询若干次。

        子进程退出后文件已关闭，但文件系统的目录项可能有一个极短的传播延迟。
        只在「缺口确实变少」时提前返回，否则重试到上限。
        """
        after = self.audit()
        for _ in range(_POST_SYNC_POLL_ATTEMPTS):
            missing = sum(item.tail_missing_closed + item.missing_in_gaps for item in after)
            if missing < before_missing:
                return after
            time.sleep(_POST_SYNC_POLL_INTERVAL_SECS)
            after = self.audit()
        return after


def _child_env() -> dict[str, str]:
    """给子进程准备环境变量：保证它能 import 到 ``pa_trend``。"""
    env = dict(os.environ)
    src_dir = str(PROJECT_ROOT / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src_dir if not existing else f"{src_dir}{os.pathsep}{existing}"
    # 采集器是无人值守进程，别让它继承交互式终端的颜色控制符。
    env.setdefault("NO_COLOR", "1")
    return env


__all__ = [
    "COLLECTOR_SCRIPT",
    "DEFAULT_SYNC_TIMEOUT_SECS",
    "MarketSyncService",
    "SyncResult",
]
