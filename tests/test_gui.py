"""界面与交互测试：剪贴板、Esc 隐藏、Enter/双击复制、全局快捷键呼出。

默认使用 Qt 的 offscreen 平台，不会在屏幕上弹出窗口。
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

# 必须在导入 PySide6 之前设置，保证 CI / 无人值守环境下也能跑。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRect, Qt  # noqa: E402
from PySide6.QtGui import QFont, QFontMetrics, QGuiApplication  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.clipboard import copy_text, read_text  # noqa: E402
from src.fsutil import atomic_write_text  # noqa: E402
from src.hotkey import IS_WINDOWS, HotkeyListener, parse_hotkey, probe_hotkey  # noqa: E402
from src.prompt_store import PromptStore  # noqa: E402
from src.settings import DEFAULT_FONT_SIZE, MAX_FONT_SIZE, MIN_FONT_SIZE, Settings  # noqa: E402
from src.ui.main_window import (  # noqa: E402
    ALL_KEY,
    RECENT_KEY,
    TITLE_BAR_HEIGHT,
    MainWindow,
)
from src.ui.prompt_editor import PromptEditorDialog  # noqa: E402
from src.ui.settings_dialog import SettingsDialog  # noqa: E402
from src.ui.theme import (  # noqa: E402
    BASE_FONT_SIZE,
    apply_font_size,
    current_font_size,
    scaled,
)
from src.ui.variable_dialog import VariableDialog  # noqa: E402
from src.ui.window_placement import right_panel_rect  # noqa: E402

VK_MENU = 0x12
VK_SPACE = 0x20
KEYEVENTF_KEYUP = 0x0002


# ----------------------------------------------------------------------
# 基础设施
# ----------------------------------------------------------------------
@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    return app


def wait_until(predicate: Callable[[], bool], timeout_ms: int = 3000) -> bool:
    """等待条件成立，同时驱动事件循环处理跨线程信号。"""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    QApplication.processEvents()
    return predicate()


def press_alt_space() -> None:
    """用 Win32 API 真实模拟一次 Alt+Space 按键。"""
    user32 = ctypes.WinDLL("user32")
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_SPACE, 0, 0, 0)
    user32.keybd_event(VK_SPACE, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)


@pytest.fixture()
def window(qapp: QApplication, tmp_path: Path) -> MainWindow:
    """构建一个使用临时 prompts 目录的主窗口。"""
    root = tmp_path / "prompts"
    atomic_write_text(root / "Research" / "精读论文.md", "精读本文：研究问题｜核心贡献。\n")
    atomic_write_text(root / "Coding" / "Bug诊断.md", "先复现并定位真实根因。\n")
    atomic_write_text(
        root / "Coding" / "项目诊断.md",
        "请检查以下项目：\n\n{{PROJECT_PATH}}\n\n当前任务：{{TASK}}\n",
    )

    store = PromptStore(root)
    settings = Settings()
    settings.save(tmp_path / "config.json")

    win = MainWindow(store, settings)
    yield win
    win.hide()
    win.deleteLater()
    qapp.processEvents()


# ----------------------------------------------------------------------
# 9. 剪贴板复制
# ----------------------------------------------------------------------
def test_clipboard_copy_roundtrip(qapp: QApplication) -> None:
    text = "中文内容 + emoji ✅\n第二行\t带制表符"
    assert copy_text(text) is True
    assert read_text() == text


def test_clipboard_preserves_prompt_exactly(qapp: QApplication) -> None:
    content = "请检查以下项目：\n\n{{PROJECT_PATH}}\n\n要求找出真实根因。\n"
    assert copy_text(content) is True
    assert read_text() == content


# ----------------------------------------------------------------------
# 12. Enter 复制
# ----------------------------------------------------------------------
def test_enter_copies_selected_prompt(qapp: QApplication, window: MainWindow) -> None:
    window.show_launcher()
    qapp.processEvents()

    first = window.current_prompt()
    assert first is not None

    QTest.keyClick(window._search, Qt.Key_Return)
    qapp.processEvents()

    assert read_text() == first.content
    assert window._settings.recent[0] == first.id


def test_double_click_copies_prompt(qapp: QApplication, window: MainWindow) -> None:
    window.show_launcher()
    qapp.processEvents()

    row = next(index for index, prompt in enumerate(window._visible) if not prompt.has_variables)
    item = window._list.item(row)
    assert item is not None
    rect = window._list.visualItemRect(item)
    QTest.mouseDClick(window._list.viewport(), Qt.LeftButton, pos=rect.center())
    qapp.processEvents()

    prompt = window._prompts_by_id[item.data(Qt.UserRole)]
    assert read_text() == prompt.content


def test_arrow_keys_move_selection(qapp: QApplication, window: MainWindow) -> None:
    window.show_launcher()
    qapp.processEvents()

    assert window.current_prompt() is not None
    first = window.current_prompt()
    QTest.keyClick(window._search, Qt.Key_Down)
    qapp.processEvents()
    assert window.current_prompt() is not first

    QTest.keyClick(window._search, Qt.Key_Up)
    qapp.processEvents()
    assert window.current_prompt() == first


@pytest.mark.parametrize("navigation", ["mouse", "list_keyboard", "search_keyboard"])
def test_selection_updates_preview(qapp: QApplication, window: MainWindow, navigation: str) -> None:
    """点击或按方向键换条目时，标题、正文、路径及收藏必须一起更新。"""
    window.show_launcher()
    qapp.processEvents()
    target = window._visible[1]
    window._settings.toggle_favorite(target.id)

    if navigation == "mouse":
        rect = window._list.visualItemRect(window._list.item(1))
        QTest.mouseClick(window._list.viewport(), Qt.LeftButton, pos=rect.center())
    elif navigation == "list_keyboard":
        window._list.setFocus()
        QTest.keyClick(window._list, Qt.Key_Down)
    else:
        QTest.keyClick(window._search, Qt.Key_Down)
    qapp.processEvents()

    assert window.current_prompt() == target
    assert window._preview_title.text() == target.name
    assert window._preview.toPlainText() == target.content
    assert target.path.name in window._preview_meta.text()
    assert window._favorite_button.text() == "★"


def test_search_with_no_results_clears_preview(qapp: QApplication, window: MainWindow) -> None:
    window.show_launcher()
    window._search.setText("不存在的提示词")
    qapp.processEvents()

    assert window.current_prompt() is None
    assert window._preview.toPlainText() == ""
    assert window._preview_meta.text() == ""
    assert not window._favorite_button.isEnabled()

    window._search.clear()
    qapp.processEvents()
    assert window._preview.toPlainText() == window.current_prompt().content


@pytest.mark.parametrize("width", [340, 420, 640])
def test_narrow_window_keeps_filter_preview_and_copy_usable(qapp, window, width):
    window.show_launcher()
    window.resize(width, 760)
    qapp.processEvents()
    assert window.width() == width
    assert window._browser.compact
    assert window._browser.categories.isVisible()
    assert not window._sidebar.isVisible()
    assert window._splitter.orientation() == Qt.Vertical

    combo = window._browser.categories
    combo.setCurrentIndex(combo.findData("Coding"))
    qapp.processEvents()
    assert all(p.category == "Coding" for p in window._visible)
    target = window._visible[1]
    QTest.mouseClick(window._list.viewport(), Qt.LeftButton,
                     pos=window._list.visualItemRect(window._list.item(1)).center())
    qapp.processEvents()
    assert window._preview.toPlainText() == target.content
    assert window._copy_button.isVisible()
    assert window._copy_button.width() > 200
    assert window._preview.width() > 200


def test_wide_layout_restores_without_losing_selection(qapp, window):
    window.show_launcher()
    window.resize(420, 760)
    qapp.processEvents()
    window._list.setCurrentRow(1)
    target = window.current_prompt()
    window.resize(1000, 650)
    qapp.processEvents()
    assert not window._browser.compact
    assert window._sidebar.isVisible()
    assert not window._browser.categories.isVisible()
    assert window._splitter.orientation() == Qt.Horizontal
    assert window.current_prompt() == target
    assert window._preview.toPlainText() == target.content


def test_copy_button_keeps_panel_visible_when_auto_hide_disabled(qapp, window):
    window.show_launcher()
    window._settings.hide_after_copy = False
    window.resize(420, 760)
    qapp.processEvents()
    target = window.current_prompt()
    hidden = []
    window.request_hide.connect(lambda: hidden.append(True))
    QTest.mouseClick(window._copy_button, Qt.LeftButton)
    QTest.qWait(500)
    assert read_text() == target.content
    assert window.isVisible()
    assert not hidden


def test_hotkey_recall_preserves_user_window_position(qapp, window):
    window.show_launcher()
    qapp.processEvents()
    window.resize(410, 510)
    window.move(110, 70)
    qapp.processEvents()
    before = window.geometry()
    window._request_hide()
    window.hide()
    window.show_launcher()
    qapp.processEvents()
    assert window.geometry() == before
    assert window._settings.window_width == 410
    assert not window.windowFlags() & Qt.FramelessWindowHint
    assert window.windowFlags() & Qt.WindowMaximizeButtonHint


@pytest.mark.parametrize("area", [QRect(0, 0, 1920, 1040), QRect(-1920, 40, 1920, 1000),
                                  QRect(2560, 0, 1366, 728), QRect(0, 0, 800, 560)])
def test_right_panel_fits_desktop_work_area(area):
    panel = right_panel_rect(area)
    assert area.contains(panel)
    assert panel.right() == area.right()
    assert panel.height() == area.height()
    assert 340 <= panel.width() <= 600


def test_enter_on_variable_prompt_substitutes(
    qapp: QApplication, window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """有变量的 Prompt：弹窗填写后复制的是替换结果，且文件本身不变。"""
    window.show_launcher()
    qapp.processEvents()

    target = next(p for p in window._prompts if p.name == "项目诊断")
    window._select_prompt(target)
    qapp.processEvents()
    before = target.path.read_bytes()

    from src.ui import main_window as main_window_module

    class FakeVariableDialog:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def exec(self) -> int:
            from PySide6.QtWidgets import QDialog

            return QDialog.Accepted

        def values(self) -> dict[str, str]:
            return {"PROJECT_PATH": r"C:\demo", "TASK": "修复登录失败"}

    monkeypatch.setattr(main_window_module, "VariableDialog", FakeVariableDialog)

    window.copy_selected()
    qapp.processEvents()

    copied = read_text()
    assert r"C:\demo" in copied
    assert "修复登录失败" in copied
    assert "{{" not in copied
    assert target.path.read_bytes() == before


def test_variable_dialog_cancel_does_not_copy(
    qapp: QApplication, window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    window.show_launcher()
    qapp.processEvents()

    target = next(p for p in window._prompts if p.name == "项目诊断")
    window._select_prompt(target)
    qapp.processEvents()

    copy_text("哨兵内容")
    from src.ui import main_window as main_window_module

    class CancelDialog:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def exec(self) -> int:
            from PySide6.QtWidgets import QDialog

            return QDialog.Rejected

    monkeypatch.setattr(main_window_module, "VariableDialog", CancelDialog)

    window.copy_selected()
    qapp.processEvents()
    assert read_text() == "哨兵内容"


# ----------------------------------------------------------------------
# 11. Esc 隐藏
# ----------------------------------------------------------------------
def test_escape_hides_window(qapp: QApplication, window: MainWindow) -> None:
    window.show_launcher()
    qapp.processEvents()
    assert window.isVisible() is True

    hidden: list[bool] = []
    window.request_hide.connect(lambda: hidden.append(True))

    window._request_hide()
    qapp.processEvents()

    assert hidden == [True]


def test_escape_shortcut_is_bound(qapp: QApplication, window: MainWindow) -> None:
    """Esc 快捷键已绑定到隐藏动作。"""
    from PySide6.QtGui import QShortcut

    sequences = {
        shortcut.key().toString()
        for shortcut in window.findChildren(QShortcut)
    }
    assert "Esc" in sequences
    assert "Ctrl+N" in sequences
    assert "Ctrl+D" in sequences


# ----------------------------------------------------------------------
# 搜索 / 分类过滤
# ----------------------------------------------------------------------
def test_search_filters_list(qapp: QApplication, window: MainWindow) -> None:
    window.show_launcher()
    qapp.processEvents()
    assert len(window._visible) == 3

    window._search.setText("根因")
    qapp.processEvents()
    assert [p.name for p in window._visible] == ["Bug诊断"]
    assert window.current_prompt() is not None

    window._search.setText("")
    qapp.processEvents()
    assert len(window._visible) == 3


def test_category_switch_filters_list(qapp: QApplication, window: MainWindow) -> None:
    window.show_launcher()
    qapp.processEvents()

    window._selected_category = "Coding"
    window._refresh_sidebar()
    window._refresh_list(reset=True)
    qapp.processEvents()
    assert {p.name for p in window._visible} == {"Bug诊断", "项目诊断"}

    window._selected_category = ALL_KEY
    window._refresh_sidebar()
    window._refresh_list(reset=True)
    qapp.processEvents()
    assert len(window._visible) == 3


# ----------------------------------------------------------------------
# 4/5. 收藏与最近使用在界面中生效
# ----------------------------------------------------------------------
def test_favorite_persists_to_config(qapp: QApplication, window: MainWindow, tmp_path: Path) -> None:
    window.show_launcher()
    qapp.processEvents()

    prompt = window.current_prompt()
    assert prompt is not None

    window.toggle_favorite()
    qapp.processEvents()

    assert window._settings.is_favorite(prompt.id) is True

    window._selected_category = "favorites"
    window._refresh_sidebar()
    window._refresh_list(reset=True)
    qapp.processEvents()
    assert [p.id for p in window._visible] == [prompt.id]


def test_recent_updates_after_copy(qapp: QApplication, window: MainWindow) -> None:
    window.show_launcher()
    qapp.processEvents()

    # 只挑无变量的 Prompt，避免弹出真实的变量填写对话框阻塞测试。
    prompts = [p for p in window._visible if not p.has_variables]
    assert len(prompts) >= 2

    window.copy_prompt(prompts[0])
    qapp.processEvents()
    window.copy_prompt(prompts[1])
    qapp.processEvents()

    assert window._settings.recent[0] == prompts[1].id
    assert window._settings.recent[1] == prompts[0].id

    window._selected_category = RECENT_KEY
    window._refresh_list(reset=True)
    qapp.processEvents()
    assert [p.id for p in window._visible] == [prompts[1].id, prompts[0].id]


# ----------------------------------------------------------------------
# 7. 新建 / 重命名 / 删除（经由界面）
# ----------------------------------------------------------------------
def test_new_prompt_appears_in_list(qapp: QApplication, window: MainWindow, monkeypatch) -> None:
    from PySide6.QtWidgets import QDialog

    from src.ui import main_window as main_window_module

    class FakeEditor:
        @classmethod
        def for_new(cls, *args, **kwargs) -> "FakeEditor":
            return cls()

        def __init__(self, *args, **kwargs) -> None:
            pass

        def exec(self) -> int:
            return QDialog.Accepted

        def cleaned_name(self) -> str:
            return "新 Prompt"

        def cleaned_category(self) -> str:
            return "新增分类"

        def values(self) -> tuple[str, str, str]:
            return "新 Prompt", "新增分类", "这是新写入的内容。\n"

    monkeypatch.setattr(main_window_module, "PromptEditorDialog", FakeEditor)

    window.new_prompt()
    qapp.processEvents()

    names = {p.name for p in window._prompts}
    assert "新 Prompt" in names
    created = next(p for p in window._prompts if p.name == "新 Prompt")
    assert created.path.exists()
    assert created.path.read_text(encoding="utf-8") == "这是新写入的内容。\n"


def test_rename_and_delete_via_window(qapp: QApplication, window: MainWindow) -> None:
    window.show_launcher()
    qapp.processEvents()

    prompt = next(p for p in window._prompts if p.name == "Bug诊断")
    old_id = prompt.id

    window._apply_update(prompt, name="Bug诊断v2")
    qapp.processEvents()

    assert old_id not in window._prompts_by_id
    assert "Coding/Bug诊断v2.md" in window._prompts_by_id
    assert not prompt.path.exists()

    updated = window._prompts_by_id["Coding/Bug诊断v2.md"]
    window._store.delete(updated)
    window._settings.remove_id(updated.id)
    window.reload_prompts()
    qapp.processEvents()

    assert "Coding/Bug诊断v2.md" not in window._prompts_by_id


# ----------------------------------------------------------------------
# 10 / 13. 全局快捷键
# ----------------------------------------------------------------------
@pytest.mark.skipif(not IS_WINDOWS, reason="全局快捷键仅支持 Windows")
def test_parse_hotkey_variants() -> None:
    spec = parse_hotkey("Alt+Space")
    assert spec.modifiers != 0
    assert spec.text == "Alt+Space"

    assert parse_hotkey("Ctrl+Shift+P").text == "Ctrl+Shift+P"
    assert parse_hotkey("F9").has_modifier is False


@pytest.mark.skipif(not IS_WINDOWS, reason="全局快捷键仅支持 Windows")
def test_parse_hotkey_rejects_garbage() -> None:
    from src.hotkey import HotkeyError

    for bad in ("", "Alt+", "Hyper+X", "Alt+不存在"):
        with pytest.raises(HotkeyError):
            parse_hotkey(bad)


@pytest.mark.skipif(not IS_WINDOWS, reason="全局快捷键仅支持 Windows")
def test_global_hotkey_registers_and_fires(qapp: QApplication) -> None:
    """真实注册 Alt+Space，真实模拟按键，验证回调被触发。"""
    listener = HotkeyListener("Alt+Space")
    fired: list[bool] = []
    failures: list[str] = []
    listener.activated.connect(lambda: fired.append(True))
    listener.registration_failed.connect(lambda reason: failures.append(reason))

    listener.start()
    assert wait_until(listener.is_registered, 4000), f"热键注册失败：{failures}"

    try:
        press_alt_space()
        assert wait_until(lambda: bool(fired), 4000), "按下 Alt+Space 后没有收到热键事件"
    finally:
        listener.stop()

    assert listener.is_registered() is False


@pytest.mark.skipif(not IS_WINDOWS, reason="全局快捷键仅支持 Windows")
def test_probe_hotkey_reports_unavailable_while_held(qapp: QApplication) -> None:
    """已被占用的热键会被探测出来（用于设置界面的提示）。"""
    listener = HotkeyListener("Ctrl+Alt+F9")
    listener.start()
    assert wait_until(listener.is_registered, 4000)

    try:
        available, reason = probe_hotkey("Ctrl+Alt+F9")
        assert available is False
        assert reason
    finally:
        listener.stop()


@pytest.mark.skipif(not IS_WINDOWS, reason="全局快捷键仅支持 Windows")
def test_hotkey_recalls_window_after_hiding(qapp: QApplication, tmp_path: Path) -> None:
    """隐藏后再次按热键仍能呼出窗口（完整链路：热键 -> 显示）。"""
    root = tmp_path / "prompts"
    atomic_write_text(root / "Coding" / "Bug诊断.md", "内容\n")

    window = MainWindow(PromptStore(root), Settings())
    hidden_events: list[bool] = []
    window.request_hide.connect(lambda: hidden_events.append(True))

    listener = HotkeyListener("Alt+Space")
    listener.activated.connect(window.show_launcher)
    listener.start()
    assert wait_until(listener.is_registered, 4000)

    try:
        # 第一次呼出
        press_alt_space()
        assert wait_until(window.isVisible, 4000), "第一次按热键没有呼出窗口"

        # 隐藏（等价于 Esc / 点击 ✕）
        window._request_hide()
        window.hide()
        qapp.processEvents()
        assert window.isVisible() is False
        assert hidden_events == [True]

        # 第二次呼出
        press_alt_space()
        assert wait_until(window.isVisible, 4000), "隐藏后再次按热键没有呼出窗口"
    finally:
        listener.stop()
        window.hide()
        window.deleteLater()
        qapp.processEvents()


# ----------------------------------------------------------------------
# 界面字号
# ----------------------------------------------------------------------
@pytest.fixture(autouse=True)
def restore_font_size(qapp: QApplication):
    """字号是应用级状态，用例结束后复位，避免影响其他用例。"""
    yield
    apply_font_size(qapp, BASE_FONT_SIZE)


def _font_of_size(size: int) -> QFont:
    font = QFont()
    font.setPixelSize(size)
    return font


@pytest.mark.parametrize("size", [10, 14, 18, 24])
def test_font_size_applies_to_whole_ui(qapp: QApplication, window: MainWindow, size: int) -> None:
    """字号变化立即作用于搜索框、列表、预览、按钮、标题栏与状态栏。"""
    window.show_launcher()
    window.resize(900, 700)
    qapp.processEvents()

    before_row = window._list.sizeHintForRow(0)
    window.set_font_size(size)
    qapp.processEvents()

    assert current_font_size() == size
    assert window._settings.font_size == size
    assert f"font-size: {size}px" in qapp.styleSheet()

    # 样式表的字体规则要真正落到控件上，而不只是写在字符串里
    for widget in (
        window._search,
        window._copy_button,
        window._list,
        window._preview_title,
    ):
        assert widget.font().pixelSize() == size, f"{widget.objectName()} 没跟上 {size}px"

    # 预览正文与状态栏按设计比基础字号小一号，但仍随基础字号等比放大
    for widget in (window._preview, window._status_label):
        assert widget.font().pixelSize() == scaled(12), f"{widget.objectName()} 没有等比缩放"

    # 列表行必须放得下「名称 + 副标题」两行字
    title_metrics = QFontMetrics(_font_of_size(size))
    subtitle_metrics = QFontMetrics(_font_of_size(max(8, size - scaled(2))))
    row_height = window._list.sizeHintForRow(0)
    assert row_height >= title_metrics.height() + subtitle_metrics.height()
    if size > BASE_FONT_SIZE:
        assert row_height > before_row

    # 侧边栏、标题栏、状态栏、按钮都不能裁字
    assert window._sidebar.sizeHintForRow(0) >= title_metrics.height()
    assert window._title_bar.minimumHeight() == scaled(TITLE_BAR_HEIGHT)
    assert window._title_bar.height() >= scaled(TITLE_BAR_HEIGHT)
    assert window._status_bar.height() >= QFontMetrics(window._status_label.font()).height()
    assert window._copy_button.height() >= window._copy_button.fontMetrics().height()
    assert window._search.height() >= window._search.fontMetrics().height()


def test_default_font_size_is_14(qapp: QApplication, window: MainWindow) -> None:
    """没有 font_size 的配置启动后就是 14px。"""
    assert Settings().font_size == DEFAULT_FONT_SIZE == 14
    assert window._settings.font_size == 14
    assert current_font_size() == 14


def test_font_size_survives_restart(
    qapp: QApplication, window: MainWindow, tmp_path: Path
) -> None:
    """改成 18px 后写入 config.json，重启（重新读配置）仍然是 18px。"""
    window.show_launcher()
    qapp.processEvents()

    window.set_font_size(18)
    window._settings.save()

    config = tmp_path / "config.json"
    assert json.loads(config.read_text(encoding="utf-8"))["font_size"] == 18

    reloaded = Settings.load(config)
    assert reloaded.font_size == 18
    apply_font_size(qapp, reloaded.font_size)
    assert current_font_size() == 18


def test_legacy_config_keeps_working_in_gui(
    qapp: QApplication, tmp_path: Path
) -> None:
    """旧版 config（无 font_size）能被界面正常读取并使用默认字号。"""
    root = tmp_path / "prompts"
    atomic_write_text(root / "Coding" / "Bug诊断.md", "内容\n")
    config = tmp_path / "legacy.json"
    config.write_text(
        json.dumps({"hotkey": "Ctrl+Alt+Q", "window_width": 700, "schema_version": 1}),
        encoding="utf-8",
    )

    settings = Settings.load(config)
    win = MainWindow(PromptStore(root), settings)
    try:
        win.show_launcher()
        qapp.processEvents()
        assert settings.font_size == DEFAULT_FONT_SIZE
        assert current_font_size() == DEFAULT_FONT_SIZE
        assert win._search.font().pixelSize() == DEFAULT_FONT_SIZE
        assert len(win._visible) == 1
    finally:
        win.hide()
        win.deleteLater()
        qapp.processEvents()


def test_settings_dialog_exposes_font_size_controls(qapp: QApplication) -> None:
    dialog = SettingsDialog("Alt+Space", True, True, None, font_size=18)
    try:
        spin = dialog._font_spin
        assert dialog.font_size() == 18
        assert (spin.minimum(), spin.maximum()) == (MIN_FONT_SIZE, MAX_FONT_SIZE) == (10, 24)
        assert spin.singleStep() == 1
        assert spin.suffix() == " px"
        assert spin.text().strip() == "18 px"

        dialog._font_reset.click()
        assert dialog.font_size() == DEFAULT_FONT_SIZE == 14
    finally:
        dialog.deleteLater()


def test_settings_dialog_previews_font_size_and_rolls_back(
    qapp: QApplication, window: MainWindow
) -> None:
    """改 SpinBox 立即预览；取消对话框则回到原来的字号。"""
    window.show_launcher()
    qapp.processEvents()
    window._settings.font_size = 14
    window.set_font_size(14)

    dialog = SettingsDialog(window._settings.hotkey, True, True, window, font_size=14)
    try:
        dialog._font_spin.setValue(20)
        qapp.processEvents()
        assert current_font_size() == 20
        assert window._settings.font_size == 20
        assert window._list.sizeHintForRow(0) > 0

        dialog.reject()
        qapp.processEvents()
        assert current_font_size() == 14
        assert window._settings.font_size == 14
    finally:
        dialog.deleteLater()


def test_new_dialogs_use_current_font_size(qapp: QApplication, window: MainWindow) -> None:
    """新建 / 编辑 Prompt 窗口与变量填写窗口也跟随字号。"""
    window.set_font_size(20)
    qapp.processEvents()

    editor = PromptEditorDialog.for_new(window._store.categories(), "Coding", window)
    variable = VariableDialog(["PROJECT_PATH"], "示例 Prompt", window)
    try:
        editor.show()
        variable.show()
        qapp.processEvents()

        assert editor._name_edit.font().pixelSize() == 20
        assert editor._content_edit.font().pixelSize() == scaled(12)
        assert variable._editors["PROJECT_PATH"].font().pixelSize() == 20
        assert editor.height() >= editor.minimumSizeHint().height()
    finally:
        editor.close()
        editor.deleteLater()
        variable.close()
        variable.deleteLater()
        qapp.processEvents()


def test_narrow_layout_still_usable_at_max_font(qapp: QApplication, window: MainWindow) -> None:
    """24px 下窄窗口仍然走紧凑布局，过滤、预览、复制按钮都可用。"""
    window.show_launcher()
    qapp.processEvents()
    window.set_font_size(MAX_FONT_SIZE)
    window.resize(460, 800)
    qapp.processEvents()

    assert window._browser.compact
    assert window._browser.categories.isVisible()
    assert not window._sidebar.isVisible()
    assert window._splitter.orientation() == Qt.Vertical
    assert (
        window._browser.categories.height()
        >= QFontMetrics(window._browser.categories.font()).height()
    )

    combo = window._browser.categories
    combo.setCurrentIndex(combo.findData("Coding"))
    qapp.processEvents()
    assert all(p.category == "Coding" for p in window._visible)

    target = window._visible[0]
    window._list.setCurrentRow(0)
    qapp.processEvents()
    assert window._preview.toPlainText() == target.content
    assert window._copy_button.isVisible()
    assert window._copy_button.height() >= window._copy_button.fontMetrics().height()

    # 搜索与复制在最大字号下依然正常
    window._search.setText("Bug")
    qapp.processEvents()
    assert [p.name for p in window._visible] == ["Bug诊断"]
    window._search.clear()
    qapp.processEvents()

    target = next(p for p in window._visible if not p.has_variables)
    window.copy_prompt(target)
    qapp.processEvents()
    assert read_text() == target.content


def test_font_size_does_not_break_context_menu(qapp: QApplication, window: MainWindow) -> None:
    """右键菜单是应用级样式表的一部分，字号变化后仍能正常构建。"""
    window.show_launcher()
    qapp.processEvents()
    window.set_font_size(24)
    qapp.processEvents()

    menu = window._build_list_menu(window.current_prompt())
    try:
        assert menu.actions()
        assert menu.font().pixelSize() == MAX_FONT_SIZE
    finally:
        menu.deleteLater()

