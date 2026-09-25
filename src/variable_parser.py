"""Prompt 变量解析。

支持 ``{{VARIABLE_NAME}}`` 语法：任何被双花括号包起来的片段都视为变量，
变量名允许中文、字母、数字、下划线等（不含花括号与换行）。
"""

from __future__ import annotations

import re
from collections.abc import Mapping

# 变量名：1~64 个字符，不能包含花括号或换行；两侧空白会被忽略。
_VARIABLE_RE = re.compile(r"\{\{([^{}\r\n]{1,64}?)\}\}")

MAX_VARIABLE_NAME_LENGTH = 64


def extract_variables(text: str) -> list[str]:
    """按首次出现顺序返回去重后的变量名列表。"""
    variables: list[str] = []
    seen: set[str] = set()
    for match in _VARIABLE_RE.finditer(text):
        name = match.group(1).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        variables.append(name)
    return variables


def has_variables(text: str) -> bool:
    """文本中是否包含至少一个变量。"""
    return _VARIABLE_RE.search(text) is not None


def substitute(text: str, values: Mapping[str, str]) -> str:
    """替换所有变量，同一变量出现多次会被全部替换。

    未在 ``values`` 中提供（或值为 ``None``）的变量保持原样，避免因为漏填
    而静默丢失信息。
    """
    def _replace(match: re.Match[str]) -> str:
        name = match.group(1).strip()
        if name not in values:
            return match.group(0)
        value = values[name]
        if value is None:
            return match.group(0)
        return str(value)

    return _VARIABLE_RE.sub(_replace, text)


__all__ = [
    "MAX_VARIABLE_NAME_LENGTH",
    "extract_variables",
    "has_variables",
    "substitute",
]
