"""变量填写对话框：复制带 ``{{VARIABLE}}`` 的 Prompt 时弹出。"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .theme import set_state

#: 单行输入框的宽度，够输入常见路径。
EDITOR_WIDTH = 420


class VariableDialog(QDialog):
    """让用户为 Prompt 中的每个变量填写取值。

    变量按提示中的首次出现顺序排列，同名变量只出现一次。
    """

    def __init__(
        self,
        variables: Sequence[str],
        prompt_name: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._editors: dict[str, QLineEdit] = {}

        self.setWindowTitle("填写变量")
        self.setModal(True)
        self.setMinimumWidth(EDITOR_WIDTH + 80)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        title = QLabel(prompt_name or "Prompt")
        title.setObjectName("DialogTitle")
        title.setWordWrap(True)
        layout.addWidget(title)

        hint = QLabel("以下变量会在复制前被替换，回车确认。")
        hint.setObjectName("HintLabel")
        layout.addWidget(hint)

        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.setColumnStretch(1, 1)

        for row, name in enumerate(variables):
            label = QLabel(f"{name}")
            label.setObjectName("FieldLabel")
            label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

            editor = QLineEdit()
            editor.setPlaceholderText(f"{name} 的值")
            editor.setMinimumWidth(EDITOR_WIDTH)
            editor.returnPressed.connect(self.accept)
            self._editors[name] = editor

            form.addWidget(label, row, 0)
            form.addWidget(editor, row, 1)

        layout.addLayout(form)

        self._warning = QLabel("")
        self._warning.setObjectName("WarningLabel")
        set_state(self._warning, "muted")
        layout.addWidget(self._warning)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)

        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(cancel_button)

        copy_button = QPushButton("复制")
        copy_button.setObjectName("Primary")
        copy_button.setDefault(True)
        copy_button.clicked.connect(self._on_accept)
        buttons.addWidget(copy_button)

        layout.addLayout(buttons)

        if variables:
            first = self._editors[variables[0]]
            first.setFocus(Qt.OtherFocusReason)
            first.selectAll()

    # ------------------------------------------------------------------
    def values(self) -> dict[str, str]:
        """返回变量取值。留空的变量会被替换成空字符串。"""
        return {name: editor.text() for name, editor in self._editors.items()}

    def _on_accept(self) -> None:
        """提交前提示哪些变量留空了，但不阻止复制。"""
        empty = [name for name, editor in self._editors.items() if not editor.text().strip()]
        if empty and not self._warning.text():
            set_state(self._warning, "warning")
            self._warning.setText(
                f"{'、'.join(empty)} 为空，将替换为空内容；再次点击「复制」确认。"
            )
            return
        self.accept()


__all__ = ["VariableDialog"]
