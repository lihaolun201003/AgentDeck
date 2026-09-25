"""设置对话框：全局快捷键、窗口行为、界面字体大小。"""

from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..hotkey import HotkeyError, IS_WINDOWS, describe_error, parse_hotkey, probe_hotkey
from ..paths import CONFIG_FILE
from ..settings import DEFAULT_FONT_SIZE, MAX_FONT_SIZE, MIN_FONT_SIZE
from .theme import clamp_font_size, set_state

_MODIFIER_KEYS = {
    Qt.Key_Control,
    Qt.Key_Shift,
    Qt.Key_Alt,
    Qt.Key_Meta,
    Qt.Key_AltGr,
    Qt.Key_unknown,
}


class HotkeyLineEdit(QLineEdit):
    """快捷键输入框：聚焦后直接按组合键即可录入，也允许手工输入。"""

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt 命名风格
        key = event.key()

        if key == Qt.Key_Escape:
            super().keyPressEvent(event)
            return

        if key in _MODIFIER_KEYS:
            return

        if key in (Qt.Key_Backspace, Qt.Key_Delete) and not event.modifiers():
            self.clear()
            event.accept()
            return

        modifiers = event.modifiers()
        parts: list[str] = []
        if modifiers & Qt.ControlModifier:
            parts.append("Ctrl")
        if modifiers & Qt.AltModifier:
            parts.append("Alt")
        if modifiers & Qt.ShiftModifier:
            parts.append("Shift")
        if modifiers & Qt.MetaModifier:
            parts.append("Win")

        key_text = QKeySequence(key).toString()
        if not key_text:
            return
        parts.append(key_text)

        self.setText("+".join(parts))
        event.accept()


class SettingsDialog(QDialog):
    """读取并返回用户设置，不直接写文件。"""

    def __init__(
        self,
        hotkey: str,
        always_on_top: bool,
        hide_after_copy: bool,
        parent: QWidget | None = None,
        font_size: int = DEFAULT_FONT_SIZE,
    ) -> None:
        super().__init__(parent)
        self._original_hotkey = hotkey
        self._initial_font_size = clamp_font_size(font_size)

        self.setWindowTitle("AgentDeck 设置")
        self.setModal(True)
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        # --- 全局快捷键 ---
        label = QLabel("Global Hotkey（全局快捷键）")
        label.setObjectName("FieldLabel")
        layout.addWidget(label)

        self._hotkey_edit = HotkeyLineEdit(hotkey)
        self._hotkey_edit.setPlaceholderText("例如：Alt+Space")
        layout.addWidget(self._hotkey_edit)

        self._hotkey_status = QLabel("")
        self._hotkey_status.setObjectName("HintLabel")
        self._hotkey_status.setWordWrap(True)
        layout.addWidget(self._hotkey_status)

        if not IS_WINDOWS:
            self._hotkey_edit.setEnabled(False)
            self._hotkey_status.setText("当前平台不支持全局快捷键（仅 Windows）。")

        layout.addSpacing(6)

        # --- 行为开关 ---
        self._top_check = QCheckBox("窗口置顶（Always on Top）")
        self._top_check.setChecked(always_on_top)
        layout.addWidget(self._top_check)

        self._hide_check = QCheckBox("复制后自动隐藏窗口（Hide after Copy）")
        self._hide_check.setChecked(hide_after_copy)
        layout.addWidget(self._hide_check)

        layout.addSpacing(6)

        # --- 界面字体大小 ---
        font_label = QLabel("Font Size / 字体大小")
        font_label.setObjectName("FieldLabel")
        layout.addWidget(font_label)

        font_row = QHBoxLayout()
        font_row.setSpacing(8)

        self._font_spin = QSpinBox()
        self._font_spin.setRange(MIN_FONT_SIZE, MAX_FONT_SIZE)
        self._font_spin.setSingleStep(1)
        self._font_spin.setSuffix(" px")
        self._font_spin.setValue(self._initial_font_size)
        self._font_spin.setToolTip("AgentDeck 整个界面的基础字体大小，调整后立即预览")
        font_row.addWidget(self._font_spin)

        self._font_reset = QPushButton("Reset to Default")
        self._font_reset.setToolTip(f"恢复默认的 {DEFAULT_FONT_SIZE} px")
        self._font_reset.clicked.connect(
            lambda: self._font_spin.setValue(DEFAULT_FONT_SIZE)
        )
        font_row.addWidget(self._font_reset)

        font_row.addStretch(1)
        layout.addLayout(font_row)

        font_hint = QLabel("影响列表、预览、对话框与菜单；保存后立即生效。")
        font_hint.setObjectName("HintLabel")
        font_hint.setWordWrap(True)
        layout.addWidget(font_hint)

        layout.addSpacing(6)

        # --- 配置文件位置 ---
        path_hint = QLabel(f"配置文件：{CONFIG_FILE}")
        path_hint.setObjectName("PathLabel")
        path_hint.setWordWrap(True)
        path_hint.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(path_hint)

        open_button = QPushButton("打开配置目录")
        open_button.clicked.connect(self._open_config_dir)
        open_row = QHBoxLayout()
        open_row.addWidget(open_button)
        open_row.addStretch(1)
        layout.addLayout(open_row)

        layout.addStretch(1)

        # --- 按钮 ---
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)

        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(cancel_button)

        save_button = QPushButton("保存")
        save_button.setObjectName("Primary")
        save_button.setDefault(True)
        save_button.clicked.connect(self._on_accept)
        buttons.addWidget(save_button)

        layout.addLayout(buttons)

        QShortcut(QKeySequence("Esc"), self, activated=self.reject)
        self._hotkey_edit.textChanged.connect(self._validate_hotkey)
        self._font_spin.valueChanged.connect(self._preview_font_size)
        self._validate_hotkey()

    # ------------------------------------------------------------------
    def hotkey(self) -> str:
        return self._hotkey_edit.text().strip()

    def always_on_top(self) -> bool:
        return self._top_check.isChecked()

    def hide_after_copy(self) -> bool:
        return self._hide_check.isChecked()

    def font_size(self) -> int:
        return self._font_spin.value()

    # ------------------------------------------------------------------
    def _preview_font_size(self, size: int) -> None:
        """让主窗口实时预览新字号（父窗口不在时不预览，照样能保存）。"""
        hook = getattr(self.parent(), "set_font_size", None)
        if callable(hook):
            hook(size)

    def reject(self) -> None:
        """取消时把字号改回去，避免留下"预览过但没保存"的界面。"""
        self._preview_font_size(self._initial_font_size)
        super().reject()

    # ------------------------------------------------------------------
    def _validate_hotkey(self) -> None:
        """实时校验格式；格式错误时阻止保存。"""
        raw = self.hotkey()
        if not raw:
            self._set_hotkey_status("请填写快捷键，例如 Alt+Space", "error")
            return
        try:
            parse_hotkey(raw)
        except HotkeyError as exc:
            self._set_hotkey_status(f"格式错误：{exc}", "error")
            return

        if not IS_WINDOWS:
            return
        if raw.casefold() == self._original_hotkey.casefold():
            self._set_hotkey_status("当前正在使用的快捷键。", "muted")
            return
        available, reason = probe_hotkey(raw)
        if available:
            self._set_hotkey_status("快捷键可用。", "ok")
        else:
            self._set_hotkey_status(f"暂时无法注册：{reason}", "error")

    def _set_hotkey_status(self, text: str, state: str) -> None:
        """状态文字的颜色与字号由主题样式表统一决定。"""
        set_state(self._hotkey_status, state)
        self._hotkey_status.setText(text)

    def _on_accept(self) -> None:
        try:
            parse_hotkey(self.hotkey())
        except HotkeyError:
            return
        self.accept()

    def _open_config_dir(self) -> None:
        directory = CONFIG_FILE.parent
        directory.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(str(directory))  # noqa: S606 - 打开本地目录
            else:
                subprocess.Popen(["xdg-open", str(directory)])
        except OSError:
            pass


__all__ = ["HotkeyLineEdit", "SettingsDialog"]
