"""工程内固定路径约定。

持久化数据必须落在工程目录内，而不是相对当前工作目录的 `catalog`：采集可以
从任意目录启动，相对路径会让数据散落到不同位置，导致「采集到了但看不到」。
"""

from __future__ import annotations

from pathlib import Path

#: 工程根目录（`nautilus_pa/`）。
PROJECT_ROOT = Path(__file__).resolve().parents[3]

#: 默认 Parquet 数据目录：`nautilus_pa/catalog`。
DEFAULT_CATALOG_DIR = PROJECT_ROOT / "catalog"

#: 默认配置目录。
DEFAULT_CONFIGS_DIR = PROJECT_ROOT / "configs"

#: 前端静态资源目录。
WEB_DIR = PROJECT_ROOT / "web"


def resolve_catalog_dir(value: Path | str | None) -> Path:
    """把用户传入的目录解析为绝对路径。

    ``None`` 或空字符串使用 :data:`DEFAULT_CATALOG_DIR`。相对路径按工程根目录
    解析，而不是按进程当前工作目录，保证无论从哪里启动都指向同一位置。
    """
    if value is None or str(value) == "":
        return DEFAULT_CATALOG_DIR
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()
