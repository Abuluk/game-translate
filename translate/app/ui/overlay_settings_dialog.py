from __future__ import annotations

from PySide6 import QtWidgets


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
        self.spin_bg = QtWidgets.QDoubleSpinBox(); self.spin_bg.setRange(0.0, 1.0); self.spin_bg.setSingleStep(0.05); self.spin_bg.setValue(float(bg_opacity))
        self.spin_x = QtWidgets.QDoubleSpinBox(); self.spin_x.setRange(0.0, 1.0); self.spin_x.setSingleStep(0.01); self.spin_x.setValue(float(x_pct))
        self.spin_y = QtWidgets.QDoubleSpinBox(); self.spin_y.setRange(0.0, 1.0); self.spin_y.setSingleStep(0.01); self.spin_y.setValue(float(y_pct))
        self.spin_w = QtWidgets.QDoubleSpinBox(); self.spin_w.setRange(0.1, 1.0); self.spin_w.setSingleStep(0.01); self.spin_w.setValue(float(width_pct))
        self.spin_h = QtWidgets.QDoubleSpinBox(); self.spin_h.setRange(0.1, 1.0); self.spin_h.setSingleStep(0.01); self.spin_h.setValue(float(height_pct))

        layout.addRow("字体大小:", self.spin_font)
        layout.addRow("文字颜色(#RRGGBB):", self.edit_color)
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


