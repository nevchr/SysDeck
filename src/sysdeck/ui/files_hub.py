from PySide6.QtWidgets import (
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .files_page import FilesPage
from .organizer_page import OrganizerPage


class FilesHub(QWidget):
    def __init__(self):
        super().__init__()

        layout = QVBoxLayout(
            self
        )

        layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        layout.setSpacing(
            0
        )

        self.tabs = QTabWidget()

        self.tabs.setObjectName(
            "filesTabs"
        )

        self.duplicates_page = (
            FilesPage()
        )

        self.organizer_page = (
            OrganizerPage()
        )

        self.tabs.addTab(
            self.duplicates_page,
            "Duplicates",
        )

        self.tabs.addTab(
            self.organizer_page,
            "Organizer",
        )

        layout.addWidget(
            self.tabs
        )

    def refresh_index_info(self):
        self.duplicates_page.refresh_index_info()