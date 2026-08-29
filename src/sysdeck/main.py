import ctypes
import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .core.paths import resource_path
from .ui.main_window import MainWindow
from .version import APP_NAME, APP_VERSION


def configure_windows_app_identity():
    """
    Give SysDeck its own Windows application identity.

    This helps Windows use the correct taskbar icon
    instead of grouping it under Python.
    """

    if sys.platform != "win32":
        return

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "SysDeck.SysDeck"
        )

    except Exception:
        pass


def main():
    configure_windows_app_identity()

    app = QApplication(
        sys.argv
    )

    app.setApplicationName(
        APP_NAME
    )

    app.setApplicationVersion(
        APP_VERSION
    )

    app.setOrganizationName(
        APP_NAME
    )

    icon_path = resource_path(
        os.path.join(
            "assets",
            "sysdeck_icon.png",
        )
    )

    if os.path.exists(
        icon_path
    ):
        app.setWindowIcon(
            QIcon(
                icon_path
            )
        )

    window = MainWindow()

    window.show()

    sys.exit(
        app.exec()
    )


if __name__ == "__main__":
    main()