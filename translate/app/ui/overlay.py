from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets
from app.config.runtime_config import get_config


class OverlayWindow(QtWidgets.QWidget):
    def __init__(self, font_point_size: int = 28, bg_opacity: float = 0.0) -> None:
        super().__init__(None, QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.Tool)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
        self.setWindowFlag(QtCore.Qt.WindowDoesNotAcceptFocus, True)

        self._text = ""
        self._font_point_size = font_point_size
        self._bg_opacity = max(0.0, min(1.0, bg_opacity))

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(8000)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.clear_text)

        # Initial size to bottom center third
        self.apply_config()

        # Make mouse click-through on Windows if desired
        try:
            import ctypes
            hwnd = self.winId().__int__()
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x80000
            WS_EX_TRANSPARENT = 0x20
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT)
        except Exception:
            pass

    def set_font_size(self, pt: int) -> None:
        self._font_point_size = max(10, min(96, pt))
        self.update()

    def set_bg_opacity(self, opacity: float) -> None:
        self._bg_opacity = max(0.0, min(1.0, opacity))
        self.update()

    def show_text(self, text: str) -> None:
        self._text = text.strip()
        if not self.isVisible():
            self.show()
        self.update()
        self._timer.start()

    def clear_text(self) -> None:
        self._text = ""
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: D401
        painter = QtGui.QPainter(self)
        painter.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.TextAntialiasing)

        if self._text:
            rect = self.rect().adjusted(8, 8, -8, -8)
            if self._bg_opacity > 0:
                bg_color = QtGui.QColor(0, 0, 0)
                bg_color.setAlphaF(self._bg_opacity)
                painter.setBrush(bg_color)
                painter.setPen(QtCore.Qt.NoPen)
                painter.drawRoundedRect(rect, 12, 12)

            # draw text centered, wrap
            try:
                color = QtGui.QColor(get_config().overlay.color_hex)
            except Exception:
                color = QtGui.QColor(255, 255, 255)
            pen = QtGui.QPen(color)
            painter.setPen(pen)
            font = painter.font()
            try:
                font.setPointSize(int(get_config().overlay.font_size))
            except Exception:
                font.setPointSize(self._font_point_size)
            font.setBold(True)
            painter.setFont(font)
            flags = QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap
            painter.drawText(rect, flags, self._text)

    def apply_config(self) -> None:
        cfg = get_config().overlay
        desktop = QtGui.QGuiApplication.primaryScreen().availableGeometry()
        width = int(desktop.width() * cfg.width_pct)
        height = int(desktop.height() * cfg.height_pct)
        x = int(desktop.width() * cfg.x_pct)
        y = int(desktop.height() * cfg.y_pct)
        self.setGeometry(x, y, width, height)
        try:
            self.set_font_size(int(cfg.font_size))
        except Exception:
            pass
        try:
            self.set_bg_opacity(float(cfg.bg_opacity))
        except Exception:
            pass


