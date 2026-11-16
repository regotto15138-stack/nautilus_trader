"""NautilusTrader 策略外壳：把七周期 K 线路由到多周期识别上下文。

本基线中策略不做任何交易。外壳只负责：接收 K 线、转换、调用 ``MarketContext``、
记录状态变化。Setup / Signal / 执行 / 风控（规格第 10 至 17 章）尚未实现，
因此不存在可能被误开启的下单路径。
"""

from __future__ import annotations

from pathlib import Path

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model import Bar, BarType, InstrumentId
from nautilus_trader.trading import Strategy

from pa_trend.adapters.nautilus.bar_converter import to_domain_bar
from pa_trend.application.market_context import MarketContext
from pa_trend.config.loader import load_config
from pa_trend.config.validation import Stage, validate_startup
from pa_trend.domain.errors import BarAlignmentError
from pa_trend.domain.models.timeframe import Timeframe


class PaTrendStrategyConfig(StrategyConfig):
    """:class:`PaTrendStrategy` 的配置。"""

    def __init__(
        self,
        *,
        instrument_id: str,
        configs_dir: str,
        session_offset_hours: int | None = None,
        **_kwargs: object,
    ) -> None:
        """初始化配置。

        参数
        ----
        instrument_id : str
            合约标识，例如 ``ETH-USDT-SWAP.OKX``。
        configs_dir : str
            存放五个冻结 YAML 配置文件的目录。
        session_offset_hours : int 或 None
            会话偏移；缺省取 ``research.session_offset_hours``。
        """
        super().__init__()
        self.instrument_id = instrument_id
        self.configs_dir = configs_dir
        self.session_offset_hours = session_offset_hours


class PaTrendStrategy(Strategy):
    """V1.4.8 多周期趋势识别（只识别，不下单）。"""

    def __init__(self, config: PaTrendStrategyConfig) -> None:
        """初始化策略。"""
        super().__init__(config)
        self._pa_config = load_config(Path(config.configs_dir))
        self._startup = validate_startup(self._pa_config, Stage.RESEARCH_STRUCTURE)
        self._context = MarketContext(self._pa_config)
        self._instrument_id = InstrumentId.from_str(config.instrument_id)
        self._session_offset_hours = (
            self._pa_config.research.session_offset_hours
            if config.session_offset_hours is None
            else config.session_offset_hours
        )
        self._bar_type_by_key: dict[str, Timeframe] = {
            self._bar_type_key(timeframe): timeframe
            for timeframe in self._pa_config.timeframes.all()
        }
        self._last_states: dict[Timeframe, str | None] = dict.fromkeys(
            self._pa_config.timeframes.all(),
        )
        self._alignment_errors = 0

    def _bar_type_key(self, timeframe: Timeframe) -> str:
        return f"{self._instrument_id}-{timeframe.bar_spec}-LAST-EXTERNAL"

    @property
    def market_context(self) -> MarketContext:
        """返回多周期上下文，便于研究侧检查。"""
        return self._context

    def on_start(self) -> None:
        """订阅全部七个周期的 K 线。"""
        self.log.info(
            f"V1.4.8 多周期识别启动: instrument={self._instrument_id} "
            f"stage={self._startup.stage.value} "
            f"session=UTC+{self._session_offset_hours} "
            f"timeframes={[tf.value for tf in self._pa_config.timeframes.all()]}",
        )
        for key in self._bar_type_by_key:
            self.subscribe_bars(BarType.from_str(key))

    def on_bar(self, bar: Bar) -> None:
        """把完成 K 线送入对应周期的引擎，并记录状态变化。

        对时间边界不合法（例如会话偏移设置错误）的 K 线不再向上抛出异常：在实盘
        节点中那会让整个策略 fault。这里记录错误、计数并跳过；对应周期状态会停留
        在 UNKNOWN，按规格第 8.5 节禁止新开仓，属安全降级。
        """
        timeframe = self._bar_type_by_key.get(str(bar.bar_type))
        if timeframe is None:
            self.log.debug(f"忽略未订阅的 K 线类型: {bar.bar_type}")
            return

        try:
            domain_bar = to_domain_bar(
                bar,
                timeframe,
                instrument_id=str(self._instrument_id),
                session_offset_minutes=self._session_offset_hours * 60,
            )
        except BarAlignmentError as exc:
            self._alignment_errors += 1
            self.log.error(
                f"拒绝未对齐的 {timeframe.value} K 线（累计 {self._alignment_errors} 条）: {exc}",
            )
            return

        self._context.on_bar(domain_bar)
        self._report_state_change(timeframe)

    def _report_state_change(self, timeframe: Timeframe) -> None:
        engine = self._context.engine(timeframe)
        current = None if engine.state is None else str(engine.state)
        if current == self._last_states[timeframe]:
            return
        self._last_states[timeframe] = current
        if current is None:
            return
        self.log.info(
            f"状态变化: {timeframe.value} → {current} "
            f"收盘={engine.last_bar.close if engine.last_bar else None} "
            f"ProtectedLow={engine.levels.snapshot.protected_low} "
            f"ProtectedHigh={engine.levels.snapshot.protected_high}",
        )

    def on_stop(self) -> None:
        """记录最终的多周期快照。"""
        snapshot = self._context.snapshot()
        for timeframe in self._pa_config.timeframes.all():
            engine = self._context.engine(timeframe)
            self.log.info(
                f"停止: {timeframe.value} 状态={engine.state} K线={engine.bar_count} "
                f"摆动点={len(engine.swings)} "
                f"N结构={len(engine.structures.structures)}",
            )
        self.log.info(
            f"宏观: 1M={snapshot.month.value} 1W={snapshot.week.value} "
            f"1D={snapshot.day.value} 4H={snapshot.h4.value} 1H={snapshot.h1.value} "
            f"CanOpen={snapshot.can_open} CanHold={snapshot.can_hold}",
        )
        if self._alignment_errors:
            self.log.warning(f"累计拒绝未对齐 K 线: {self._alignment_errors}")
