"""在宽窗口使用三栏，在窄窗口使用分类下拉框和上下分区。"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QSplitter, QVBoxLayout, QWidget

from .theme import scaled

#: 分类下拉框的最小高度（按默认字号设计，字体放大后等比放大）。
CATEGORY_MIN_HEIGHT = 30


class ResponsiveBrowser(QWidget):
    compact_changed = Signal(bool)
    BREAKPOINT = 720

    def __init__(self, sidebar, results, preview, parent=None):
        super().__init__(parent)
        self.sidebar = sidebar
        self.preview = preview
        self.compact = None
        self._wide_sizes = [158, 240, 420]
        self._narrow_sizes = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        self.categories = QComboBox()
        self.categories.setMinimumHeight(scaled(CATEGORY_MIN_HEIGHT))
        self.categories.setToolTip("按分类、收藏或最近使用筛选")
        self.categories.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.categories.setMinimumContentsLength(8)
        self.categories.currentIndexChanged.connect(sidebar.setCurrentRow)
        layout.addWidget(self.categories)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(5)
        self.splitter.addWidget(sidebar)
        self.splitter.addWidget(results)
        self.splitter.addWidget(preview)
        layout.addWidget(self.splitter, 1)

    def sync_categories(self, entries, selected_row):
        self.categories.blockSignals(True)
        self.categories.clear()
        for entry in entries:
            label = f"{entry.label}  ({entry.count})"
            self.categories.addItem(label, entry.key)
        self.categories.setCurrentIndex(selected_row)
        self.categories.blockSignals(False)

    def sync_selection(self, row):
        self.categories.blockSignals(True)
        self.categories.setCurrentIndex(row)
        self.categories.blockSignals(False)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        compact = self.width() < self.BREAKPOINT
        if compact == self.compact:
            return
        if self.compact is True:
            self._narrow_sizes = self.splitter.sizes()
        elif self.compact is False:
            self._wide_sizes = self.splitter.sizes()
        self.compact = compact
        self.sidebar.setVisible(not compact)
        self.categories.setVisible(compact)
        self.splitter.setOrientation(Qt.Vertical if compact else Qt.Horizontal)
        self.preview.layout().setContentsMargins(0 if compact else 10, 4 if compact else 0, 0, 0)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 2 if compact else 0)
        self.splitter.setStretchFactor(2, 3 if compact else 1)
        if compact:
            sizes = self._narrow_sizes or [0, int(self.height() * .40), int(self.height() * .60)]
        else:
            sizes = self._wide_sizes
        self.splitter.setSizes(sizes)
        self.compact_changed.emit(compact)
