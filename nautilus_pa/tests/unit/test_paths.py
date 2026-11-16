"""持久化路径约定测试。

采集可以从任意工作目录启动；catalog 路径必须是工程内固定位置，否则数据会
散落到不同目录，表现为「采集成功但读不到」。
"""

from __future__ import annotations

from pathlib import Path

from pa_trend.application import paths


def test_project_root_is_nautilus_pa() -> None:
    """工程根目录应指向 nautilus_pa。"""
    assert paths.PROJECT_ROOT.name == "nautilus_pa"
    assert (paths.PROJECT_ROOT / "pyproject.toml").is_file()


def test_default_catalog_is_inside_project() -> None:
    """默认 catalog 必须位于工程目录内。"""
    assert paths.DEFAULT_CATALOG_DIR.is_absolute()
    assert paths.DEFAULT_CATALOG_DIR.parent == paths.PROJECT_ROOT
    assert paths.DEFAULT_CATALOG_DIR.name == "catalog"


def test_none_resolves_to_default() -> None:
    """未提供路径时使用默认目录。"""
    assert paths.resolve_catalog_dir(None) == paths.DEFAULT_CATALOG_DIR


def test_empty_string_resolves_to_default() -> None:
    """空字符串等价于未提供。"""
    assert paths.resolve_catalog_dir("") == paths.DEFAULT_CATALOG_DIR


def test_relative_path_resolves_against_project_not_cwd(tmp_path: Path, monkeypatch) -> None:
    """相对路径应相对工程根目录解析，而不是进程当前目录。"""
    monkeypatch.chdir(tmp_path)
    resolved = paths.resolve_catalog_dir("catalog")
    assert resolved == paths.DEFAULT_CATALOG_DIR
    assert resolved != (tmp_path / "catalog")


def test_absolute_path_is_preserved(tmp_path: Path) -> None:
    """绝对路径原样使用。"""
    assert paths.resolve_catalog_dir(tmp_path) == tmp_path.resolve()


def test_web_dir_exists() -> None:
    """前端静态目录必须存在。"""
    assert (paths.WEB_DIR / "index.html").is_file()
    assert (paths.WEB_DIR / "app.js").is_file()


def test_configs_dir_exists() -> None:
    """配置目录必须存在且包含 V1.4.8 配置。"""
    assert (paths.DEFAULT_CONFIGS_DIR / "strategy_v1_4_8.yaml").is_file()
