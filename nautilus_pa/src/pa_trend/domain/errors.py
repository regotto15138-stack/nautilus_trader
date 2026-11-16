"""价格行为趋势基线的异常层级。"""

from __future__ import annotations


class PaTrendError(Exception):
    """本包所有异常的基类。"""


class ConfigurationError(PaTrendError):
    """配置缺失或未通过启动门禁时抛出。"""


class DataIntegrityError(PaTrendError):
    """行情数据完整性相关异常的基类。"""


class BarValidationError(DataIntegrityError):
    """K 线违反 OHLCV 或成交量不变量时抛出。"""


class BarAlignmentError(DataIntegrityError):
    """K 线未落在其周期对应的 UTC 边界上时抛出。"""


class DataGapError(DataIntegrityError):
    """所需行情数据缺失时抛出。"""


class WarmupError(PaTrendError):
    """在指标预热完成前请求计算时抛出。"""
