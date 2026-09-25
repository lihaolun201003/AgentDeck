"""可复用的自定义控件：搜索框、可拖动标题栏、列表绘制委托。"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QLineEdit,
    QListWidget,
    QStyle,
    QStyledItemDelegate,
    QWidget,
)

from .theme import (
    ACCENT,
    BG_HOVER,
    BG_SELECTED,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    current_font_size,
    scaled,
)

#: 默认字号下的行高；实际行高取它与字体度量的较大值，字号放大时不会重叠。
PROMPT_ITEM_HEIGHT = 44
SIDEBAR_ITEM_HEIGHT = 26
ICON_SIZE = 32


def _item_font(option) -> QFont:
    """列表项字体。

    QSS 只设了 ``font-size`` 的像素值时 ``option.font`` 依然有效；万一拿不到
    字号，就退回当前界面字号，避免画出 0 号字。
    """
    font = QFont(option.font)
    if font.pixelSize() <= 0 and font.pointSizeF() <= 0:
        font.setPixelSize(current_font_size())
    return font


def _subtitle_font(title_font: QFont) -> QFont:
    """副标题字体：比标题小一点，但不小于 8px。"""
    font = QFont(title_font)
    size = font.pixelSize() if font.pixelSize() > 0 else current_font_size()
    font.setPixelSize(max(8, size - scaled(2)))
    return font


def _sidebar_height(option) -> int:
    metrics = QFontMetrics(_item_font(option))
    return max(scaled(SIDEBAR_ITEM_HEIGHT), metrics.height() + scaled(8))


def _prompt_item_height(option) -> int:
    title_font = _item_font(option)
    title_metrics = QFontMetrics(title_font)
    sub_metrics = QFontMetrics(_subtitle_font(title_font))
    return max(scaled(PROMPT_ITEM_HEIGHT), title_metrics.height() + sub_metrics.height() + scaled(8))


def search_icon() -> QIcon:
    """程序化绘制放大镜图标，避免附带图片资源。"""
    pixmap = QPixmap(ICON_SIZE, ICON_SIZE)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor(TEXT_SECONDARY))
    pen.setWidthF(2.6)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.drawEllipse(QRectF(5.5, 5.5, 14.0, 14.0))
    painter.drawLine(QPointF(18.5, 18.5), QPointF(25.5, 25.5))
    painter.end()

    return QIcon(pixmap)


class SearchLineEdit(QLineEdit):
    """搜索框：把上下键与回车转发给结果列表。"""

    navigate_next = Signal()
    navigate_previous = Signal()
    submitted = Signal()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt 命名风格
        key = event.key()
        if key in (Qt.Key_Down, Qt.Key_Up) and not (
            event.modifiers() & (Qt.ControlModifier | Qt.AltModifier)
        ):
            if key == Qt.Key_Down:
                self.navigate_next.emit()
            else:
                self.navigate_previous.emit()
            event.accept()
            return
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self.submitted.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class PromptListWidget(QListWidget):
    """结果列表：回车触发"复制"，上下键在列表内移动。"""

    submitted = Signal()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt 命名风格
        key = event.key()
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self.submitted.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class DragBar(QWidget):
    """标题栏：按住任意空白处可以拖动无边框窗口。"""

    def __init__(self, window: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window = window
        self._offset: QPoint | None = None

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt 命名风格
        if event.button() == Qt.LeftButton:
            self._offset = (
                event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt 命名风格
        if self._offset is not None and event.buttons() & Qt.LeftButton:
            self._window.move(event.globalPosition().toPoint() - self._offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt 命名风格
        self._offset = None
        super().mouseReleaseEvent(event)


@dataclass(frozen=True)
class SidebarEntry:
    """侧边栏的一行。``key`` 为 None 表示"全部"。"""

    key: str | None
    label: str
    count: int


class SidebarDelegate(QStyledItemDelegate):
    """侧边栏绘制：左侧名称，右侧数量。"""

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 - Qt 命名风格
        return QSize(option.rect.width(), _sidebar_height(option))

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = option.rect.adjusted(6, 1, -6, -1)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)

        if selected:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(BG_SELECTED))
            painter.drawRoundedRect(rect, 4, 4)
        elif hovered:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(BG_HOVER))
            painter.drawRoundedRect(rect, 4, 4)

        font = _item_font(option)
        painter.setFont(font)
        metrics = QFontMetrics(font)

        count = index.data(Qt.UserRole + 1)
        count_text = str(count) if count else ""
        count_width = metrics.horizontalAdvance(count_text) + 8 if count_text else 0

        text_left = rect.left() + 8
        text_right = rect.right() - 8 - count_width

        label = metrics.elidedText(str(index.data(Qt.DisplayRole)), Qt.ElideRight, max(10, text_right - text_left))
        painter.setPen(QColor(TEXT_PRIMARY if selected else TEXT_SECONDARY))
        painter.drawText(
            text_left, rect.top(), text_right - text_left, rect.height(),
            Qt.AlignLeft | Qt.AlignVCenter, label,
        )

        if count_text:
            painter.setPen(QColor(TEXT_MUTED))
            painter.drawText(
                text_right, rect.top(), count_width, rect.height(),
                Qt.AlignRight | Qt.AlignVCenter, count_text,
            )

        painter.restore()


class PromptItemDelegate(QStyledItemDelegate):
    """结果列表绘制：第一行名称，第二行分类与变量提示。"""

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 - Qt 命名风格
        return QSize(option.rect.width(), _prompt_item_height(option))

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = option.rect.adjusted(6, 2, -6, -2)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)

        if selected:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(BG_SELECTED))
            painter.drawRoundedRect(rect, 5, 5)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(ACCENT))
            painter.drawRoundedRect(rect.left(), rect.top() + 4, 2, rect.height() - 8, 1, 1)
        elif hovered:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(BG_HOVER))
            painter.drawRoundedRect(rect, 5, 5)

        name = str(index.data(Qt.DisplayRole) or "")
        subtitle = str(index.data(Qt.UserRole) or "")
        has_variables = bool(index.data(Qt.UserRole + 1))

        title_font = _item_font(option)
        title_metrics = QFontMetrics(title_font)
        subtitle_font = _subtitle_font(title_font)
        sub_metrics = QFontMetrics(subtitle_font)

        # 两行文本按各自字体高度排布，中间剩余空间上下均分。
        title_height = title_metrics.height()
        subtitle_height = sub_metrics.height()
        slack = max(0, rect.height() - title_height - subtitle_height)
        top = rect.top() + slack // 2
        left = rect.left() + 10
        text_width = max(10, rect.width() - 20)

        painter.setFont(title_font)
        painter.setPen(QColor(TEXT_PRIMARY))
        painter.drawText(
            left, top, text_width, title_height,
            Qt.AlignLeft | Qt.AlignVCenter,
            title_metrics.elidedText(name, Qt.ElideRight, text_width),
        )

        badge = "{{ }} 变量" if has_variables else ""
        badge_width = sub_metrics.horizontalAdvance(badge) + 12 if badge else 0

        painter.setFont(subtitle_font)
        painter.setPen(QColor(TEXT_MUTED))
        available = max(10, rect.width() - 20 - badge_width)
        painter.drawText(
            left, top + title_height, available, subtitle_height,
            Qt.AlignLeft | Qt.AlignVCenter,
            sub_metrics.elidedText(subtitle, Qt.ElideRight, available),
        )

        if badge:
            badge_rect = rect.adjusted(rect.width() - badge_width - 4, 0, -6, 0)
            badge_rect.setTop(top + title_height)
            badge_rect.setHeight(subtitle_height)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(BG_SELECTED))
            painter.drawRoundedRect(badge_rect, 3, 3)
            painter.setPen(QColor(ACCENT))
            painter.drawText(badge_rect, Qt.AlignCenter, badge)

        painter.restore()


__all__ = [
    "DragBar",
    "PromptItemDelegate",
    "PromptListWidget",
    "SearchLineEdit",
    "SidebarDelegate",
    "SidebarEntry",
    "search_icon",
]
