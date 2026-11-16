"""价格行为趋势基线的 pytest 配置。"""

from __future__ import annotations

from pathlib import Path

import pytest

CONFIGS_DIR = Path(__file__).resolve().parents[1] / "configs"


@pytest.fixture
def configs_dir() -> Path:
    """返回冻结的配置目录。"""
    return CONFIGS_DIR
