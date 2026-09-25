"""Prompt 编辑器：新建 / 编辑 / 重命名共用一个对话框。

对话框只负责收集用户输入，不直接操作文件；真正的读写由
:class:`src.prompt_store.PromptStore` 在调用方完成。
"""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..prompt_store import Prompt, sanitize_category, sanitize_name
from .theme import scaled

MODE_NEW = "new"
MODE_EDIT = "edit"
MODE_RENAME = "rename"


class PromptEditorDialog(QDialog):
    """收集 Prompt 的名称、分类与正文。"""

    def __init__(
        self,
        mode: str,
        *,
        name: str = "",
        category: str = "",
        content: str = "",
        categories: Iterable[str] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._mode = mode
        self._original_name = name

        titles = {MODE_NEW: "新建 Prompt", MODE_EDIT: "编辑 Prompt", MODE_RENAME: "重命名 Prompt"}
        self.setWindowTitle(titles.get(mode, "Prompt"))
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # --- 名称 ---
        self._name_label = QLabel("Prompt Name")
        self._name_label.setObjectName("FieldLabel")
        layout.addWidget(self._name_label)

        self._name_edit = QLineEdit(name)
        self._name_edit.setPlaceholderText("例如：精读论文")
        layout.addWidget(self._name_edit)

        # --- 分类 ---
        self._category_label = QLabel("Category")
        self._category_label.setObjectName("FieldLabel")
        layout.addWidget(self._category_label)

        self._category_combo = QComboBox()
        self._category_combo.setEditable(True)
        self._category_combo.setInsertPolicy(QComboBox.NoInsert)
        for item in sorted(set(categories), key=str.casefold):
            self._category_combo.addItem(item)
        if category:
            self._category_combo.setCurrentText(category)
        layout.addWidget(self._category_combo)

        category_hint = QLabel("输入不存在的分类名会自动创建该目录，可用「父/子」形式分层。")
        category_hint.setObjectName("HintLabel")
        layout.addWidget(category_hint)

        # --- 正文 ---
        self._content_label = QLabel("Prompt Content")
        self._content_label.setObjectName("FieldLabel")
        layout.addWidget(self._content_label)

        self._content_edit = QPlainTextEdit(content)
        self._content_edit.setObjectName("EditorContent")
        self._content_edit.setPlaceholderText(
            "这里的内容会被完整复制到剪贴板。可用 {{变量名}} 定义复制前填写的变量。"
        )
        self._content_edit.setTabChangesFocus(False)
        layout.addWidget(self._content_edit, 1)

        self._status = QLabel("")
        self._status.setObjectName("HintLabel")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        # --- 按钮 ---
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)

        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(cancel_button)

        save_text = "保存" if mode != MODE_RENAME else "重命名"
        self._save_button = QPushButton(save_text)
        self._save_button.setObjectName("Primary")
        self._save_button.setDefault(True)
        self._save_button.clicked.connect(self.accept)
        buttons.addWidget(self._save_button)

        layout.addLayout(buttons)

        QShortcut(QKeySequence("Esc"), self, activated=self.reject)

        # 所有控件就绪后再接信号，避免校验函数访问尚未创建的成员。
        self._name_edit.textChanged.connect(self._validate)
        self._category_combo.editTextChanged.connect(self._validate)

        self._apply_mode()
        self._validate()

    # ------------------------------------------------------------------
    @classmethod
    def for_new(
        cls, categories: Iterable[str] = (), default_category: str = "", parent: QWidget | None = None
    ) -> "PromptEditorDialog":
        return cls(MODE_NEW, category=default_category, categories=categories, parent=parent)

    @classmethod
    def for_edit(
        cls, prompt: Prompt, categories: Iterable[str] = (), parent: QWidget | None = None
    ) -> "PromptEditorDialog":
        return cls(
            MODE_EDIT,
            name=prompt.name,
            category=prompt.category,
            content=prompt.content,
            categories=categories,
            parent=parent,
        )

    @classmethod
    def for_rename(cls, prompt: Prompt, parent: QWidget | None = None) -> "PromptEditorDialog":
        return cls(MODE_RENAME, name=prompt.name, parent=parent)

    # ------------------------------------------------------------------
    def values(self) -> tuple[str, str, str]:
        """返回 ``(名称, 分类, 正文)``。重命名模式下后两项为空字符串。"""
        if self._mode == MODE_RENAME:
            return self._name_edit.text(), "", ""
        return (
            self._name_edit.text(),
            self._category_combo.currentText(),
            self._content_edit.toPlainText(),
        )

    def cleaned_name(self) -> str:
        """返回清洗后的文件名（去掉非法字符）。"""
        return sanitize_name(self._name_edit.text())

    def cleaned_category(self) -> str:
        return sanitize_category(self._category_combo.currentText())

    # ------------------------------------------------------------------
    def _apply_mode(self) -> None:
        """按模式隐藏无关字段。"""
        if self._mode == MODE_RENAME:
            self._content_label.hide()
            self._content_edit.hide()
            self._category_label.hide()
            self._category_combo.hide()
            # 不锁死高度：字体放大后由布局自己撑开，避免文字被裁。
            self.setMinimumWidth(scaled(420))
            self.resize(scaled(420), scaled(190))
        else:
            self.setMinimumSize(640, 520)

        if self._mode == MODE_NEW:
            self._name_edit.setFocus(Qt.OtherFocusReason)
        elif self._mode == MODE_RENAME:
            self._name_edit.setFocus(Qt.OtherFocusReason)
            self._name_edit.selectAll()
        else:
            self._content_edit.setFocus(Qt.OtherFocusReason)

    def _validate(self) -> None:
        """实时给出名称清洗提示。"""
        raw_name = self._name_edit.text().strip()
        raw_category = self._category_combo.currentText().strip()
        problems: list[str] = []

        if not raw_name:
            problems.append("请填写 Prompt 名称")
        else:
            cleaned = sanitize_name(raw_name)
            if cleaned != raw_name:
                problems.append(f"名称含非法字符，将保存为「{cleaned}」")

        if self._mode != MODE_RENAME and raw_category:
            cleaned_category = sanitize_category(raw_category)
            if cleaned_category != raw_category.strip().strip("/\\"):
                problems.append(f"分类将保存为「{cleaned_category}」")

        self._status.setText("；".join(problems))
        self._save_button.setEnabled(bool(raw_name))


__all__ = ["MODE_EDIT", "MODE_NEW", "MODE_RENAME", "PromptEditorDialog"]
