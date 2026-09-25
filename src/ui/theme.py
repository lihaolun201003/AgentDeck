"""白色主题：调色板 + 样式表 + 全局界面字号。

白色背景、浅灰输入区、深色文字与蓝色选中态。
不使用渐变、不使用大圆角，保持紧凑的桌面小工具观感。

界面字号只有 :func:`apply_theme` / :func:`apply_font_size` 两个入口：
它们同时更新 ``QApplication`` 的默认字体和整份样式表，因此列表、对话框、
右键菜单、消息框以及之后新建的窗口都会跟着变。样式表内的字号一律由
``BASE_FONT_SIZE`` 等比换算，不在这里之外写死 px。
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QWidget

# --- 调色板 ----------------------------------------------------------------
BG_ROOT = "#ffffff"
BG_PANEL = "#f8fafc"
BG_INPUT = "#f5f7fa"
BG_HOVER = "#edf1f6"
BG_SELECTED = "#e3eeff"
BG_BORDER = "#d2d9e3"
BG_DIVIDER = "#e2e7ee"

TEXT_PRIMARY = "#202939"
TEXT_SECONDARY = "#4b5565"
TEXT_MUTED = "#667085"

ACCENT = "#2563c9"
SUCCESS = "#237a42"
DANGER = "#c13d38"
WARNING = "#92540b"

# --- 字体 ------------------------------------------------------------------
#: 界面基础字号的默认值（px）。与 ``Settings.font_size`` 的默认值保持一致。
BASE_FONT_SIZE = 14
MIN_FONT_SIZE = 10
MAX_FONT_SIZE = 24

#: 界面字体候选，按可用性依次回退。
UI_FONT_FAMILIES = ["Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei"]
UI_FONTS = ", ".join(f'"{name}"' for name in UI_FONT_FAMILIES) + ", sans-serif"
MONO_FONTS = '"Cascadia Mono", "JetBrains Mono", "Consolas", "Microsoft YaHei UI"'

#: 当前生效的基础字号，由 apply_theme / apply_font_size 维护。
_current_font_size = BASE_FONT_SIZE


def clamp_font_size(size: object) -> int:
    """把任意输入收敛到 ``[MIN_FONT_SIZE, MAX_FONT_SIZE]``；非数字回退默认值。"""
    if isinstance(size, bool) or not isinstance(size, (int, float)):
        return BASE_FONT_SIZE
    return max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, int(round(size))))


def current_font_size() -> int:
    """当前界面基础字号（px）。"""
    return _current_font_size


def scaled(px: float) -> int:
    """把"按默认字号设计"的像素值换算到当前字号下，供控件尺寸使用。

    字体放大后固定高度会裁字，所以布局尺寸统一走这里换算。
    """
    return max(0, int(round(px * _current_font_size / BASE_FONT_SIZE)))


def _style_font_size(base: int) -> int:
    """样式表内的字号：同样按当前基础字号等比缩放，至少 1px。"""
    return max(1, int(round(base * _current_font_size / BASE_FONT_SIZE)))


def ui_font() -> QFont:
    """按当前字号构造界面默认字体。"""
    font = QFont()
    font.setFamilies(UI_FONT_FAMILIES)
    font.setPixelSize(_current_font_size)
    return font


def set_state(widget: QWidget, state: str) -> None:
    """更新驱动样式表的状态属性，并立即重绘该控件。

    QSS 里的 ``[state="error"]`` 一类选择器只在 polish 时求值，
    运行时改属性必须手动 unpolish/polish 才会变色。
    """
    if widget.property("state") == state:
        return
    widget.setProperty("state", state)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def build_stylesheet() -> str:
    """按当前基础字号生成整份样式表。"""
    fs = _style_font_size
    base = _current_font_size

    return f"""
* {{
    font-family: {UI_FONTS};
    font-size: {base}px;
}}

QWidget {{
    background-color: {BG_ROOT};
    color: {TEXT_PRIMARY};
}}

QDialog {{
    background-color: {BG_ROOT};
}}

/* ---------- 标题栏 ---------- */
QWidget#TitleBar {{
    background-color: {BG_ROOT};
}}
QLabel#AppTitle {{
    color: {TEXT_MUTED};
    font-size: {fs(12)}px;
    font-weight: 600;
    letter-spacing: 1px;
}}
QPushButton#IconButton {{
    background-color: transparent;
    border: none;
    border-radius: 4px;
    color: {TEXT_SECONDARY};
    font-size: {fs(15)}px;
    padding: 1px 7px;
}}
QPushButton#IconButton:hover {{
    background-color: {BG_HOVER};
    color: {TEXT_PRIMARY};
}}
QPushButton#IconButton:pressed {{
    background-color: {BG_SELECTED};
}}
QPushButton#CompactButton {{
    padding: 2px 10px;
    color: {ACCENT};
    background-color: {BG_SELECTED};
    border: none;
}}

/* ---------- 搜索框 ---------- */
QLineEdit#SearchInput {{
    background-color: {BG_INPUT};
    border: 1px solid {BG_BORDER};
    border-radius: 6px;
    padding: 7px 10px;
    color: {TEXT_PRIMARY};
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
}}
QLineEdit#SearchInput:focus {{
    border: 1px solid {ACCENT};
}}

/* ---------- 列表 ---------- */
QListWidget {{
    background-color: transparent;
    border: none;
    outline: none;
}}
QListWidget::item {{
    border: none;
    padding: 0px;
}}
QListWidget::item:selected,
QListWidget::item:selected:active,
QListWidget::item:selected:!active {{
    background-color: transparent;
    color: {TEXT_PRIMARY};
}}
QListWidget::item:hover {{
    background-color: transparent;
}}

/* ---------- 预览区 ---------- */
QLabel#PreviewTitle {{
    font-weight: 600;
}}
QPlainTextEdit#Preview {{
    background-color: {BG_PANEL};
    border: 1px solid {BG_DIVIDER};
    border-radius: 6px;
    padding: 8px 10px;
    color: {TEXT_PRIMARY};
    font-family: {MONO_FONTS};
    font-size: {fs(12)}px;
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
}}

/* ---------- 分隔线 ---------- */
QFrame#Divider {{
    background-color: {BG_DIVIDER};
    border: none;
    max-height: 1px;
}}

/* ---------- 按钮 ---------- */
QPushButton {{
    background-color: {BG_ROOT};
    border: 1px solid {BG_BORDER};
    border-radius: 5px;
    padding: 5px 14px;
    color: {TEXT_PRIMARY};
}}
QPushButton:hover {{
    background-color: {BG_HOVER};
}}
QPushButton:pressed {{
    background-color: {BG_SELECTED};
}}
QPushButton:disabled {{
    color: {TEXT_MUTED};
    background-color: {BG_INPUT};
}}
QPushButton#Primary {{
    background-color: {ACCENT};
    border: 1px solid {ACCENT};
    color: #ffffff;
}}
QPushButton#Primary:hover {{
    background-color: #1d53ae;
}}
QPushButton#Primary:default {{
    border: 1px solid #174489;
}}

/* ---------- 输入控件 ---------- */
QLineEdit, QPlainTextEdit, QTextEdit {{
    background-color: {BG_INPUT};
    border: 1px solid {BG_BORDER};
    border-radius: 5px;
    padding: 5px 8px;
    color: {TEXT_PRIMARY};
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border: 1px solid {ACCENT};
}}
QPlainTextEdit#EditorContent {{
    font-family: {MONO_FONTS};
    font-size: {fs(12)}px;
}}

/* QComboBox、QCheckBox 与 QSpinBox 交给 Fusion 绘制：
   自定义样式会丢掉下拉箭头、勾选标记和上下箭头。 */
QComboBox QAbstractItemView {{
    background-color: {BG_ROOT};
    border: 1px solid {BG_BORDER};
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
    color: {TEXT_PRIMARY};
    outline: none;
}}

QCheckBox {{
    spacing: 8px;
    color: {TEXT_PRIMARY};
}}

/* ---------- 标签 ---------- */
QLabel#FieldLabel {{
    color: {TEXT_SECONDARY};
}}
QLabel#DialogTitle {{
    font-weight: 600;
}}
QLabel#HintLabel {{
    color: {TEXT_MUTED};
    font-size: {fs(12)}px;
}}
QLabel#HintLabel[state="ok"] {{
    color: {SUCCESS};
}}
QLabel#HintLabel[state="error"] {{
    color: {DANGER};
}}
QLabel#HintLabel[state="muted"] {{
    color: {TEXT_MUTED};
}}
QLabel#StatusLabel {{
    color: {TEXT_SECONDARY};
    font-size: {fs(12)}px;
}}
QLabel#PathLabel {{
    color: {TEXT_MUTED};
    font-size: {fs(11)}px;
}}
QLabel#WarningLabel {{
    color: {DANGER};
    font-size: {fs(12)}px;
}}
QLabel#WarningLabel[state="muted"] {{
    color: {TEXT_MUTED};
}}
QLabel#WarningLabel[state="warning"] {{
    color: {WARNING};
}}
QLabel#ToastLabel {{
    color: {SUCCESS};
    font-size: {fs(12)}px;
    font-weight: 600;
}}
QLabel#ToastLabel[state="error"] {{
    color: {DANGER};
}}

/* ---------- 菜单 ---------- */
QMenu {{
    background-color: {BG_ROOT};
    border: 1px solid {BG_BORDER};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 26px 6px 14px;
    border-radius: 4px;
    color: {TEXT_PRIMARY};
}}
QMenu::item:selected {{
    background-color: {ACCENT};
    color: #ffffff;
}}
QMenu::item:disabled {{
    color: {TEXT_MUTED};
}}
QMenu::separator {{
    height: 1px;
    background-color: {BG_DIVIDER};
    margin: 4px 8px;
}}

/* ---------- 消息框 ---------- */
QMessageBox {{
    background-color: {BG_ROOT};
}}
QMessageBox QLabel {{
    color: {TEXT_PRIMARY};
}}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px 2px 2px 0px;
}}
QScrollBar::handle:vertical {{
    background: #c5cbd5;
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: #9ba5b4;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
}}
QScrollBar::handle:horizontal {{
    background: #c5cbd5;
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0px;
    width: 0px;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

/* ---------- 分隔器 ---------- */
QSplitter::handle {{
    background-color: {BG_DIVIDER};
    width: 1px;
}}
QSplitter::handle:hover {{
    background-color: {ACCENT};
}}

QToolTip {{
    background-color: {BG_ROOT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BG_BORDER};
    padding: 4px 6px;
}}
"""


def apply_theme(app: QApplication, font_size: object = None) -> None:
    """把白色主题与界面字号应用到整个应用。"""
    _set_font_size(clamp_font_size(font_size if font_size is not None else BASE_FONT_SIZE))
    app.setStyle("Fusion")
    app.setPalette(_light_palette())
    app.setFont(ui_font())
    app.setStyleSheet(build_stylesheet())


def apply_font_size(app: QApplication | None, font_size: object) -> int:
    """切换界面字号并立即刷新，返回实际生效的字号。

    样式表是应用级的，所以主窗口、对话框、菜单和之后新建的窗口都会用新字号。
    """
    size = clamp_font_size(font_size)
    if app is None or size == _current_font_size:
        return size
    _set_font_size(size)
    app.setFont(ui_font())
    app.setStyleSheet(build_stylesheet())
    return size


def _set_font_size(size: int) -> None:
    global _current_font_size
    _current_font_size = size


def _light_palette() -> QPalette:
    """Fusion 风格下的浅色调色板，用于 QSS 覆盖不到的原生控件。"""
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(BG_ROOT))
    palette.setColor(QPalette.WindowText, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.Base, QColor(BG_INPUT))
    palette.setColor(QPalette.AlternateBase, QColor(BG_PANEL))
    palette.setColor(QPalette.Text, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.Button, QColor(BG_ROOT))
    palette.setColor(QPalette.ButtonText, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ToolTipBase, QColor(BG_ROOT))
    palette.setColor(QPalette.ToolTipText, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.PlaceholderText, QColor(TEXT_MUTED))
    palette.setColor(QPalette.Link, QColor(ACCENT))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(TEXT_MUTED))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(TEXT_MUTED))
    return palette


__all__ = [
    "ACCENT",
    "BASE_FONT_SIZE",
    "DANGER",
    "MAX_FONT_SIZE",
    "MIN_FONT_SIZE",
    "SUCCESS",
    "TEXT_MUTED",
    "WARNING",
    "apply_font_size",
    "apply_theme",
    "build_stylesheet",
    "clamp_font_size",
    "current_font_size",
    "scaled",
    "set_state",
    "ui_font",
]
