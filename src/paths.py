"""应用路径解析。

开发模式和 PyInstaller 打包模式共用同一套约定：

* 开发模式：以项目根目录（本包的上一级）作为数据根目录。
* 打包模式：以 AgentDeck.exe 所在目录作为数据根目录，这样 prompts/ 与
  data/ 始终位于用户可见、可写的位置，而不是解压出来的临时目录。
"""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包出的可执行文件中。"""
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """返回数据根目录（prompts/ 与 data/ 的父目录）。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


APP_ROOT: Path = app_root()
PROMPTS_DIR: Path = APP_ROOT / "prompts"
DATA_DIR: Path = APP_ROOT / "data"
CONFIG_FILE: Path = DATA_DIR / "config.json"

__all__ = [
    "APP_ROOT",
    "CONFIG_FILE",
    "DATA_DIR",
    "PROMPTS_DIR",
    "app_root",
    "is_frozen",
]
