"""文件读写工具：原子写入与换行风格保持。

Prompt 文件是用户的真实数据，任何一次写入都必须是"要么完整成功、要么完全
不动原文件"。这里统一提供原子写入，避免程序在写入途中崩溃时把 Markdown
内容截断成半截。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def read_text(path: Path) -> str:
    """以 UTF-8 读取文本，保留文件中原本的换行风格。

    使用 ``newline=""`` 关闭通用换行转换，确保读到什么就复制什么，
    剪贴板内容与原文件逐字节一致。
    """
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return handle.read()


def detect_newline(text: str) -> str:
    """推断文本的换行风格，返回 ``"\\r\\n"`` 或 ``"\\n"``。"""
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    return "\r\n" if crlf > lf else "\n"


def to_newline_style(text: str, newline: str) -> str:
    """把任意换行的文本统一成指定换行风格。"""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if newline == "\r\n":
        return normalized.replace("\n", "\r\n")
    return normalized


def atomic_write_text(path: Path, text: str, newline: str = "\n") -> None:
    """原子写入文本：先写同目录临时文件，再整体替换目标文件。

    临时文件与目标文件在同一个目录，保证 ``os.replace`` 是同一卷内的原子操作。
    写入过程抛错时删除临时文件，原文件保持不变。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = to_newline_style(text, newline)

    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=".agentdeck-", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


__all__ = [
    "atomic_write_text",
    "detect_newline",
    "read_text",
    "to_newline_style",
]
