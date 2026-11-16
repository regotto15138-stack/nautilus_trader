"""价格行为趋势基线的 NautilusTrader 适配层。

``bar_converter`` 在未安装 NautilusTrader 时也可导入；``collector`` 与
``strategy`` 依赖 v2 运行时，由调用方显式导入，例如
``from pa_trend.adapters.nautilus.strategy import PaTrendStrategy``。
"""

__all__: list[str] = []
