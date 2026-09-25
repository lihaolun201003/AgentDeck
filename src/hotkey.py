"""Windows 全局快捷键（ctypes + RegisterHotKey，无需管理员权限）。

RegisterHotKey 注册的热键只对"注册它的线程"投递 WM_HOTKEY 消息，因此这里
用一个独立线程创建消息队列、注册热键并跑 GetMessage 循环，再把按键事件通过
Qt 信号抛回主线程。

非 Windows 平台上模块仍可导入，但注册会失败并给出中文提示。
"""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from ctypes import wintypes

from PySide6.QtCore import QThread, Signal

IS_WINDOWS = sys.platform == "win32"

# --- Win32 常量 ------------------------------------------------------------
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

HOTKEY_ID = 0xA4D1

ERROR_HOTKEY_ALREADY_REGISTERED = 1409

_MODIFIER_NAMES: dict[str, int] = {
    "ALT": MOD_ALT,
    "CTRL": MOD_CONTROL,
    "CONTROL": MOD_CONTROL,
    "SHIFT": MOD_SHIFT,
    "WIN": MOD_WIN,
    "WINDOWS": MOD_WIN,
    "SUPER": MOD_WIN,
    "META": MOD_WIN,
}

_VK_NAMES: dict[str, int] = {
    "SPACE": 0x20,
    "TAB": 0x09,
    "ESC": 0x1B,
    "ESCAPE": 0x1B,
    "ENTER": 0x0D,
    "RETURN": 0x0D,
    "BACKSPACE": 0x08,
    "DELETE": 0x2E,
    "DEL": 0x2E,
    "INSERT": 0x2D,
    "INS": 0x2D,
    "HOME": 0x24,
    "END": 0x23,
    "PAGEUP": 0x21,
    "PGUP": 0x21,
    "PAGEDOWN": 0x22,
    "PGDN": 0x22,
    "UP": 0x26,
    "DOWN": 0x28,
    "LEFT": 0x25,
    "RIGHT": 0x27,
    "`": 0xC0,
    "-": 0xBD,
    "=": 0xBB,
    "[": 0xDB,
    "]": 0xDD,
    "\\": 0xDC,
    ";": 0xBA,
    "'": 0xDE,
    ",": 0xBC,
    ".": 0xBE,
    "/": 0xBF,
}


class HotkeyError(ValueError):
    """快捷键字符串非法。"""


@dataclass(frozen=True)
class HotkeySpec:
    """解析后的快捷键定义。"""

    modifiers: int
    virtual_key: int
    text: str

    @property
    def has_modifier(self) -> bool:
        return self.modifiers != 0


def parse_hotkey(text: str) -> HotkeySpec:
    """把 ``"Alt+Space"`` 这类字符串解析为 Win32 需要的键码。

    允许的写法：``Alt+Space``、``Ctrl+Shift+P``、``Win+` ``、``F9``（不带修饰键）。
    解析失败抛 :class:`HotkeyError`。
    """
    raw = (text or "").strip()
    if not raw:
        raise HotkeyError("快捷键不能为空")

    parts = [part.strip() for part in raw.split("+")]
    if any(not part for part in parts):
        raise HotkeyError(f"快捷键格式不正确：{raw}")

    *modifier_parts, key_part = parts
    modifiers = 0
    for part in modifier_parts:
        modifier = _MODIFIER_NAMES.get(part.upper())
        if modifier is None:
            raise HotkeyError(f"无法识别的修饰键：{part}")
        modifiers |= modifier

    virtual_key = _resolve_virtual_key(key_part)
    if virtual_key is None:
        raise HotkeyError(f"无法识别的按键：{key_part}")

    normalized_key = _normalize_key_name(key_part)
    modifier_names = _describe_modifiers(modifiers)
    display = "+".join([*modifier_names, normalized_key])

    return HotkeySpec(modifiers=modifiers, virtual_key=virtual_key, text=display)


def _resolve_virtual_key(name: str) -> int | None:
    upper = name.upper()
    if upper in _VK_NAMES:
        return _VK_NAMES[upper]
    if len(upper) == 1 and (upper.isascii() and upper.isalnum()):
        return ord(upper)
    if upper.startswith("F") and upper[1:].isdigit():
        index = int(upper[1:])
        if 1 <= index <= 24:
            return 0x70 + index - 1
    return None


def _normalize_key_name(name: str) -> str:
    upper = name.upper()
    aliases = {"ESC": "Esc", "ESCAPE": "Esc", "RETURN": "Enter", "PGUP": "PageUp", "PGDN": "PageDown"}
    if upper in aliases:
        return aliases[upper]
    if len(name) == 1:
        return name.upper()
    if upper in _VK_NAMES:
        return name.capitalize() if not upper.startswith("F") else upper
    return name


def _describe_modifiers(modifiers: int) -> list[str]:
    names: list[str] = []
    if modifiers & MOD_CONTROL:
        names.append("Ctrl")
    if modifiers & MOD_ALT:
        names.append("Alt")
    if modifiers & MOD_SHIFT:
        names.append("Shift")
    if modifiers & MOD_WIN:
        names.append("Win")
    return names


def describe_error(code: int) -> str:
    """把 RegisterHotKey 的错误码翻译成中文提示。"""
    if code == ERROR_HOTKEY_ALREADY_REGISTERED:
        return "该快捷键已被其他程序占用"
    if code == 0:
        return "系统未返回错误码（可能被系统保留键占用）"
    return f"系统错误码 {code}"


if IS_WINDOWS:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    _user32.RegisterHotKey.restype = wintypes.BOOL
    _user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.UnregisterHotKey.restype = wintypes.BOOL
    # GetMessageW 返回 BOOL，但错误时返回 -1；用 c_int 才能区分 0 与 -1。
    _user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    _user32.GetMessageW.restype = ctypes.c_int
    _user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.PostThreadMessageW.restype = wintypes.BOOL
    _user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
    _user32.PeekMessageW.restype = wintypes.BOOL
else:  # pragma: no cover - 仅在非 Windows 上走到
    _user32 = None
    _kernel32 = None


class HotkeyListener(QThread):
    """在后台线程里持有一个全局热键。

    信号：
    * :attr:`activated` —— 热键被按下（在主线程中发出）。
    * :attr:`registration_failed` —— 注册失败，附带中文原因。
    """

    activated = Signal()
    registration_failed = Signal(str)

    def __init__(self, hotkey: str, parent=None) -> None:
        super().__init__(parent)
        self._hotkey = hotkey
        self._thread_id: int = 0
        self._registered = False

    # ------------------------------------------------------------------
    @property
    def hotkey(self) -> str:
        return self._hotkey

    def is_registered(self) -> bool:
        return self._registered

    # ------------------------------------------------------------------
    def run(self) -> None:  # noqa: D102 - QThread 入口
        if not IS_WINDOWS:
            self.registration_failed.emit("全局快捷键目前仅支持 Windows")
            return

        try:
            spec = parse_hotkey(self._hotkey)
        except HotkeyError as exc:
            self.registration_failed.emit(str(exc))
            return

        assert _user32 is not None and _kernel32 is not None
        self._thread_id = int(_kernel32.GetCurrentThreadId())

        # RegisterHotKey 要求调用线程拥有消息队列，先 Peek 一次强制创建。
        msg = wintypes.MSG()
        _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)

        flags = spec.modifiers | MOD_NOREPEAT
        if not _user32.RegisterHotKey(None, HOTKEY_ID, flags, spec.virtual_key):
            code = ctypes.get_last_error()
            self.registration_failed.emit(describe_error(code))
            return

        self._registered = True
        try:
            while True:
                result = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result == 0 or result == -1:
                    break
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    self.activated.emit()
        finally:
            self._registered = False
            _user32.UnregisterHotKey(None, HOTKEY_ID)

    # ------------------------------------------------------------------
    def stop(self) -> None:
        """请求线程退出并等待结束。"""
        if IS_WINDOWS and self._thread_id:
            assert _user32 is not None
            _user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self.wait(2000)


def probe_hotkey(hotkey: str) -> tuple[bool, str]:
    """在调用线程内尝试注册一次，用于 Settings 里校验快捷键是否可用。

    返回 ``(是否可用, 失败原因)``。校验完成后立即注销，不会长期占用。
    """
    if not IS_WINDOWS:
        return False, "全局快捷键目前仅支持 Windows"
    try:
        spec = parse_hotkey(hotkey)
    except HotkeyError as exc:
        return False, str(exc)

    assert _user32 is not None
    if _user32.RegisterHotKey(None, HOTKEY_ID, spec.modifiers | MOD_NOREPEAT, spec.virtual_key):
        _user32.UnregisterHotKey(None, HOTKEY_ID)
        return True, ""
    return False, describe_error(ctypes.get_last_error())


# ----------------------------------------------------------------------
# 前台窗口激活
# ----------------------------------------------------------------------
if IS_WINDOWS:
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    _user32.AttachThreadInput.restype = wintypes.BOOL
    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _user32.SetForegroundWindow.restype = wintypes.BOOL
    _user32.BringWindowToTop.argtypes = [wintypes.HWND]
    _user32.BringWindowToTop.restype = wintypes.BOOL


def force_foreground(hwnd: int) -> bool:
    """把窗口强行带到前台并取得键盘焦点。

    Windows 默认禁止后台进程抢占前台，这里用 AttachThreadInput 把当前线程
    挂到前台线程上，绕开该限制。失败不抛异常，交由 Qt 的 activateWindow 兜底。
    """
    if not IS_WINDOWS or not hwnd:
        return False
    assert _user32 is not None and _kernel32 is not None

    try:
        foreground = _user32.GetForegroundWindow()
        if foreground == hwnd:
            return True

        current_thread = int(_kernel32.GetCurrentThreadId())
        target_thread = 0
        if foreground:
            target_thread = int(_user32.GetWindowThreadProcessId(foreground, None))

        attached = False
        if target_thread and target_thread != current_thread:
            attached = bool(_user32.AttachThreadInput(target_thread, current_thread, True))
        try:
            _user32.BringWindowToTop(hwnd)
            _user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                _user32.AttachThreadInput(target_thread, current_thread, False)

        return _user32.GetForegroundWindow() == hwnd
    except OSError:
        return False


__all__ = [
    "HotkeyError",
    "HotkeyListener",
    "HotkeySpec",
    "IS_WINDOWS",
    "describe_error",
    "force_foreground",
    "parse_hotkey",
    "probe_hotkey",
]
