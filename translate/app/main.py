import sys
import os
from pathlib import Path
from PySide6 import QtWidgets

# Allow running this file directly (python app/main.py) by adding project root to sys.path
try:
    from app.ui.main_window import MainWindow
except ModuleNotFoundError:
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))
    from app.ui.main_window import MainWindow


def main() -> None:
    # Ensure working directory is project root when launched as module
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()


