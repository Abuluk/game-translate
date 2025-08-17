from __future__ import annotations

from PySide6 import QtWidgets, QtGui


class OverlaySettingsDialog(QtWidgets.QDialog):
    def __init__(self, *, font_size: int, color_hex: str, bg_opacity: float,
                 x_pct: float, y_pct: float, width_pct: float, height_pct: float,
                 parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("字幕设置")
        layout = QtWidgets.QFormLayout(self)

        self.spin_font = QtWidgets.QSpinBox()
        self.spin_font.setRange(10, 96)
        self.spin_font.setValue(int(font_size))

        self.edit_color = QtWidgets.QLineEdit(color_hex)
        self.btn_pick = QtWidgets.QPushButton("选择…")
        self.preview = QtWidgets.QLabel()
        self.preview.setFixedSize(32, 18)
        self.preview.setFrameShape(QtWidgets.QFrame.Box)
        self._set_preview(color_hex)
        self.btn_pick.clicked.connect(self._on_pick_color)
        row_color = QtWidgets.QWidget()
        row_hl = QtWidgets.QHBoxLayout(row_color)
        row_hl.setContentsMargins(0, 0, 0, 0)
        row_hl.setSpacing(8)
        row_hl.addWidget(self.edit_color, 1)
        row_hl.addWidget(self.btn_pick)
        row_hl.addWidget(self.preview)
        self.spin_bg = QtWidgets.QDoubleSpinBox(); self.spin_bg.setRange(0.0, 1.0); self.spin_bg.setSingleStep(0.05); self.spin_bg.setValue(float(bg_opacity))
        self.spin_x = QtWidgets.QDoubleSpinBox(); self.spin_x.setRange(0.0, 1.0); self.spin_x.setSingleStep(0.01); self.spin_x.setValue(float(x_pct))
        self.spin_y = QtWidgets.QDoubleSpinBox(); self.spin_y.setRange(0.0, 1.0); self.spin_y.setSingleStep(0.01); self.spin_y.setValue(float(y_pct))
        self.spin_w = QtWidgets.QDoubleSpinBox(); self.spin_w.setRange(0.1, 1.0); self.spin_w.setSingleStep(0.01); self.spin_w.setValue(float(width_pct))
        self.spin_h = QtWidgets.QDoubleSpinBox(); self.spin_h.setRange(0.1, 1.0); self.spin_h.setSingleStep(0.01); self.spin_h.setValue(float(height_pct))

        layout.addRow("字体大小:", self.spin_font)
        layout.addRow("文字颜色(#RRGGBB):", row_color)
        layout.addRow("背景透明度(0-1):", self.spin_bg)
        layout.addRow("X比例:", self.spin_x)
        layout.addRow("Y比例:", self.spin_y)
        layout.addRow("宽度比例:", self.spin_w)
        layout.addRow("高度比例:", self.spin_h)

        btn_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addRow(btn_box)

    def values(self) -> dict:
        return {
            "font_size": int(self.spin_font.value()),
            "color_hex": self.edit_color.text().strip() or "#FFFFFF",
            "bg_opacity": float(self.spin_bg.value()),
            "x_pct": float(self.spin_x.value()),
            "y_pct": float(self.spin_y.value()),
            "width_pct": float(self.spin_w.value()),
            "height_pct": float(self.spin_h.value()),
        }

    def _on_pick_color(self) -> None:
        # Initialize with current text if valid
        init = QtGui.QColor(self.edit_color.text().strip())
        if not init.isValid():
            init = QtGui.QColor("#FFFFFF")
        color = QtWidgets.QColorDialog.getColor(init, self, "选择颜色")
        if color.isValid():
            hexv = color.name(QtGui.QColor.HexRgb).upper()
            self.edit_color.setText(hexv)
            self._set_preview(hexv)

    def _set_preview(self, hexv: str) -> None:
        pal = self.preview.palette()
        pal.setColor(self.preview.backgroundRole(), QtGui.QColor(hexv))
        self.preview.setAutoFillBackground(True)
        self.preview.setPalette(pal)


