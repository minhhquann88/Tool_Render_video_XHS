import sys

from PySide6.QtWidgets import QApplication

from app.config import APP_NAME, ensure_dirs
from app.ui.main_window import MainWindow
from app.ui.theme import apply_theme
from app.ui.widgets.common import NoWheelFilter


def main() -> int:
    ensure_dirs()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("MQ")
    apply_theme(app)
    no_wheel = NoWheelFilter(app)
    app.installEventFilter(no_wheel)

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
