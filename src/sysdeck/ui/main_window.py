from PySide6.QtCore import (
    QSettings,
    Qt,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .dashboard_page import DashboardPage
from .files_page import FilesPage
from .performance_page import PerformancePage
from .processes_page import ProcessesPage
from .search_page import SearchPage
from .settings_page import SettingsPage
from .storage_page import StoragePage
from .theme import APP_STYLE


class PlaceholderPage(QWidget):
    def __init__(
        self,
        title,
        description,
    ):
        super().__init__()

        layout = QVBoxLayout(
            self
        )

        layout.setContentsMargins(
            46,
            40,
            46,
            40,
        )

        layout.setSpacing(
            8
        )

        layout.setAlignment(
            Qt.AlignmentFlag.AlignTop
        )

        title_label = QLabel(
            title
        )

        title_label.setObjectName(
            "pageTitle"
        )

        description_label = QLabel(
            description
        )

        description_label.setObjectName(
            "pageDescription"
        )

        layout.addWidget(
            title_label
        )

        layout.addWidget(
            description_label
        )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.settings = QSettings(
            "SysDeck",
            "SysDeck",
        )

        self.setWindowTitle(
            "SysDeck"
        )

        self.resize(
            1200,
            760,
        )

        self.setMinimumSize(
            900,
            600,
        )

        self.setStyleSheet(
            APP_STYLE
        )

        self.nav_buttons = []

        self.button_group = QButtonGroup(
            self
        )

        self.button_group.setExclusive(
            True
        )

        self.setup_ui()

    def setup_ui(self):
        root = QWidget()

        root_layout = QHBoxLayout(
            root
        )

        root_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        root_layout.setSpacing(
            0
        )

        sidebar = self.create_sidebar()

        self.pages = QStackedWidget()

        self.pages.setObjectName(
            "contentArea"
        )

        self.create_pages()

        root_layout.addWidget(
            sidebar
        )

        root_layout.addWidget(
            self.pages,
            1,
        )

        self.setCentralWidget(
            root
        )

        self.restore_start_page()

    # ========================================================
    # Sidebar
    # ========================================================

    def create_sidebar(self):
        sidebar = QFrame()

        sidebar.setObjectName(
            "sidebar"
        )

        sidebar.setFixedWidth(
            220
        )

        layout = QVBoxLayout(
            sidebar
        )

        layout.setContentsMargins(
            14,
            22,
            14,
            14,
        )

        layout.setSpacing(
            4
        )

        title = QLabel(
            "SysDeck"
        )

        title.setObjectName(
            "appTitle"
        )

        layout.addWidget(
            title
        )

        layout.addSpacing(
            18
        )

        navigation = [
            ("Dashboard", 0),
            ("Performance", 1),
            ("Processes", 2),
            ("Storage", 3),
            ("Search", 4),
            ("Files", 5),
            ("Vault", 6),
        ]

        for name, index in navigation:
            layout.addWidget(
                self.create_nav_button(
                    name,
                    index,
                )
            )

        spacer = QWidget()

        spacer.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding,
        )

        layout.addWidget(
            spacer
        )

        layout.addWidget(
            self.create_nav_button(
                "Settings",
                7,
            )
        )

        return sidebar

    def create_nav_button(
        self,
        name,
        page_index,
    ):
        button = QPushButton(
            name
        )

        button.setObjectName(
            "navButton"
        )

        button.setCheckable(
            True
        )

        button.setCursor(
            Qt.CursorShape.PointingHandCursor
        )

        button.clicked.connect(
            lambda checked=False, index=page_index:
            self.switch_page(
                index
            )
        )

        self.button_group.addButton(
            button
        )

        self.nav_buttons.append(
            button
        )

        return button

    # ========================================================
    # Pages
    # ========================================================

    def create_pages(self):
        self.dashboard_page = (
            DashboardPage()
        )

        self.performance_page = (
            PerformancePage()
        )

        self.processes_page = (
            ProcessesPage()
        )

        self.storage_page = (
            StoragePage()
        )

        self.search_page = (
            SearchPage()
        )

        self.files_page = (
            FilesPage()
        )

        self.vault_page = PlaceholderPage(
            "Vault",
            "Securely store local credentials and private information.",
        )

        self.settings_page = (
            SettingsPage()
        )

        self.dashboard_page.navigate_requested.connect(
            self.switch_page
        )

        self.settings_page.reindex_requested.connect(
            self.handle_reindex_requested
        )

        self.settings_page.index_changed.connect(
            self.handle_index_changed
        )

        self.pages.addWidget(
            self.dashboard_page
        )

        self.pages.addWidget(
            self.performance_page
        )

        self.pages.addWidget(
            self.processes_page
        )

        self.pages.addWidget(
            self.storage_page
        )

        self.pages.addWidget(
            self.search_page
        )

        self.pages.addWidget(
            self.files_page
        )

        self.pages.addWidget(
            self.vault_page
        )

        self.pages.addWidget(
            self.settings_page
        )

    # ========================================================
    # Navigation
    # ========================================================

    def restore_start_page(self):
        remember = self.settings.value(
            "navigation/remember_last_page",
            False,
            type=bool,
        )

        page_index = 0

        if remember:
            try:
                page_index = int(
                    self.settings.value(
                        "navigation/last_page",
                        0,
                    )
                )

            except (
                TypeError,
                ValueError,
            ):
                page_index = 0

        if not (
            0
            <= page_index
            < self.pages.count()
        ):
            page_index = 0

        self.switch_page(
            page_index
        )

    def switch_page(
        self,
        index,
    ):
        if not (
            0
            <= index
            < self.pages.count()
        ):
            return

        self.pages.setCurrentIndex(
            index
        )

        if (
            0
            <= index
            < len(self.nav_buttons)
        ):
            self.nav_buttons[
                index
            ].setChecked(
                True
            )

        remember = self.settings.value(
            "navigation/remember_last_page",
            False,
            type=bool,
        )

        if remember:
            self.settings.setValue(
                "navigation/last_page",
                index,
            )

    # ========================================================
    # Settings integration
    # ========================================================

    def handle_reindex_requested(
        self,
        root_path,
    ):
        self.search_page.start_index(
            root_path
        )

        self.switch_page(
            4
        )

    def handle_index_changed(self):
        # Dashboard
        self.dashboard_page.update_index_stats()

        # Search
        self.search_page.refresh_filter_options()
        self.search_page.refresh_index_status()
        self.search_page.perform_search()

        # Files
        self.files_page.refresh_index_info()