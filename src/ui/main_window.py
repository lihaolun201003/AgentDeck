"""主窗口：搜索框 + 分类侧边栏 + 结果列表 + 预览区。

使用原生窗口边框与最大化按钮，支持 Windows 贴靠分屏。
关闭按钮与 Esc 都只做"隐藏"，真正的退出由托盘菜单负责。
"""

from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizeGrip,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..clipboard import copy_text
from ..hotkey import force_foreground
from ..prompt_store import (
    Prompt,
    PromptExistsError,
    PromptStore,
    PromptStoreError,
    sanitize_category,
    search_prompts,
)
from ..settings import Settings
from ..variable_parser import substitute
from .prompt_editor import PromptEditorDialog
from .responsive_browser import CATEGORY_MIN_HEIGHT, ResponsiveBrowser
from .settings_dialog import SettingsDialog
from .theme import apply_font_size, scaled, set_state
from .variable_dialog import VariableDialog
from .window_placement import WindowPlacement
from .widgets import (
    PromptItemDelegate,
    PromptListWidget,
    SearchLineEdit,
    SidebarDelegate,
    SidebarEntry,
    search_icon,
)

#: 侧边栏中的虚拟分类键。
ALL_KEY = "all"
FAVORITES_KEY = "favorites"
RECENT_KEY = "recent"

# 以下像素值都按默认字号设计，实际使用前一律经 theme.scaled() 换算，
# 字体放大后标题栏、状态栏和按钮不会裁掉文字。
TITLE_BAR_HEIGHT = 30
STATUS_BAR_HEIGHT = 28
COPY_BUTTON_HEIGHT = 34
PREVIEW_MIN_HEIGHT = 60
SIDEBAR_MIN_WIDTH = 120
SIDEBAR_MAX_WIDTH = 280

#: 显示 "Copied ✓" 之后延迟隐藏窗口的毫秒数。
COPIED_HIDE_DELAY_MS = 420
#: 状态提示自动消失的毫秒数。
STATUS_RESET_MS = 1800


class MainWindow(QWidget):
    """AgentDeck 的主界面。"""

    request_hide = Signal()
    settings_changed = Signal()

    def __init__(self, store: PromptStore, settings: Settings) -> None:
        super().__init__(None)
        self._store = store
        self._settings = settings

        self._prompts: list[Prompt] = []
        self._prompts_by_id: dict[str, Prompt] = {}
        self._visible: list[Prompt] = []
        self._selected_category: str = ALL_KEY
        self._on_top = False

        self.setWindowTitle("AgentDeck")
        self.setWindowFlags(Qt.Window | Qt.WindowTitleHint | Qt.WindowSystemMenuHint
                            | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        self.setMinimumSize(340, 360)
        self.resize(settings.window_width, settings.window_height)

        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(self._reset_status)

        self._build_ui()
        self._placement = WindowPlacement(self, settings)
        self._bind_shortcuts()
        self.reload_prompts()

    # ==================================================================
    # 构建界面
    # ==================================================================
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_title_bar())
        root.addWidget(self._build_search_row())
        root.addWidget(_divider())
        root.addWidget(self._build_body(), 1)
        root.addWidget(_divider())
        root.addWidget(self._build_status_bar())

    def _build_title_bar(self) -> QWidget:
        bar = QWidget(self)
        bar.setObjectName("TitleBar")
        bar.setMinimumHeight(scaled(TITLE_BAR_HEIGHT))
        self._title_bar = bar

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 0, 6, 0)
        layout.setSpacing(2)

        title = QLabel("AGENTDECK")
        title.setObjectName("AppTitle")
        layout.addWidget(title)
        layout.addStretch(1)

        right_button = QPushButton("靠右")
        right_button.setObjectName("CompactButton")
        right_button.setToolTip("放到桌面右侧；也可以拖动标题栏使用 Windows 分屏")
        right_button.clicked.connect(lambda: self._placement.place_right())
        layout.addWidget(right_button)

        new_button = QPushButton("＋")
        new_button.setObjectName("IconButton")
        new_button.setToolTip("新建 Prompt（Ctrl+N）")
        new_button.setCursor(Qt.PointingHandCursor)
        new_button.clicked.connect(self.new_prompt)
        layout.addWidget(new_button)

        settings_button = QPushButton("⚙")
        settings_button.setObjectName("IconButton")
        settings_button.setToolTip("设置（Ctrl+,）")
        settings_button.setCursor(Qt.PointingHandCursor)
        settings_button.clicked.connect(self.open_settings)
        layout.addWidget(settings_button)

        return bar

    def _build_search_row(self) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(12, 0, 12, 10)
        layout.setSpacing(0)

        self._search = SearchLineEdit()
        self._search.setObjectName("SearchInput")
        self._search.setPlaceholderText("搜索 Prompt（名称 / 分类 / 正文）…")
        self._search.setClearButtonEnabled(True)
        self._search.addAction(search_icon(), QLineEdit.LeadingPosition)
        self._search.textChanged.connect(self._on_search_changed)
        self._search.navigate_next.connect(lambda: self._move_selection(1))
        self._search.navigate_previous.connect(lambda: self._move_selection(-1))
        self._search.submitted.connect(self.copy_selected)
        layout.addWidget(self._search)

        return container

    def _build_body(self) -> QWidget:
        self._sidebar = QListWidget()
        self._sidebar.setItemDelegate(SidebarDelegate(self._sidebar))
        self._sidebar.setUniformItemSizes(True)
        self._sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._sidebar.setMinimumWidth(scaled(SIDEBAR_MIN_WIDTH))
        self._sidebar.setMaximumWidth(scaled(SIDEBAR_MAX_WIDTH))
        self._sidebar.setFocusPolicy(Qt.NoFocus)
        self._sidebar.currentRowChanged.connect(self._on_category_changed)
        self._sidebar.setContextMenuPolicy(Qt.CustomContextMenu)
        self._sidebar.customContextMenuRequested.connect(self._on_sidebar_context_menu)

        self._list = PromptListWidget()
        self._list.setItemDelegate(PromptItemDelegate(self._list))
        self._list.setUniformItemSizes(True)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.setMinimumWidth(180)
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_list_context_menu)
        self._list.currentItemChanged.connect(self._on_current_item_changed)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._list.submitted.connect(self.copy_selected)
        self._browser = ResponsiveBrowser(self._sidebar, self._list, self._build_preview())
        self._splitter = self._browser.splitter
        self._browser.compact_changed.connect(self._on_compact_changed)
        return self._browser

    def _build_preview(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(6)

        self._preview_title = QLabel("未选择 Prompt")
        self._preview_title.setObjectName("PreviewTitle")
        self._preview_title.setWordWrap(True)
        self._preview_title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        header.addWidget(self._preview_title, 1)

        self._favorite_button = QPushButton("☆")
        self._favorite_button.setObjectName("IconButton")
        self._favorite_button.setToolTip("收藏 / 取消收藏（Ctrl+D）")
        self._favorite_button.setCursor(Qt.PointingHandCursor)
        self._favorite_button.setEnabled(False)
        self._favorite_button.clicked.connect(self.toggle_favorite)
        header.addWidget(self._favorite_button)

        layout.addLayout(header)

        self._preview_meta = QLabel("")
        self._preview_meta.setObjectName("PathLabel")
        self._preview_meta.setWordWrap(True)
        self._preview_meta.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(self._preview_meta)

        self._preview = QPlainTextEdit()
        self._preview.setObjectName("Preview")
        self._preview.setMinimumHeight(scaled(PREVIEW_MIN_HEIGHT))
        self._preview.setReadOnly(True)
        self._preview.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self._preview.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        layout.addWidget(self._preview, 1)

        self._copy_button = QPushButton("复制 Prompt")
        self._copy_button.setObjectName("Primary")
        self._copy_button.setMinimumHeight(scaled(COPY_BUTTON_HEIGHT))
        self._copy_button.setEnabled(False)
        self._copy_button.clicked.connect(self.copy_selected)
        layout.addWidget(self._copy_button)

        return container

    def _build_status_bar(self) -> QWidget:
        container = QWidget()
        container.setMinimumHeight(scaled(STATUS_BAR_HEIGHT))
        self._status_bar = container

        layout = QHBoxLayout(container)
        layout.setContentsMargins(12, 0, 4, 0)
        layout.setSpacing(8)

        self._status_label = QLabel("Enter 复制 · ↑↓ 选择 · Esc 隐藏")
        self._status_label.setObjectName("StatusLabel")
        layout.addWidget(self._status_label)

        self._count_label = QLabel("")
        self._count_label.setObjectName("PathLabel")
        layout.addWidget(self._count_label)
        layout.addStretch(1)

        self._toast_label = QLabel("")
        self._toast_label.setObjectName("ToastLabel")
        self._toast_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(self._toast_label)

        layout.addWidget(QSizeGrip(self))
        return container

    def _on_compact_changed(self, compact: bool) -> None:
        self._status_label.setText("Enter 复制" if compact else "Enter 复制 · ↑↓ 选择 · Esc 隐藏")

    def _bind_shortcuts(self) -> None:
        def bind(sequence: str, slot) -> None:
            QShortcut(QKeySequence(sequence), self, activated=slot)

        bind("Esc", self._request_hide)
        bind("Ctrl+N", self.new_prompt)
        bind("Ctrl+R", self.reload_prompts)
        bind("Ctrl+E", lambda: self.edit_prompt(self.current_prompt()))
        bind("Ctrl+D", self.toggle_favorite)
        bind("Ctrl+,", self.open_settings)
        bind("Ctrl+Return", self.copy_selected)

    # ==================================================================
    # 数据刷新
    # ==================================================================
    def reload_prompts(self) -> None:
        """重新扫描 prompts/ 目录并刷新界面。"""
        self._prompts = self._store.scan()
        self._prompts_by_id = {prompt.id: prompt for prompt in self._prompts}

        if self._settings.prune_ids(set(self._prompts_by_id)):
            self._settings.save()

        self._refresh_sidebar()
        self._refresh_list()

        if self._store.errors:
            self._flash_status(f"有 {len(self._store.errors)} 个文件读取失败", error=True)

    def _sidebar_entries(self) -> list[SidebarEntry]:
        entries = [SidebarEntry(ALL_KEY, "全部 Prompt", len(self._prompts))]
        favorites = sum(1 for prompt in self._prompts if self._settings.is_favorite(prompt.id))
        entries.append(SidebarEntry(FAVORITES_KEY, "★ 收藏", favorites))
        entries.append(SidebarEntry(RECENT_KEY, "最近使用", len(self._recent_prompts())))

        counts: dict[str, int] = {}
        for prompt in self._prompts:
            counts[prompt.category] = counts.get(prompt.category, 0) + 1

        known = set(self._store.categories())
        known.update(counts)
        for category in sorted(known, key=str.casefold):
            entries.append(SidebarEntry(category, category, counts.get(category, 0)))
        return entries

    def _refresh_sidebar(self) -> None:
        entries = self._sidebar_entries()

        self._sidebar.blockSignals(True)
        self._sidebar.clear()
        for entry in entries:
            item = QListWidgetItem(entry.label)
            item.setData(Qt.UserRole, entry.key)
            item.setData(Qt.UserRole + 1, entry.count)
            self._sidebar.addItem(item)

        row = 0
        for index in range(self._sidebar.count()):
            if self._sidebar.item(index).data(Qt.UserRole) == self._selected_category:
                row = index
                break
        else:
            self._selected_category = ALL_KEY
            row = 0

        self._sidebar.setCurrentRow(row)
        self._sidebar.blockSignals(False)
        self._browser.sync_categories(entries, row)

    def _recent_prompts(self) -> list[Prompt]:
        prompts: list[Prompt] = []
        for prompt_id in self._settings.recent:
            prompt = self._prompts_by_id.get(prompt_id)
            if prompt is not None:
                prompts.append(prompt)
        return prompts

    def _pool_for_category(self) -> list[Prompt]:
        key = self._selected_category
        if key == FAVORITES_KEY:
            return [prompt for prompt in self._prompts if self._settings.is_favorite(prompt.id)]
        if key == RECENT_KEY:
            return self._recent_prompts()
        if key in (ALL_KEY, "", None):
            return list(self._prompts)
        return [prompt for prompt in self._prompts if prompt.category == key]

    def _refresh_list(self, select_id: str | None = None, reset: bool = False) -> None:
        """按当前分类与搜索词重建结果列表。

        ``select_id`` 指定要选中的 Prompt；``reset`` 为真时选中第一项；
        两者都不给则尽量保持当前选中项。
        """
        if reset:
            select_id = None
        elif select_id is None:
            current = self.current_prompt()
            select_id = current.id if current else None

        pool = self._pool_for_category()
        query = self._search.text().strip()
        self._visible = search_prompts(pool, query)

        self._list.blockSignals(True)
        self._list.clear()
        for prompt in self._visible:
            item = QListWidgetItem(prompt.name)
            item.setData(Qt.UserRole, prompt.id)
            item.setData(Qt.UserRole + 1, prompt.has_variables)
            item.setToolTip(f"{prompt.display_name}\n{prompt.path}")
            self._list.addItem(item)
        self._list.blockSignals(False)

        self._count_label.setText(f"{len(self._visible)} / {len(self._prompts)}")

        if not self._visible:
            self._list.setCurrentRow(-1)
            self._show_preview(None)
            return

        row = 0
        if select_id:
            for index, prompt in enumerate(self._visible):
                if prompt.id == select_id:
                    row = index
                    break
        self._list.setCurrentRow(row)
        self._show_preview(self._visible[row])

    def _show_preview(self, prompt: Prompt | None) -> None:
        self._copy_button.setEnabled(prompt is not None)
        if prompt is None:
            self._preview_title.setText("没有可显示的 Prompt")
            self._preview_meta.setText("")
            self._preview.setPlainText("")
            self._favorite_button.setEnabled(False)
            self._favorite_button.setText("☆")
            return

        self._preview_title.setText(prompt.name)
        meta = f"{prompt.category} · {prompt.path.name}"
        if prompt.has_variables:
            meta += f" · 变量：{', '.join(prompt.variables)}"
        self._preview_meta.setText(meta)

        self._preview.setPlainText(prompt.content)
        self._preview.moveCursor(QTextCursor.Start)

        self._favorite_button.setEnabled(True)
        self._favorite_button.setText("★" if self._settings.is_favorite(prompt.id) else "☆")
        self._favorite_button.setToolTip(
            "取消收藏（Ctrl+D）" if self._settings.is_favorite(prompt.id) else "加入收藏（Ctrl+D）"
        )

    # ==================================================================
    # 交互
    # ==================================================================
    def _on_search_changed(self, _text: str) -> None:
        self._refresh_list(reset=True)

    def _on_category_changed(self, row: int) -> None:
        if row < 0:
            return
        item = self._sidebar.item(row)
        if item is None:
            return
        self._selected_category = item.data(Qt.UserRole) or ALL_KEY
        self._browser.sync_selection(row)
        self._refresh_list(reset=True)

    def _on_current_item_changed(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        self._show_preview(self._prompt_of_item(current))

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        prompt = self._prompt_of_item(item)
        if prompt is not None:
            self.copy_prompt(prompt)

    def _move_selection(self, delta: int) -> None:
        """搜索框里按上下键时移动结果列表的选中项。"""
        if not self._visible:
            return
        row = self._list.currentRow()
        if row < 0:
            row = 0
        else:
            row = max(0, min(len(self._visible) - 1, row + delta))
        self._list.setCurrentRow(row)
        item = self._list.item(row)
        if item is not None:
            self._list.scrollToItem(item)

    def current_prompt(self) -> Prompt | None:
        """返回当前选中的 Prompt。"""
        row = self._list.currentRow()
        if 0 <= row < len(self._visible):
            return self._visible[row]
        return None

    def _prompt_of_item(self, item: QListWidgetItem | None) -> Prompt | None:
        if item is None:
            return None
        return self._prompts_by_id.get(item.data(Qt.UserRole))

    # ------------------------------------------------------------------
    # 复制
    # ------------------------------------------------------------------
    def copy_selected(self) -> None:
        prompt = self.current_prompt()
        if prompt is None:
            self._flash_status("没有可复制的 Prompt", error=True)
            return
        self.copy_prompt(prompt)

    def copy_prompt(self, prompt: Prompt) -> None:
        """复制 Prompt：有变量先弹窗填写，然后写入剪贴板。"""
        text = prompt.content

        if prompt.has_variables:
            dialog = VariableDialog(list(prompt.variables), prompt.display_name, self)
            if dialog.exec() != QDialog.Accepted:
                self._search.setFocus(Qt.OtherFocusReason)
                return
            text = substitute(prompt.content, dialog.values())

        if not copy_text(text):
            self._flash_status("复制失败：剪贴板被其他程序占用", error=True)
            return

        self._settings.add_recent(prompt.id)
        self._settings.save()

        self._flash_status(f"Copied ✓  {prompt.name}")
        if self._selected_category == RECENT_KEY or self._selected_category == FAVORITES_KEY:
            self._refresh_list(select_id=prompt.id)

        if self._settings.hide_after_copy:
            QTimer.singleShot(COPIED_HIDE_DELAY_MS, self._request_hide)

    def toggle_favorite(self) -> None:
        prompt = self.current_prompt()
        if prompt is None:
            return
        self.set_favorite(prompt, not self._settings.is_favorite(prompt.id))

    def set_favorite(self, prompt: Prompt, favorite: bool) -> None:
        if self._settings.is_favorite(prompt.id) != favorite:
            self._settings.toggle_favorite(prompt.id)
        self._settings.save()
        self._flash_status("已加入收藏 ★" if favorite else "已取消收藏 ☆")
        self._refresh_list(select_id=prompt.id)
        self._refresh_sidebar()

    # ------------------------------------------------------------------
    # 编辑操作
    # ------------------------------------------------------------------
    def new_prompt(self) -> None:
        default_category = self._selected_category
        if default_category in (ALL_KEY, FAVORITES_KEY, RECENT_KEY):
            default_category = ""

        dialog = PromptEditorDialog.for_new(self._store.categories(), default_category, self)
        if dialog.exec() != QDialog.Accepted:
            self._focus_search()
            return

        name = dialog.cleaned_name()
        category = dialog.cleaned_category()
        _, _, content = dialog.values()
        try:
            prompt = self._store.create(name, category, content)
        except PromptExistsError as exc:
            self._error_box("新建失败", str(exc))
            return
        except (PromptStoreError, OSError) as exc:
            self._error_box("新建失败", f"{exc}")
            return

        self.reload_prompts()
        self._select_prompt(prompt)
        self._flash_status(f"已新建：{prompt.display_name}")

    def edit_prompt(self, prompt: Prompt | None = None) -> None:
        prompt = prompt or self.current_prompt()
        if prompt is None:
            return

        dialog = PromptEditorDialog.for_edit(prompt, self._store.categories(), self)
        if dialog.exec() != QDialog.Accepted:
            self._focus_search()
            return

        name = dialog.cleaned_name()
        category = dialog.cleaned_category()
        _, _, content = dialog.values()
        self._apply_update(prompt, name=name, category=category, content=content)

    def rename_prompt(self, prompt: Prompt | None = None) -> None:
        prompt = prompt or self.current_prompt()
        if prompt is None:
            return

        dialog = PromptEditorDialog.for_rename(prompt, self)
        if dialog.exec() != QDialog.Accepted:
            self._focus_search()
            return

        self._apply_update(prompt, name=dialog.cleaned_name())

    def _apply_update(
        self,
        prompt: Prompt,
        *,
        name: str | None = None,
        category: str | None = None,
        content: str | None = None,
    ) -> None:
        old_id = prompt.id
        try:
            updated = self._store.update(prompt, name=name, category=category, content=content)
        except PromptExistsError as exc:
            self._error_box("保存失败", str(exc))
            return
        except (PromptStoreError, OSError) as exc:
            self._error_box("保存失败", str(exc))
            return

        if updated.id != old_id:
            self._settings.rename_id(old_id, updated.id)
            self._settings.save()

        self.reload_prompts()
        self._select_prompt(updated)
        self._flash_status(f"已保存：{updated.display_name}")

    def delete_prompt(self, prompt: Prompt | None = None) -> None:
        prompt = prompt or self.current_prompt()
        if prompt is None:
            return

        box = QMessageBox(self)
        box.setWindowTitle("删除 Prompt")
        box.setIcon(QMessageBox.Warning)
        box.setText(f"确定删除「{prompt.display_name}」？")
        box.setInformativeText(f"文件将被永久删除：\n{prompt.path}\n\n此操作不可撤销。")
        delete_button = box.addButton("删除", QMessageBox.DestructiveRole)
        cancel_button = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(cancel_button)
        box.exec()

        if box.clickedButton() is not delete_button:
            self._focus_search()
            return

        try:
            self._store.delete(prompt)
        except OSError as exc:
            self._error_box("删除失败", f"{exc}")
            return

        self._settings.remove_id(prompt.id)
        self._settings.save()
        self.reload_prompts()
        self._flash_status(f"已删除：{prompt.name}")

    def new_category(self) -> None:
        name, accepted = QInputDialog.getText(self, "新建分类", "分类名称（可用「父/子」分层）：")
        if not accepted or not name.strip():
            self._focus_search()
            return

        try:
            category = self._store.create_category(name)
        except OSError as exc:
            self._error_box("新建分类失败", f"{exc}")
            return

        self._selected_category = category
        self.reload_prompts()
        self._flash_status(f"已创建分类：{category}")

    def open_file_location(self, prompt: Prompt | None = None) -> None:
        prompt = prompt or self.current_prompt()
        if prompt is None:
            return
        path = prompt.path
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", os.path.normpath(str(path))])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path.parent)])
        except OSError as exc:
            self._error_box("无法打开文件位置", str(exc))

    def open_settings(self) -> None:
        dialog = SettingsDialog(
            self._settings.hotkey,
            self._settings.always_on_top,
            self._settings.hide_after_copy,
            self,
            font_size=self._settings.font_size,
        )
        if dialog.exec() != QDialog.Accepted:
            self._focus_search()
            return

        self._settings.hotkey = dialog.hotkey()
        self._settings.always_on_top = dialog.always_on_top()
        self._settings.hide_after_copy = dialog.hide_after_copy()
        self._settings.font_size = dialog.font_size()
        self._settings.save()

        self.apply_settings()
        self.settings_changed.emit()
        self._flash_status("设置已保存")
        self._focus_search()

    def apply_settings(self) -> None:
        """把设置同步到窗口（快捷键由 app 层重新注册）。"""
        self._apply_topmost_flag()
        self.set_font_size(self._settings.font_size)

    def set_font_size(self, size: int) -> None:
        """应用界面字号并立即刷新布局。

        设置对话框改 SpinBox 时会直接调用这里做预览，取消时再调回原值，
        所以这里只改内存中的配置，落盘由调用方决定。
        """
        self._settings.font_size = apply_font_size(QApplication.instance(), size)
        self.refresh_font_metrics()

    def refresh_font_metrics(self) -> None:
        """字号变化后重算所有依赖字体的像素尺寸并让列表重新排版。"""
        self._title_bar.setMinimumHeight(scaled(TITLE_BAR_HEIGHT))
        self._status_bar.setMinimumHeight(scaled(STATUS_BAR_HEIGHT))
        self._copy_button.setMinimumHeight(scaled(COPY_BUTTON_HEIGHT))
        self._preview.setMinimumHeight(scaled(PREVIEW_MIN_HEIGHT))
        self._sidebar.setMinimumWidth(scaled(SIDEBAR_MIN_WIDTH))
        self._sidebar.setMaximumWidth(scaled(SIDEBAR_MAX_WIDTH))
        self._browser.categories.setMinimumHeight(scaled(CATEGORY_MIN_HEIGHT))
        # 行高由委托按字体度量给出，必须显式重排才会用上新字号。
        self._sidebar.doItemsLayout()
        self._list.doItemsLayout()

    def _apply_topmost_flag(self) -> None:
        want_top = bool(self._settings.always_on_top)
        if want_top == self._on_top:
            return
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, want_top)
        self._on_top = want_top
        if visible:
            self.show()

    # ------------------------------------------------------------------
    # 右键菜单
    # ------------------------------------------------------------------
    def _on_list_context_menu(self, position) -> None:
        item = self._list.itemAt(position)
        prompt = self._prompt_of_item(item)
        if prompt is not None:
            self._list.setCurrentItem(item)
        self._build_list_menu(prompt).exec(self._list.mapToGlobal(position))

    def _build_list_menu(self, prompt: Prompt | None) -> QMenu:
        """构建结果列表的右键菜单。"""
        menu = QMenu(self)
        if prompt is None:
            menu.addAction("新建 Prompt…", self.new_prompt)
            menu.addAction("重新扫描 prompts/", self.reload_prompts)
        else:
            is_favorite = self._settings.is_favorite(prompt.id)

            # "\t" 让 Qt 把快捷键提示右对齐显示。
            copy_action = QAction("复制\tEnter", menu)
            copy_action.triggered.connect(lambda: self.copy_prompt(prompt))
            menu.addAction(copy_action)

            favorite_action = QAction(
                ("取消收藏\tCtrl+D") if is_favorite else ("加入收藏\tCtrl+D"), menu
            )
            favorite_action.triggered.connect(lambda: self.set_favorite(prompt, not is_favorite))
            menu.addAction(favorite_action)

            menu.addSeparator()

            edit_action = QAction("编辑…", menu)
            edit_action.triggered.connect(lambda: self.edit_prompt(prompt))
            menu.addAction(edit_action)

            rename_action = QAction("重命名…", menu)
            rename_action.triggered.connect(lambda: self.rename_prompt(prompt))
            menu.addAction(rename_action)

            delete_action = QAction("删除…", menu)
            delete_action.triggered.connect(lambda: self.delete_prompt(prompt))
            menu.addAction(delete_action)

            menu.addSeparator()

            reveal_action = QAction("打开文件位置", menu)
            reveal_action.triggered.connect(lambda: self.open_file_location(prompt))
            menu.addAction(reveal_action)

            menu.addSeparator()
            menu.addAction("新建 Prompt…", self.new_prompt)

        return menu

    def _on_sidebar_context_menu(self, position) -> None:
        item = self._sidebar.itemAt(position)
        menu = QMenu(self)

        if item is not None:
            key = item.data(Qt.UserRole) or ALL_KEY
            if key not in (ALL_KEY, FAVORITES_KEY, RECENT_KEY):
                rename_action = QAction("重命名分类…", menu)
                rename_action.triggered.connect(lambda: self._rename_category(key))
                menu.addAction(rename_action)
                menu.addSeparator()

        if self._selected_category == RECENT_KEY:
            clear_action = QAction("清空最近使用", menu)
            clear_action.triggered.connect(self._clear_recent)
            menu.addAction(clear_action)
            menu.addSeparator()

        menu.addAction("新建分类…", self.new_category)
        menu.addAction("重新扫描 prompts/", self.reload_prompts)
        menu.exec(self._sidebar.mapToGlobal(position))

    def _rename_category(self, category: str) -> None:
        new_name, accepted = QInputDialog.getText(
            self, "重命名分类", "新的分类名称：", text=category
        )
        if not accepted or not new_name.strip():
            self._focus_search()
            return

        target = sanitize_category(new_name)
        if target == category:
            return

        try:
            self._store.create_category(target)
        except OSError as exc:
            self._error_box("重命名分类失败", str(exc))
            return

        affected: list[Prompt] = []
        for prompt in self._prompts:
            if prompt.category != category:
                continue
            try:
                affected.append(
                    self._store.update(prompt, name=prompt.name, category=target, content=prompt.content)
                )
            except (PromptStoreError, OSError) as exc:
                self._error_box("重命名分类失败", f"{prompt.name}: {exc}")
                break

        # 清理可能已经变空的旧目录
        try:
            old_dir = self._store.root / category
            if old_dir.is_dir() and not any(old_dir.iterdir()):
                old_dir.rmdir()
        except OSError:
            pass

        self._selected_category = target
        self.reload_prompts()
        self._flash_status(f"已重命名分类为 {target}（{len(affected)} 个 Prompt）")

    def _clear_recent(self) -> None:
        self._settings.clear_recent()
        self._settings.save()
        self._refresh_sidebar()
        self._refresh_list(reset=True)
        self._flash_status("已清空最近使用")

    # ------------------------------------------------------------------
    # 状态提示
    # ------------------------------------------------------------------
    def _flash_status(self, text: str, error: bool = False) -> None:
        set_state(self._toast_label, "error" if error else "ok")
        self._toast_label.setText(text)
        self._status_timer.start(STATUS_RESET_MS)

    def _reset_status(self) -> None:
        self._toast_label.setText("")

    def _focus_search(self) -> None:
        self._search.setFocus(Qt.OtherFocusReason)

    def _error_box(self, title: str, message: str) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Critical)
        box.setText(message)
        box.addButton("知道了", QMessageBox.AcceptRole)
        box.exec()
        self._focus_search()

    # ------------------------------------------------------------------
    # 窗口生命周期
    # ------------------------------------------------------------------
    def show_launcher(self) -> None:
        """呼出窗口：重置状态、重新扫描、置顶并聚焦搜索框。"""
        self._apply_topmost_flag()

        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)

        self._selected_category = ALL_KEY
        self.reload_prompts()
        if self._visible:
            self._list.setCurrentRow(0)
            self._show_preview(self._visible[0])
        self._placement.restore()

        if self._settings.window_maximized:
            self.showMaximized()
        elif self.isMinimized():
            self.showNormal()
        else:
            self.show()

        self.raise_()
        self.activateWindow()
        self._search.setFocus(Qt.OtherFocusReason)
        self._status_timer.stop()
        self._toast_label.setText("")

        # 从全局热键唤醒时 Windows 会阻止后台进程抢前台，show 之后再强行激活一次。
        QTimer.singleShot(0, self._grab_foreground)

    def _grab_foreground(self) -> None:
        try:
            force_foreground(int(self.winId()))
        except (RuntimeError, TypeError):
            pass
        self.raise_()
        self.activateWindow()
        self._search.setFocus(Qt.OtherFocusReason)

    def _request_hide(self) -> None:
        """隐藏窗口（不退出程序），并记住当前尺寸。"""
        self.save_window_size()
        self.request_hide.emit()

    def save_window_size(self) -> None:
        """保存位置、尺寸和最大化状态，呼出时不再强行居中。"""
        self._placement.save()

    def show_status_message(self, message: str, error: bool = False) -> None:
        """在状态栏右侧显示一条提示（供应用层调用）。"""
        self._flash_status(message, error=error)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 命名风格
        """点击关闭按钮只隐藏窗口，退出必须走托盘菜单。"""
        event.ignore()
        self._request_hide()

    def _select_prompt(self, prompt: Prompt) -> None:
        """选中指定 Prompt（必要时切回全部分类）。"""
        if prompt.id not in self._prompts_by_id:
            return
        if self._selected_category not in (ALL_KEY, prompt.category):
            self._selected_category = ALL_KEY
            self._refresh_sidebar()
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._refresh_list(select_id=prompt.id)


def _divider() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    line.setFixedHeight(1)
    line.setFrameShape(QFrame.NoFrame)
    return line


__all__ = ["MainWindow"]
