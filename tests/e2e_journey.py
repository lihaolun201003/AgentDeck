"""端到端验证：完整走一遍真实用户流程。

流程：启动 → Alt+Space 呼出 → 键盘输入搜索 → ↑↓ 选择 → Enter 复制 →
窗口自动隐藏 → 再按 Alt+Space 重新呼出。

使用真实窗口、真实系统托盘、真实 RegisterHotKey 与真实按键模拟（keybd_event）。
运行时窗口会短暂出现在屏幕上。手动运行：

    .venv\\Scripts\\python.exe tests\\e2e_journey.py
"""

from __future__ import annotations

import ctypes
import sys
import time
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.app import AgentDeckApp  # noqa: E402
from src.clipboard import read_text  # noqa: E402

VK_MENU = 0x12
VK_SPACE = 0x20
KEYEVENTF_KEYUP = 0x0002

steps: list[tuple[bool, str]] = []


def check(ok: bool, description: str) -> None:
    steps.append((ok, description))
    print(f"{'通过' if ok else '失败'}  {description}")


def wait_until(predicate: Callable[[], bool], timeout_ms: int = 4000) -> bool:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    QApplication.processEvents()
    return predicate()


def press_alt_space() -> None:
    user32 = ctypes.WinDLL("user32")
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_SPACE, 0, 0, 0)
    user32.keybd_event(VK_SPACE, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)


def main() -> int:
    qapp = QApplication(sys.argv)
    deck = AgentDeckApp(app=qapp)
    window = deck.window

    # 1. 启动即显示
    window.show_launcher()
    QApplication.processEvents()
    check(wait_until(window.isVisible), "启动后窗口可见")
    check(
        wait_until(lambda: deck._hotkey is not None and deck._hotkey.is_registered()),
        "全局快捷键 Alt+Space 注册成功",
    )

    # 2. Alt+Space 隐藏
    press_alt_space()
    check(wait_until(lambda: not window.isVisible()), "窗口在前台时按 Alt+Space 会隐藏")

    # 3. Alt+Space 重新呼出
    press_alt_space()
    check(wait_until(window.isVisible), "隐藏后按 Alt+Space 重新呼出")
    check(wait_until(window.isActiveWindow), "呼出后成为前台窗口")
    check(window._search.hasFocus(), "呼出后搜索框自动获得焦点")
    check(window._search.text() == "", "呼出后搜索框内容被清空")

    # 4. 真实键盘输入搜索
    QTest.keyClicks(window._search, "bug")
    QApplication.processEvents()
    names = [prompt.name for prompt in window._visible]
    check(window._search.text() == "bug", "键盘输入进入搜索框")
    check(names == ["Bug诊断"], f"搜索 'bug' 命中 {names}")

    # 5. ↑↓ 选择
    window._search.setText("")
    QApplication.processEvents()
    total = len(window._visible)
    QTest.keyClick(window._search, Qt.Key_Down)
    QApplication.processEvents()
    second = window.current_prompt()
    QTest.keyClick(window._search, Qt.Key_Up)
    QApplication.processEvents()
    first = window.current_prompt()
    check(total >= 2 and second is not None and first is not None and second.id != first.id,
          "↑↓ 可以在结果间切换选择")

    # 6. Enter 复制（选中的是无变量的 Prompt）
    assert first is not None
    check(first.has_variables is False, f"选中的「{first.name}」不含变量")
    QTest.keyClick(window._search, Qt.Key_Return)
    QApplication.processEvents()
    check(read_text() == first.content, "Enter 后剪贴板内容与 Prompt 正文逐字一致")
    check(window._settings.recent[:1] == [first.id], "剪贴板复制后写入 Recent")

    # 7. 复制后自动隐藏
    check(wait_until(lambda: not window.isVisible(), 3000), "复制后窗口自动隐藏")

    # 8. 隐藏后仍在后台，可再次呼出
    check(deck._hotkey is not None and deck._hotkey.is_registered(), "隐藏后全局快捷键仍然有效")
    press_alt_space()
    check(wait_until(window.isVisible), "隐藏后再次按 Alt+Space 仍能呼出窗口")

    # 9. 变量替换的真实替换结果（不阻塞在对话框上，直接验证替换函数链路）
    variable_prompt = next((p for p in window._prompts if p.has_variables), None)
    if variable_prompt is not None:
        from src.variable_parser import substitute

        filled = substitute(variable_prompt.content, dict.fromkeys(variable_prompt.variables, "VALUE"))
        check("{{" not in filled and "VALUE" in filled, f"变量替换链路可用（{variable_prompt.name}）")

    # 收尾
    deck._shutdown()
    window.hide()
    qapp.processEvents()

    failed = [description for ok, description in steps if not ok]
    print("\n" + "=" * 60)
    print(f"共 {len(steps)} 项，通过 {len(steps) - len(failed)} 项，失败 {len(failed)} 项")
    for description in failed:
        print(f"  失败：{description}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
