from PySide6.QtCore import Qt
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
from .performance_page import PerformancePage

from .theme import APP_STYLE


class PlaceholderPage(QWidget):
    def __init__(self, title: str, description: str):
        super().__init__()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(46, 40, 46, 40)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        title_label = QLabel(title)
        title_label.setObjectName("pageTitle")

        description_label = QLabel(description)
        description_label.setObjectName("pageDescription")

        layout.addWidget(title_label)
        layout.addWidget(description_label)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("SysDeck")
        self.resize(1200, 760)
        self.setMinimumSize(900, 600)

        self.setStyleSheet(APP_STYLE)

        self.nav_buttons = []
        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)

        self.setup_ui()

    def setup_ui(self):
        root = QWidget()
        root_layout = QHBoxLayout(root)

        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        sidebar = self.create_sidebar()

        self.pages = QStackedWidget()
        self.pages.setObjectName("contentArea")

        self.create_pages()

        root_layout.addWidget(sidebar)
        root_layout.addWidget(self.pages, 1)

        self.setCentralWidget(root)

        self.nav_buttons[0].setChecked(True)
        self.pages.setCurrentIndex(0)

    def create_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 22, 14, 14)
        layout.setSpacing(4)

        title = QLabel("SysDeck")
        title.setObjectName("appTitle")

        layout.addWidget(title)
        layout.addSpacing(18)

        navigation = [
            ("Dashboard", 0),
            ("Performance", 1),
            ("Storage", 2),
            ("Search", 3),
            ("Files", 4),
            ("Vault", 5),
        ]

        for name, page_index in navigation:
            button = self.create_nav_button(name, page_index)
            layout.addWidget(button)

        spacer = QWidget()
        spacer.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding,
        )

        layout.addWidget(spacer)

        settings_button = self.create_nav_button("Settings", 6)
        layout.addWidget(settings_button)

        return sidebar

    def create_nav_button(self, name, page_index):
        button = QPushButton(name)

        button.setObjectName("navButton")
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)

        button.clicked.connect(
            lambda checked=False, index=page_index: self.switch_page(index)
        )

        self.button_group.addButton(button)
        self.nav_buttons.append(button)

        return button

    def create_pages(self):
        self.pages.addWidget(
            PlaceholderPage(
                "Dashboard",
                "A quick overview of your system.",
            )
        )

        self.pages.addWidget(
            PerformancePage()
        )

        self.pages.addWidget(
            PlaceholderPage(
                "Storage",
                "Analyze how space is being used across your drives.",
            )
        )

        self.pages.addWidget(
            PlaceholderPage(
                "Search",
                "Find indexed files quickly across your computer.",
            )
        )

        self.pages.addWidget(
            PlaceholderPage(
                "Files",
                "Find duplicates and organize files.",
            )
        )

        self.pages.addWidget(
            PlaceholderPage(
                "Vault",
                "Securely store local credentials and private information.",
            )
        )

        self.pages.addWidget(
            PlaceholderPage(
                "Settings",
                "Configure SysDeck preferences and behavior.",
            )
        )
    def switch_page(self, index):
        self.pages.setCurrentIndex(index)