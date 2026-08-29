import os
import time

import psutil

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.database import (
    connect_database,
    get_database_path,
    get_index_counts,
)


class DashboardPage(QWidget):
    navigate_requested = Signal(int)

    def __init__(self):
        super().__init__()

        self.database_refresh_counter = 0

        self.setup_ui()
        self.setup_timer()

        self.update_system_stats()
        self.update_index_stats()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        layout.setContentsMargins(
            46,
            40,
            46,
            40,
        )

        layout.setSpacing(24)

        # -----------------------------------------------------
        # Heading
        # -----------------------------------------------------

        title = QLabel("Dashboard")
        title.setObjectName("pageTitle")

        description = QLabel(
            "A quick overview of your system and SysDeck data."
        )

        description.setObjectName(
            "pageDescription"
        )

        layout.addWidget(title)
        layout.addWidget(description)

        # -----------------------------------------------------
        # System overview
        # -----------------------------------------------------

        system_label = QLabel(
            "System Overview"
        )

        system_label.setObjectName(
            "sectionTitle"
        )

        layout.addWidget(
            system_label
        )

        system_grid = QGridLayout()

        system_grid.setHorizontalSpacing(18)
        system_grid.setVerticalSpacing(18)

        for column in range(4):
            system_grid.setColumnStretch(
                column,
                1,
            )

        self.cpu_value = QLabel("--")
        self.memory_value = QLabel("--")
        self.process_value = QLabel("--")
        self.uptime_value = QLabel("--")

        self.cpu_detail = QLabel(
            "Current usage"
        )

        self.memory_detail = QLabel(
            "Current usage"
        )

        self.process_detail = QLabel(
            "Running processes"
        )

        self.uptime_detail = QLabel(
            "Since last boot"
        )

        system_grid.addWidget(
            self.create_metric_card(
                "CPU",
                self.cpu_value,
                self.cpu_detail,
            ),
            0,
            0,
        )

        system_grid.addWidget(
            self.create_metric_card(
                "Memory",
                self.memory_value,
                self.memory_detail,
            ),
            0,
            1,
        )

        system_grid.addWidget(
            self.create_metric_card(
                "Processes",
                self.process_value,
                self.process_detail,
            ),
            0,
            2,
        )

        system_grid.addWidget(
            self.create_metric_card(
                "Uptime",
                self.uptime_value,
                self.uptime_detail,
            ),
            0,
            3,
        )

        layout.addLayout(
            system_grid
        )

        # -----------------------------------------------------
        # SysDeck overview
        # -----------------------------------------------------

        sysdeck_label = QLabel(
            "SysDeck Overview"
        )

        sysdeck_label.setObjectName(
            "sectionTitle"
        )

        layout.addWidget(
            sysdeck_label
        )

        sysdeck_grid = QGridLayout()

        sysdeck_grid.setHorizontalSpacing(18)
        sysdeck_grid.setVerticalSpacing(18)

        for column in range(4):
            sysdeck_grid.setColumnStretch(
                column,
                1,
            )

        self.drive_value = QLabel("--")
        self.indexed_value = QLabel("--")
        self.locations_value = QLabel("--")
        self.database_value = QLabel("--")

        self.drive_detail = QLabel(
            "System drive"
        )

        self.indexed_detail = QLabel(
            "Indexed files"
        )

        self.locations_detail = QLabel(
            "Indexed locations"
        )

        self.database_detail = QLabel(
            "Local index database"
        )

        sysdeck_grid.addWidget(
            self.create_metric_card(
                "Storage",
                self.drive_value,
                self.drive_detail,
            ),
            0,
            0,
        )

        sysdeck_grid.addWidget(
            self.create_metric_card(
                "Indexed Files",
                self.indexed_value,
                self.indexed_detail,
            ),
            0,
            1,
        )

        sysdeck_grid.addWidget(
            self.create_metric_card(
                "Locations",
                self.locations_value,
                self.locations_detail,
            ),
            0,
            2,
        )

        sysdeck_grid.addWidget(
            self.create_metric_card(
                "Index Size",
                self.database_value,
                self.database_detail,
            ),
            0,
            3,
        )

        layout.addLayout(
            sysdeck_grid
        )

        # -----------------------------------------------------
        # Quick actions
        # -----------------------------------------------------

        actions_label = QLabel(
            "Quick Actions"
        )

        actions_label.setObjectName(
            "sectionTitle"
        )

        layout.addWidget(
            actions_label
        )

        action_grid = QGridLayout()

        action_grid.setHorizontalSpacing(14)
        action_grid.setVerticalSpacing(14)

        actions = [
            (
                "Performance",
                "View live system activity",
                1,
            ),
            (
                "Storage",
                "Analyze drives and folders",
                3,
            ),
            (
                "Search",
                "Find indexed files",
                4,
            ),
            (
                "Files",
                "Find and clean duplicates",
                5,
            ),
        ]

        for column, (
            name,
            description,
            page_index,
        ) in enumerate(actions):

            button = self.create_action_button(
                name,
                description,
                page_index,
            )

            action_grid.addWidget(
                button,
                0,
                column,
            )

            action_grid.setColumnStretch(
                column,
                1,
            )

        layout.addLayout(
            action_grid
        )

        layout.addStretch()

    def create_metric_card(
        self,
        title,
        value,
        detail,
    ):
        card = QWidget()

        card.setObjectName(
            "metricCard"
        )

        card_layout = QVBoxLayout(
            card
        )

        card_layout.setContentsMargins(
            20,
            18,
            20,
            18,
        )

        card_layout.setSpacing(
            8
        )

        title_label = QLabel(
            title
        )

        title_label.setObjectName(
            "metricTitle"
        )

        value.setObjectName(
            "metricValue"
        )

        detail.setObjectName(
            "metricDetail"
        )

        card_layout.addWidget(
            title_label
        )

        card_layout.addWidget(
            value
        )

        card_layout.addWidget(
            detail
        )

        return card

    def create_action_button(
        self,
        title,
        description,
        page_index,
    ):
        button = QPushButton(
            f"{title}\n{description}"
        )

        button.setObjectName(
            "dashboardAction"
        )

        button.setMinimumHeight(
            78
        )

        button.clicked.connect(
            lambda checked=False, index=page_index:
            self.navigate_requested.emit(
                index
            )
        )

        return button

    # ========================================================
    # Timers
    # ========================================================

    def setup_timer(self):
        self.timer = QTimer(
            self
        )

        self.timer.timeout.connect(
            self.update_dashboard
        )

        self.timer.start(
            1000
        )

    def update_dashboard(self):
        self.update_system_stats()

        self.database_refresh_counter += 1

        if self.database_refresh_counter >= 5:
            self.update_index_stats()

            self.database_refresh_counter = 0

    # ========================================================
    # System information
    # ========================================================

    def update_system_stats(self):
        cpu = psutil.cpu_percent(
            interval=None
        )

        memory = psutil.virtual_memory()

        process_count = len(
            psutil.pids()
        )

        uptime = (
            time.time()
            - psutil.boot_time()
        )

        memory_used = (
            memory.used / (1024 ** 3)
        )

        memory_total = (
            memory.total / (1024 ** 3)
        )

        self.cpu_value.setText(
            f"{cpu:.0f}%"
        )

        self.memory_value.setText(
            f"{memory.percent:.0f}%"
        )

        self.memory_detail.setText(
            f"{memory_used:.1f} / "
            f"{memory_total:.1f} GB"
        )

        self.process_value.setText(
            f"{process_count:,}"
        )

        self.uptime_value.setText(
            self.format_uptime(
                uptime
            )
        )

        system_drive = os.getenv(
            "SystemDrive",
            "C:",
        )

        drive_path = (
            system_drive + "\\"
        )

        try:
            usage = psutil.disk_usage(
                drive_path
            )

            self.drive_value.setText(
                f"{usage.percent:.0f}%"
            )

            self.drive_detail.setText(
                f"{self.format_size(usage.free)} free"
            )

        except OSError:
            self.drive_value.setText(
                "--"
            )

            self.drive_detail.setText(
                "System drive unavailable"
            )

    # ========================================================
    # SysDeck database information
    # ========================================================

    def update_index_stats(self):
        connection = connect_database()

        try:
            (
                file_count,
                root_count,
            ) = get_index_counts(
                connection
            )

        finally:
            connection.close()

        self.indexed_value.setText(
            f"{file_count:,}"
        )

        self.locations_value.setText(
            f"{root_count:,}"
        )

        database_path = (
            get_database_path()
        )

        try:
            database_size = os.path.getsize(
                database_path
            )

        except OSError:
            database_size = 0

        self.database_value.setText(
            self.format_size(
                database_size
            )
        )

    # ========================================================
    # Formatting
    # ========================================================

    @staticmethod
    def format_uptime(
        seconds,
    ):
        seconds = int(
            seconds
        )

        days, remainder = divmod(
            seconds,
            86400,
        )

        hours, remainder = divmod(
            remainder,
            3600,
        )

        minutes, _ = divmod(
            remainder,
            60,
        )

        if days:
            return (
                f"{days}d {hours}h"
            )

        if hours:
            return (
                f"{hours}h {minutes}m"
            )

        return (
            f"{minutes}m"
        )

    @staticmethod
    def format_size(
        size,
    ):
        if size >= 1024 ** 4:
            return (
                f"{size / (1024 ** 4):.2f} TB"
            )

        if size >= 1024 ** 3:
            return (
                f"{size / (1024 ** 3):.1f} GB"
            )

        if size >= 1024 ** 2:
            return (
                f"{size / (1024 ** 2):.1f} MB"
            )

        if size >= 1024:
            return (
                f"{size / 1024:.1f} KB"
            )

        return (
            f"{size} B"
        )