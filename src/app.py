"""AgentDeck 应用组装：托盘、全局快捷键、生命周期。

窗口关闭只隐藏，真正退出走托盘菜单，因此 ``setQuitOnLastWindowClosed(False)``。
"""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Sequence

from PySide6.QtCore import QLibraryInfo, Qt, QTranslator
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .hotkey import IS_WINDOWS, HotkeyListener
from .paths import PROMPTS_DIR
from .prompt_store import PromptStore
from .seeds import ensure_sample_prompts
from .settings import Settings
from .ui.main_window import MainWindow
from .ui.theme import apply_theme

ERROR_ALREADY_EXISTS = 183
_SINGLE_INSTANCE_NAME = "Local\\AgentDeck.SingleInstance"

#: 持有互斥体句柄，进程存活期间不释放。
_instance_handle: int | None = None


def acquire_single_instance() -> bool:
    """确保只运行一个实例。返回 False 表示已有实例在运行。"""
    global _instance_handle
    if not IS_WINDOWS:
        return True

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        handle = kernel32.CreateMutexW(None, True, _SINGLE_INSTANCE_NAME)
    except OSError:
        return True

    if not handle:
        return True
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return False
    _instance_handle = handle
    return True


def _warn_already_running() -> None:
    message = "AgentDeck 已经在运行中。\n请使用系统托盘图标或全局快捷键呼出窗口。"
    if IS_WINDOWS:
        try:
            ctypes.WinDLL("user32").MessageBoxW(None, message, "AgentDeck", 0x40)
            return
        except OSError:
            pass
    print(message)


def build_app_icon() -> QIcon:
    """程序化绘制图标，避免附带二进制资源。"""
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#2f6fbf"))
    painter.drawRoundedRect(2, 2, size - 4, size - 4, 14, 14)

    pen = QPen(QColor("#ffffff"))
    pen.setWidth(6)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.drawLine(20, 46, 32, 18)
    painter.drawLine(32, 18, 44, 46)
    painter.drawLine(24, 36, 40, 36)
    painter.end()

    return QIcon(pixmap)


def install_translator(app: QApplication) -> QTranslator | None:
    """加载 Qt 自带的中文翻译，让标准按钮也显示中文。"""
    translator = QTranslator(app)
    translations_path = QLibraryInfo.path(QLibraryInfo.TranslationsPath)
    if translator.load("qtbase_zh_CN", translations_path):
        app.installTranslator(translator)
        return translator
    return None


class AgentDeckApp:
    """把配置、仓库、窗口、托盘和全局快捷键串起来。"""

    def __init__(
        self,
        argv: Sequence[str] | None = None,
        app: QApplication | None = None,
    ) -> None:
        # 允许注入已有的 QApplication，便于测试复用同一个实例。
        self._app = app if app is not None else QApplication(list(argv or sys.argv))
        self._app.setApplicationName("AgentDeck")
        self._app.setApplicationDisplayName("AgentDeck")
        self._app.setQuitOnLastWindowClosed(False)

        # 配置先于主题读取：界面字号要在构建任何窗口之前生效。
        self._settings = Settings.load()
        apply_theme(self._app, self._settings.font_size)
        self._translator = install_translator(self._app)

        self._icon = build_app_icon()
        self._app.setWindowIcon(self._icon)

        self._store = PromptStore(PROMPTS_DIR)
        ensure_sample_prompts(self._store)

        self._window = MainWindow(self._store, self._settings)
        self._window.setWindowIcon(self._icon)
        self._window.request_hide.connect(self._hide_window)
        self._window.settings_changed.connect(self._on_settings_changed)

        self._tray: QSystemTrayIcon | None = None
        self._tray_menu: QMenu | None = None
        self._hotkey: HotkeyListener | None = None

        self._build_tray()
        self._register_hotkey(self._settings.hotkey)
        self._app.aboutToQuit.connect(self._shutdown)

    # ------------------------------------------------------------------
    @property
    def window(self) -> MainWindow:
        """主窗口（供测试与脚本访问）。"""
        return self._window

    def run(self) -> int:
        """显示窗口并进入事件循环。"""
        self._window.show_launcher()
        return self._app.exec()

    # ------------------------------------------------------------------
    # 托盘
    # ------------------------------------------------------------------
    def _build_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            print("警告：当前系统不支持托盘图标，退出请使用任务管理器结束进程。")
            return

        tray = QSystemTrayIcon(self._icon)
        tray.setToolTip("AgentDeck —— Prompt 启动器")

        menu = QMenu()
        menu.addAction("显示 AgentDeck", self._window.show_launcher)
        menu.addAction("重新加载 Prompts", self._reload_prompts)
        menu.addAction("设置…", self._window.open_settings)
        menu.addSeparator()
        menu.addAction("退出", self.quit)

        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()

        self._tray = tray
        self._tray_menu = menu

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self._toggle_window()

    def _reload_prompts(self) -> None:
        self._window.reload_prompts()
        self._window.show_status_message("已重新扫描 prompts/")

    # ------------------------------------------------------------------
    # 全局快捷键
    # ------------------------------------------------------------------
    def _register_hotkey(self, hotkey: str) -> None:
        self._stop_hotkey()

        listener = HotkeyListener(hotkey)
        listener.activated.connect(self._toggle_window)
        listener.registration_failed.connect(self._on_hotkey_failed)
        listener.start()

        self._hotkey = listener

    def _stop_hotkey(self) -> None:
        if self._hotkey is None:
            return
        self._hotkey.stop()
        self._hotkey = None

    def _on_hotkey_failed(self, reason: str) -> None:
        message = f"全局快捷键「{self._settings.hotkey}」注册失败：{reason}。可在设置中更换。"
        self._window.show_status_message(message, error=True)
        if self._tray is not None:
            self._tray.showMessage("AgentDeck", message, QSystemTrayIcon.Warning, 8000)

    def _on_settings_changed(self) -> None:
        if (
            self._hotkey is not None
            and self._hotkey.hotkey == self._settings.hotkey
            and self._hotkey.is_registered()
        ):
            return
        self._register_hotkey(self._settings.hotkey)

    # ------------------------------------------------------------------
    # 窗口显隐
    # ------------------------------------------------------------------
    def _toggle_window(self) -> None:
        """热键行为：窗口在前台则隐藏，否则呼出。"""
        if self._window.isVisible() and self._window.isActiveWindow():
            self._hide_window()
        else:
            self._window.show_launcher()

    def _hide_window(self) -> None:
        self._window.hide()

    # ------------------------------------------------------------------
    # 退出
    # ------------------------------------------------------------------
    def quit(self) -> None:
        """真正退出（仅托盘菜单调用）。"""
        self._window.save_window_size()
        try:
            self._settings.save()
        except OSError:
            pass
        self._app.quit()

    def _shutdown(self) -> None:
        self._stop_hotkey()
        if self._tray is not None:
            self._tray.hide()


def run_self_check() -> int:
    """`--check`：不进入界面，打印/落盘一份环境自检结果。

    打包成 --windowed 的 exe 后没有控制台，所以结果同时写入
    ``data/selfcheck.txt``，方便确认打包产物是否可用。
    """
    app = QApplication.instance() or QApplication([])

    from .fsutil import atomic_write_text
    from .paths import APP_ROOT, CONFIG_FILE, DATA_DIR, PROMPTS_DIR
    from .hotkey import probe_hotkey

    settings = Settings.load()
    apply_theme(app, settings.font_size)

    store = PromptStore(PROMPTS_DIR)
    prompts = store.scan()
    hotkey_ok, hotkey_reason = probe_hotkey(settings.hotkey)

    lines = [
        "AgentDeck 自检",
        f"应用根目录      : {APP_ROOT}",
        f"打包运行        : {getattr(sys, 'frozen', False)}",
        f"prompts 目录    : {PROMPTS_DIR}（存在：{PROMPTS_DIR.is_dir()}）",
        f"扫描到 Prompt   : {len(prompts)} 个",
        f"分类            : {', '.join(sorted({p.category for p in prompts}))}",
        f"读取失败文件    : {len(store.errors)}",
        f"配置文件        : {CONFIG_FILE}",
        f"当前快捷键      : {settings.hotkey}",
        f"界面字号        : {settings.font_size} px",
        f"快捷键可用      : {hotkey_ok}{'' if hotkey_ok else f'（{hotkey_reason}）'}",
        f"托盘可用        : {QSystemTrayIcon.isSystemTrayAvailable()}",
        f"Qt 平台         : {app.platformName()}",
        f"Python          : {sys.version.split()[0]}",
    ]
    text = "\n".join(lines) + "\n"

    try:
        print(text)
    except Exception:  # windowed 模式下没有 stdout
        pass

    try:
        atomic_write_text(DATA_DIR / "selfcheck.txt", text, newline="\n")
    except OSError:
        pass

    return 0 if not store.errors else 2


def main(argv: Sequence[str] | None = None) -> int:
    """程序入口。"""
    arguments = list(argv if argv is not None else sys.argv)

    if "--check" in arguments:
        return run_self_check()

    if not acquire_single_instance():
        _warn_already_running()
        return 0

    deck = AgentDeckApp(arguments)
    return deck.run()


__all__ = ["AgentDeckApp", "acquire_single_instance", "build_app_icon", "main"]
