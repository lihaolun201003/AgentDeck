"""人工验证脚本：真实启动 AgentDeck 并抓取各个界面的截图。

用法::

    .venv\\Scripts\\python.exe tests\\render_screenshots.py

截图输出到 docs/screenshots/，同时会在控制台打印"窗口是否真的取得了前台焦点"
等运行时状态，便于确认界面在真实 Windows 平台下的表现。
不是 pytest 用例（文件名不以 test_ 开头），需要时手动运行。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.app import AgentDeckApp  # noqa: E402
from src.ui.prompt_editor import PromptEditorDialog  # noqa: E402
from src.ui.settings_dialog import SettingsDialog  # noqa: E402
from src.ui.variable_dialog import VariableDialog  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
findings: list[str] = []


def save(widget, name: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{name}.png"
    ok = widget.grab().save(str(path))
    findings.append(f"{'OK  ' if ok else 'FAIL'} 截图 {name} -> {path}")


def main() -> int:
    qapp = QApplication(sys.argv)
    deck = AgentDeckApp(app=qapp)
    window = deck.window

    window.show_launcher()

    def step_main() -> None:
        save(window, "01-main")
        findings.append(f"窗口可见：{window.isVisible()}")
        findings.append(f"窗口取得前台焦点：{window.isActiveWindow()}")
        findings.append(f"搜索框有焦点：{window._search.hasFocus()}")
        findings.append(f"扫描到 Prompt：{len(window._prompts)} 个")
        findings.append(f"侧边栏项：{[window._sidebar.item(i).text() for i in range(window._sidebar.count())]}")

        window._search.setText("根因")
        QTimer.singleShot(250, step_search)

    def step_search() -> None:
        save(window, "02-search")
        findings.append(f"搜索『根因』命中：{[p.name for p in window._visible]}")
        window._search.clear()
        QTimer.singleShot(250, step_variable)

    def step_variable() -> None:
        prompt = next((p for p in window._prompts if p.has_variables), None)
        if prompt is None:
            findings.append("没有带变量的示例 Prompt，跳过变量对话框截图")
            return step_editor()
        dialog = VariableDialog(list(prompt.variables), prompt.display_name, window)
        dialog.show()

        def grab() -> None:
            save(dialog, "03-variable-dialog")
            dialog.close()
            QTimer.singleShot(200, step_editor)

        QTimer.singleShot(300, grab)

    def step_editor() -> None:
        dialog = PromptEditorDialog.for_new(window._store.categories(), "Coding", window)
        dialog.show()

        def grab() -> None:
            dialog._name_edit.setText("示例 Prompt")
            dialog._category_combo.setCurrentText("Coding")
            dialog._content_edit.setPlainText("请检查以下项目：\n\n{{PROJECT_PATH}}\n\n找出真实根因。\n")
            QTimer.singleShot(150, grab2)

        def grab2() -> None:
            save(dialog, "04-prompt-editor")
            dialog.close()
            QTimer.singleShot(200, step_settings)

        QTimer.singleShot(300, grab)

    def step_settings() -> None:
        dialog = SettingsDialog(
            window._settings.hotkey,
            window._settings.always_on_top,
            window._settings.hide_after_copy,
            window,
            font_size=window._settings.font_size,
        )
        dialog.show()

        def grab() -> None:
            save(dialog, "05-settings")
            dialog.close()
            QTimer.singleShot(200, step_menu)

        QTimer.singleShot(300, grab)

    def step_menu() -> None:
        from PySide6.QtCore import QPoint

        window.show_launcher()
        prompt = window.current_prompt()
        menu = window._build_list_menu(prompt)
        menu.popup(window._list.viewport().mapToGlobal(QPoint(60, 20)))
        QTimer.singleShot(400, lambda: grab_menu(menu))

    def grab_menu(menu) -> None:
        save(menu, "06-context-menu")
        menu.close()
        QTimer.singleShot(200, finish)

    def finish() -> None:
        findings.append("—— 运行状态 ——")
        findings.append(f"托盘可用：{deck._tray is not None}")
        findings.append(f"全局快捷键已注册：{deck._hotkey is not None and deck._hotkey.is_registered()}")
        deck._window.save_window_size()
        deck._shutdown()
        qapp.quit()

    QTimer.singleShot(900, step_main)
    code = qapp.exec()

    print("\n".join(findings))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
