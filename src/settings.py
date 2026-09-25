"""应用配置（data/config.json）的读写与持久化。

配置只保存"用户偏好"这一类信息：快捷键、窗口行为、收藏、最近使用。
Prompt 正文永远保存在 prompts/ 下的 Markdown 文件里，配置文件不复制正文。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .fsutil import atomic_write_text
from .paths import CONFIG_FILE

#: 最近使用列表最多保留的条数。
MAX_RECENT = 20

SCHEMA_VERSION = 1

DEFAULT_HOTKEY = "Alt+Space"
DEFAULT_WINDOW_WIDTH = 820
DEFAULT_WINDOW_HEIGHT = 520
MIN_WINDOW_WIDTH = 340
MIN_WINDOW_HEIGHT = 360
MAX_WINDOW_WIDTH = 7680
MAX_WINDOW_HEIGHT = 4320

#: 界面基础字号（px）的默认值与允许区间，设置界面的 SpinBox 使用同一组常量。
DEFAULT_FONT_SIZE = 14
MIN_FONT_SIZE = 10
MAX_FONT_SIZE = 24


@dataclass
class Settings:
    """用户配置。字段名即 config.json 中的键名。"""

    hotkey: str = DEFAULT_HOTKEY
    always_on_top: bool = True
    hide_after_copy: bool = True
    #: 界面基础字号（px）。旧版配置没有这个键时沿用 DEFAULT_FONT_SIZE。
    font_size: int = DEFAULT_FONT_SIZE
    favorites: list[str] = field(default_factory=list)
    recent: list[str] = field(default_factory=list)
    window_width: int = DEFAULT_WINDOW_WIDTH
    window_height: int = DEFAULT_WINDOW_HEIGHT
    window_x: int | None = None
    window_y: int | None = None
    window_maximized: bool = False
    schema_version: int = SCHEMA_VERSION

    # ------------------------------------------------------------------
    # 读取与保存
    # ------------------------------------------------------------------
    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        """从磁盘读取配置，任何异常都回退到默认值而不是崩溃。"""
        config_path = path or CONFIG_FILE
        settings = cls()
        settings._config_path = config_path
        if not config_path.exists():
            return settings

        try:
            raw = config_path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, ValueError, UnicodeDecodeError):
            # 配置损坏时备份一份再回退默认值，不覆盖用户可能想手工抢救的数据。
            _quarantine(config_path)
            return settings

        if not isinstance(data, dict):
            _quarantine(config_path)
            return settings

        settings._apply(data)
        return settings

    def _apply(self, data: dict[str, Any]) -> None:
        """把磁盘上的字典按字段类型安全地合并进来。"""
        hotkey = data.get("hotkey")
        if isinstance(hotkey, str) and hotkey.strip():
            self.hotkey = hotkey.strip()

        for flag in ("always_on_top", "hide_after_copy", "window_maximized"):
            value = data.get(flag)
            if isinstance(value, bool):
                setattr(self, flag, value)

        for key in ("favorites", "recent"):
            value = data.get(key)
            if isinstance(value, list):
                cleaned = [item for item in value if isinstance(item, str) and item]
                setattr(self, key, _dedupe(cleaned))

        width = data.get("window_width")
        if isinstance(width, int) and not isinstance(width, bool):
            self.window_width = max(MIN_WINDOW_WIDTH, min(MAX_WINDOW_WIDTH, width))

        height = data.get("window_height")
        if isinstance(height, int) and not isinstance(height, bool):
            self.window_height = max(MIN_WINDOW_HEIGHT, min(MAX_WINDOW_HEIGHT, height))

        self.recent = self.recent[:MAX_RECENT]

        for key in ("window_x", "window_y"):
            value = data.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and abs(value) <= 100000:
                setattr(self, key, value)

        # 旧版配置没有 font_size：保持默认值，不报错、不覆盖。
        font_size = data.get("font_size")
        if isinstance(font_size, int) and not isinstance(font_size, bool):
            self.font_size = max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, font_size))

    def save(self, path: Path | None = None) -> None:
        """原子写入配置文件。"""
        config_path = path or getattr(self, "_config_path", CONFIG_FILE)
        self._config_path = config_path
        payload = asdict(self)
        payload["schema_version"] = SCHEMA_VERSION
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        atomic_write_text(config_path, text, newline="\n")

    def to_dict(self) -> dict[str, Any]:
        """返回可序列化的字典副本。"""
        return asdict(self)

    # ------------------------------------------------------------------
    # 收藏
    # ------------------------------------------------------------------
    def is_favorite(self, prompt_id: str) -> bool:
        return prompt_id in self.favorites

    def toggle_favorite(self, prompt_id: str) -> bool:
        """切换收藏状态，返回切换后是否为已收藏。"""
        if prompt_id in self.favorites:
            self.favorites.remove(prompt_id)
            return False
        self.favorites.append(prompt_id)
        return True

    # ------------------------------------------------------------------
    # 最近使用
    # ------------------------------------------------------------------
    def add_recent(self, prompt_id: str) -> None:
        """把 Prompt 记入最近使用（最新在前，最多 MAX_RECENT 条）。"""
        recent = [item for item in self.recent if item != prompt_id]
        recent.insert(0, prompt_id)
        self.recent = recent[:MAX_RECENT]

    def clear_recent(self) -> None:
        self.recent = []

    # ------------------------------------------------------------------
    # Prompt 标识迁移
    # ------------------------------------------------------------------
    def rename_id(self, old_id: str, new_id: str) -> None:
        """Prompt 被重命名/移动后，同步迁移收藏与最近使用记录。"""
        if old_id == new_id:
            return
        self.favorites = _dedupe(
            [new_id if item == old_id else item for item in self.favorites]
        )
        self.recent = _dedupe(
            [new_id if item == old_id else item for item in self.recent]
        )[:MAX_RECENT]

    def remove_id(self, prompt_id: str) -> None:
        """Prompt 被删除后，从收藏与最近使用中移除。"""
        self.favorites = [item for item in self.favorites if item != prompt_id]
        self.recent = [item for item in self.recent if item != prompt_id]

    def prune_ids(self, valid_ids: set[str]) -> bool:
        """丢弃指向已不存在文件的收藏/最近记录，返回是否有变化。"""
        favorites = [item for item in self.favorites if item in valid_ids]
        recent = [item for item in self.recent if item in valid_ids]
        changed = favorites != self.favorites or recent != self.recent
        self.favorites = favorites
        self.recent = recent
        return changed


def _dedupe(items: list[str]) -> list[str]:
    """保持原顺序去重。"""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _quarantine(path: Path) -> None:
    """把损坏的配置文件改名为 .bak，保留现场。"""
    backup = path.with_suffix(path.suffix + ".bak")
    try:
        if backup.exists():
            backup.unlink()
        path.replace(backup)
    except OSError:
        pass


__all__ = [
    "DEFAULT_FONT_SIZE",
    "DEFAULT_HOTKEY",
    "DEFAULT_WINDOW_HEIGHT",
    "DEFAULT_WINDOW_WIDTH",
    "MAX_FONT_SIZE",
    "MAX_RECENT",
    "MIN_FONT_SIZE",
    "MIN_WINDOW_HEIGHT",
    "MIN_WINDOW_WIDTH",
    "Settings",
]
