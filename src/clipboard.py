"""系统剪贴板读写（基于 Qt，不引入额外依赖）。"""

from __future__ import annotations

from PySide6.QtGui import QGuiApplication


def copy_text(text: str) -> bool:
    """把文本写入系统剪贴板，成功返回 True。

    写入后再读回校验一次：某些环境下剪贴板可能被其他程序占用，读回校验
    能让调用方得到真实的成功/失败结果，而不是静默失败。
    """
    clipboard = QGuiApplication.clipboard()
    if clipboard is None:
        return False
    clipboard.setText(text)
    return clipboard.text() == text


def read_text() -> str:
    """读取系统剪贴板中的纯文本。"""
    clipboard = QGuiApplication.clipboard()
    if clipboard is None:
        return ""
    return clipboard.text()


__all__ = ["copy_text", "read_text"]
