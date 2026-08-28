import os

from PySide6.QtCore import (
    QObject,
    QSettings,
    QThread,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.database import (
    connect_database,
    get_database_path,
)


# ============================================================
# Background index maintenance
# ============================================================

class IndexMaintenanceWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        action,
        root_path=None,
    ):
        super().__init__()

        self.action = action
        self.root_path = root_path

    @Slot()
    def run(self):
        connection = None

        try:
            connection = connect_database()

            if self.action == "remove_root":
                if not self.root_path:
                    raise ValueError(
                        "No indexed location was selected."
                    )

                removed = connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM files
                    WHERE root_path = ?
                    """,
                    (self.root_path,),
                ).fetchone()[0]

                connection.execute(
                    """
                    DELETE FROM files
                    WHERE root_path = ?
                    """,
                    (self.root_path,),
                )

            elif self.action == "clear_all":
                removed = connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM files
                    """
                ).fetchone()[0]

                connection.execute(
                    """
                    DELETE FROM files
                    """
                )

            else:
                raise ValueError(
                    f"Unknown maintenance action: {self.action}"
                )

            connection.commit()

            # Try to reclaim unused database space.
            # Failure here should not undo the index change.
            try:
                connection.execute(
                    "PRAGMA wal_checkpoint(TRUNCATE)"
                )

                connection.execute(
                    "VACUUM"
                )

            except Exception:
                pass

            self.finished.emit(
                {
                    "action": self.action,
                    "root_path": self.root_path,
                    "removed": removed,
                }
            )

        except Exception as error:
            self.failed.emit(
                str(error)
            )

        finally:
            if connection is not None:
                connection.close()


# ============================================================
# Settings page
# ============================================================

class SettingsPage(QWidget):
    index_changed = Signal()
    reindex_requested = Signal(str)

    def __init__(self):
        super().__init__()

        self.settings = QSettings(
            "SysDeck",
            "SysDeck",
        )

        self.maintenance_thread = None
        self.maintenance_worker = None

        self.setup_ui()
        self.refresh_index_info()
        self.refresh_remember_page_button()

        app = QApplication.instance()

        if app is not None:
            app.aboutToQuit.connect(
                self.shutdown_worker
            )

    # ========================================================
    # UI
    # ========================================================

    def setup_ui(self):
        layout = QVBoxLayout(self)

        layout.setContentsMargins(
            46,
            40,
            46,
            40,
        )

        layout.setSpacing(
            16
        )

        # ----------------------------------------------------
        # Header
        # ----------------------------------------------------

        title = QLabel(
            "Settings"
        )

        title.setObjectName(
            "pageTitle"
        )

        description = QLabel(
            "Manage SysDeck data, indexed locations, and application behavior."
        )

        description.setObjectName(
            "pageDescription"
        )

        layout.addWidget(
            title
        )

        layout.addWidget(
            description
        )

        # ----------------------------------------------------
        # Index management heading
        # ----------------------------------------------------

        index_title = QLabel(
            "Index Management"
        )

        index_title.setObjectName(
            "sectionTitle"
        )

        layout.addWidget(
            index_title
        )

        # ----------------------------------------------------
        # Summary cards
        # ----------------------------------------------------

        summary_grid = QGridLayout()

        summary_grid.setHorizontalSpacing(
            18
        )

        for column in range(3):
            summary_grid.setColumnStretch(
                column,
                1,
            )

        self.indexed_files_value = QLabel(
            "0"
        )

        self.locations_value = QLabel(
            "0"
        )

        self.database_size_value = QLabel(
            "0 B"
        )

        summary_grid.addWidget(
            self.create_summary_card(
                "Indexed Files",
                self.indexed_files_value,
            ),
            0,
            0,
        )

        summary_grid.addWidget(
            self.create_summary_card(
                "Indexed Locations",
                self.locations_value,
            ),
            0,
            1,
        )

        summary_grid.addWidget(
            self.create_summary_card(
                "Database Size",
                self.database_size_value,
            ),
            0,
            2,
        )

        layout.addLayout(
            summary_grid
        )

        # ----------------------------------------------------
        # Database path
        # ----------------------------------------------------

        self.database_path_label = QLabel()

        self.database_path_label.setObjectName(
            "searchStatus"
        )

        self.database_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        layout.addWidget(
            self.database_path_label
        )

        # ----------------------------------------------------
        # Indexed locations table
        # ----------------------------------------------------

        self.locations_table = QTableWidget(
            0,
            3,
        )

        self.locations_table.setObjectName(
            "searchResults"
        )

        self.locations_table.setHorizontalHeaderLabels(
            [
                "Indexed Location",
                "Files",
                "Indexed Size",
            ]
        )

        self.locations_table.verticalHeader().hide()

        self.locations_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )

        self.locations_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )

        self.locations_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )

        self.locations_table.setAlternatingRowColors(
            True
        )

        self.locations_table.setShowGrid(
            False
        )

        self.locations_table.itemSelectionChanged.connect(
            self.update_index_action_buttons
        )

        self.locations_table.itemDoubleClicked.connect(
            lambda _item:
            self.open_selected_location()
        )

        header = (
            self.locations_table
            .horizontalHeader()
        )

        header.setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.Stretch,
        )

        header.setSectionResizeMode(
            1,
            QHeaderView.ResizeMode.ResizeToContents,
        )

        header.setSectionResizeMode(
            2,
            QHeaderView.ResizeMode.ResizeToContents,
        )

        layout.addWidget(
            self.locations_table
        )

        # ----------------------------------------------------
        # Index action buttons
        # ----------------------------------------------------

        index_actions = QHBoxLayout()

        index_actions.setSpacing(
            12
        )

        self.index_status = QLabel(
            ""
        )

        self.index_status.setObjectName(
            "searchStatus"
        )

        self.open_location_button = QPushButton(
            "Open Location"
        )

        self.open_location_button.setObjectName(
            "secondaryButton"
        )

        self.open_location_button.setEnabled(
            False
        )

        self.open_location_button.clicked.connect(
            self.open_selected_location
        )

        self.reindex_button = QPushButton(
            "Reindex Selected"
        )

        self.reindex_button.setObjectName(
            "secondaryButton"
        )

        self.reindex_button.setEnabled(
            False
        )

        self.reindex_button.clicked.connect(
            self.reindex_selected
        )

        self.remove_button = QPushButton(
            "Remove from Index"
        )

        self.remove_button.setObjectName(
            "secondaryButton"
        )

        self.remove_button.setEnabled(
            False
        )

        self.remove_button.clicked.connect(
            self.remove_selected_root
        )

        self.clear_index_button = QPushButton(
            "Clear Entire Index"
        )

        self.clear_index_button.setObjectName(
            "secondaryButton"
        )

        self.clear_index_button.clicked.connect(
            self.clear_entire_index
        )

        index_actions.addWidget(
            self.index_status
        )

        index_actions.addStretch()

        index_actions.addWidget(
            self.open_location_button
        )

        index_actions.addWidget(
            self.reindex_button
        )

        index_actions.addWidget(
            self.remove_button
        )

        index_actions.addWidget(
            self.clear_index_button
        )

        layout.addLayout(
            index_actions
        )

        layout.addSpacing(
            2
        )

        # ----------------------------------------------------
        # Application behavior
        # ----------------------------------------------------

        behavior_title = QLabel(
            "Application"
        )

        behavior_title.setObjectName(
            "sectionTitle"
        )

        layout.addWidget(
            behavior_title
        )

        behavior_card = QWidget()

        behavior_card.setObjectName(
            "summaryCard"
        )

        behavior_layout = QHBoxLayout(
            behavior_card
        )

        behavior_layout.setContentsMargins(
            20,
            18,
            20,
            18,
        )

        behavior_text = QVBoxLayout()

        behavior_text.setSpacing(
            5
        )

        remember_title = QLabel(
            "Remember last page"
        )

        remember_title.setObjectName(
            "driveTitle"
        )

        remember_description = QLabel(
            "Reopen SysDeck on the page you were using last."
        )

        remember_description.setObjectName(
            "pageDescription"
        )

        behavior_text.addWidget(
            remember_title
        )

        behavior_text.addWidget(
            remember_description
        )

        self.remember_page_button = QPushButton()

        self.remember_page_button.setObjectName(
            "secondaryButton"
        )

        self.remember_page_button.setCheckable(
            True
        )

        self.remember_page_button.clicked.connect(
            self.toggle_remember_last_page
        )

        behavior_layout.addLayout(
            behavior_text
        )

        behavior_layout.addStretch()

        behavior_layout.addWidget(
            self.remember_page_button
        )

        layout.addWidget(
            behavior_card
        )

        # ----------------------------------------------------
        # App data
        # ----------------------------------------------------

        data_card = QWidget()

        data_card.setObjectName(
            "summaryCard"
        )

        data_layout = QHBoxLayout(
            data_card
        )

        data_layout.setContentsMargins(
            20,
            18,
            20,
            18,
        )

        data_text = QVBoxLayout()

        data_text.setSpacing(
            5
        )

        data_title = QLabel(
            "SysDeck data"
        )

        data_title.setObjectName(
            "driveTitle"
        )

        data_description = QLabel(
            "Open the local folder containing SysDeck's database and application data."
        )

        data_description.setObjectName(
            "pageDescription"
        )

        data_text.addWidget(
            data_title
        )

        data_text.addWidget(
            data_description
        )

        open_data_button = QPushButton(
            "Open Data Folder"
        )

        open_data_button.setObjectName(
            "secondaryButton"
        )

        open_data_button.clicked.connect(
            self.open_data_folder
        )

        data_layout.addLayout(
            data_text
        )

        data_layout.addStretch()

        data_layout.addWidget(
            open_data_button
        )

        layout.addWidget(
            data_card
        )

        layout.addStretch()

    # ========================================================
    # Cards
    # ========================================================

    def create_summary_card(
        self,
        title,
        value,
    ):
        card = QWidget()

        card.setObjectName(
            "summaryCard"
        )

        card_layout = QVBoxLayout(
            card
        )

        card_layout.setContentsMargins(
            18,
            16,
            18,
            16,
        )

        card_layout.setSpacing(
            7
        )

        title_label = QLabel(
            title
        )

        title_label.setObjectName(
            "summaryTitle"
        )

        value.setObjectName(
            "summaryValue"
        )

        card_layout.addWidget(
            title_label
        )

        card_layout.addWidget(
            value
        )

        return card

    # ========================================================
    # Page refresh
    # ========================================================

    def showEvent(
        self,
        event,
    ):
        super().showEvent(
            event
        )

        self.refresh_index_info()
        self.refresh_remember_page_button()

    def refresh_index_info(self):
        connection = connect_database()

        try:
            file_count = connection.execute(
                """
                SELECT COUNT(*)
                FROM files
                """
            ).fetchone()[0]

            root_rows = connection.execute(
                """
                SELECT
                    root_path,
                    COUNT(*) AS file_count,
                    COALESCE(SUM(size), 0) AS total_size
                FROM files
                GROUP BY root_path
                ORDER BY root_path COLLATE NOCASE
                """
            ).fetchall()

        finally:
            connection.close()

        database_path = (
            get_database_path()
        )

        try:
            database_size = os.path.getsize(
                database_path
            )

        except OSError:
            database_size = 0

        self.indexed_files_value.setText(
            f"{file_count:,}"
        )

        self.locations_value.setText(
            f"{len(root_rows):,}"
        )

        self.database_size_value.setText(
            self.format_size(
                database_size
            )
        )

        self.database_path_label.setText(
            f"Database: {database_path}"
        )

        self.populate_locations_table(
            root_rows
        )

        if root_rows:
            self.index_status.setText(
                f"{len(root_rows):,} indexed "
                f"location{'' if len(root_rows) == 1 else 's'}"
            )

        else:
            self.index_status.setText(
                "No indexed locations"
            )

        self.clear_index_button.setEnabled(
            file_count > 0
            and not self.maintenance_running()
        )

    def populate_locations_table(
        self,
        rows,
    ):
        self.locations_table.setUpdatesEnabled(
            False
        )

        self.locations_table.setRowCount(
            len(rows)
        )

        # Dynamically size the table so one indexed
        # location doesn't leave a large empty area.
        header_height = 42
        row_height = 40

        visible_rows = max(
            1,
            min(
                len(rows),
                4,
            ),
        )

        table_height = (
            header_height
            + visible_rows * row_height
            + 4
        )

        self.locations_table.setFixedHeight(
            table_height
        )

        for row_index, (
            root_path,
            file_count,
            total_size,
        ) in enumerate(rows):

            root_item = QTableWidgetItem(
                root_path
            )

            root_item.setData(
                Qt.ItemDataRole.UserRole,
                root_path,
            )

            root_item.setToolTip(
                root_path
            )

            file_count_item = QTableWidgetItem(
                f"{file_count:,}"
            )

            file_count_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight
                | Qt.AlignmentFlag.AlignVCenter
            )

            size_item = QTableWidgetItem(
                self.format_size(
                    total_size
                )
            )

            size_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight
                | Qt.AlignmentFlag.AlignVCenter
            )

            self.locations_table.setItem(
                row_index,
                0,
                root_item,
            )

            self.locations_table.setItem(
                row_index,
                1,
                file_count_item,
            )

            self.locations_table.setItem(
                row_index,
                2,
                size_item,
            )

        self.locations_table.setUpdatesEnabled(
            True
        )

        self.locations_table.viewport().update()

        self.update_index_action_buttons()

    # ========================================================
    # Selected indexed location
    # ========================================================

    def get_selected_root(self):
        selected_rows = (
            self.locations_table
            .selectionModel()
            .selectedRows()
        )

        if not selected_rows:
            return None

        row = selected_rows[0].row()

        item = self.locations_table.item(
            row,
            0,
        )

        if item is None:
            return None

        return item.data(
            Qt.ItemDataRole.UserRole
        )

    def update_index_action_buttons(self):
        has_selection = (
            self.get_selected_root()
            is not None
        )

        enabled = (
            has_selection
            and not self.maintenance_running()
        )

        self.open_location_button.setEnabled(
            enabled
        )

        self.reindex_button.setEnabled(
            enabled
        )

        self.remove_button.setEnabled(
            enabled
        )

    def open_selected_location(self):
        root = self.get_selected_root()

        if not root:
            return

        if not os.path.exists(root):
            QMessageBox.warning(
                self,
                "Location unavailable",
                "That indexed location no longer exists or is currently unavailable.",
            )

            return

        try:
            os.startfile(
                root
            )

        except OSError:
            pass

    # ========================================================
    # Reindex
    # ========================================================

    def reindex_selected(self):
        root = self.get_selected_root()

        if not root:
            return

        if not os.path.exists(root):
            QMessageBox.warning(
                self,
                "Location unavailable",
                "That indexed location no longer exists and cannot be reindexed.",
            )

            return

        self.reindex_requested.emit(
            root
        )

    # ========================================================
    # Remove location
    # ========================================================

    def remove_selected_root(self):
        root = self.get_selected_root()

        if not root:
            return

        confirmation = QMessageBox.question(
            self,
            "Remove indexed location",
            (
                "Remove this location from SysDeck's search index?\n\n"
                f"{root}\n\n"
                "No actual files or folders will be deleted."
            ),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if (
            confirmation
            != QMessageBox.StandardButton.Yes
        ):
            return

        self.start_maintenance(
            "remove_root",
            root,
        )

    # ========================================================
    # Clear index
    # ========================================================

    def clear_entire_index(self):
        confirmation = QMessageBox.question(
            self,
            "Clear entire index",
            (
                "Remove every indexed file from SysDeck's local database?\n\n"
                "Your actual files will not be touched. "
                "You can index the locations again later."
            ),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if (
            confirmation
            != QMessageBox.StandardButton.Yes
        ):
            return

        self.start_maintenance(
            "clear_all"
        )

    # ========================================================
    # Maintenance thread
    # ========================================================

    def start_maintenance(
        self,
        action,
        root_path=None,
    ):
        if self.maintenance_running():
            return

        self.set_maintenance_controls(
            False
        )

        if action == "remove_root":
            self.index_status.setText(
                "Removing location from index..."
            )

        else:
            self.index_status.setText(
                "Clearing index..."
            )

        self.maintenance_thread = QThread(
            self
        )

        self.maintenance_worker = (
            IndexMaintenanceWorker(
                action,
                root_path,
            )
        )

        self.maintenance_worker.moveToThread(
            self.maintenance_thread
        )

        self.maintenance_thread.started.connect(
            self.maintenance_worker.run
        )

        self.maintenance_worker.finished.connect(
            self.handle_maintenance_finished
        )

        self.maintenance_worker.failed.connect(
            self.handle_maintenance_failed
        )

        self.maintenance_worker.finished.connect(
            self.maintenance_thread.quit
        )

        self.maintenance_worker.failed.connect(
            self.maintenance_thread.quit
        )

        self.maintenance_worker.finished.connect(
            self.maintenance_worker.deleteLater
        )

        self.maintenance_worker.failed.connect(
            self.maintenance_worker.deleteLater
        )

        self.maintenance_thread.finished.connect(
            self.cleanup_maintenance_thread
        )

        self.maintenance_thread.start()

    @Slot(object)
    def handle_maintenance_finished(
        self,
        result,
    ):
        removed = result[
            "removed"
        ]

        if result["action"] == "remove_root":
            self.index_status.setText(
                f"Removed {removed:,} indexed files"
            )

        else:
            self.index_status.setText(
                f"Cleared {removed:,} indexed files"
            )

        self.refresh_index_info()

        self.index_changed.emit()

    @Slot(str)
    def handle_maintenance_failed(
        self,
        error,
    ):
        self.index_status.setText(
            f"Index operation failed: {error}"
        )

        self.set_maintenance_controls(
            True
        )

    def cleanup_maintenance_thread(self):
        if self.maintenance_thread is not None:
            self.maintenance_thread.deleteLater()

        self.maintenance_thread = None
        self.maintenance_worker = None

        self.set_maintenance_controls(
            True
        )

    def maintenance_running(self):
        return (
            self.maintenance_thread is not None
            and self.maintenance_thread.isRunning()
        )

    def set_maintenance_controls(
        self,
        enabled,
    ):
        if not enabled:
            self.open_location_button.setEnabled(
                False
            )

            self.reindex_button.setEnabled(
                False
            )

            self.remove_button.setEnabled(
                False
            )

            self.clear_index_button.setEnabled(
                False
            )

            return

        self.update_index_action_buttons()

        self.clear_index_button.setEnabled(
            self.locations_table.rowCount()
            > 0
        )

    # ========================================================
    # Remember last page
    # ========================================================

    def toggle_remember_last_page(
        self,
        checked,
    ):
        self.settings.setValue(
            "navigation/remember_last_page",
            bool(checked),
        )

        self.settings.sync()

        self.refresh_remember_page_button()

    def refresh_remember_page_button(self):
        enabled = self.settings.value(
            "navigation/remember_last_page",
            False,
            type=bool,
        )

        self.remember_page_button.blockSignals(
            True
        )

        self.remember_page_button.setChecked(
            enabled
        )

        self.remember_page_button.setText(
            "On"
            if enabled
            else "Off"
        )

        self.remember_page_button.blockSignals(
            False
        )

    # ========================================================
    # App data
    # ========================================================

    def open_data_folder(self):
        database_path = (
            get_database_path()
        )

        folder = os.path.dirname(
            database_path
        )

        os.makedirs(
            folder,
            exist_ok=True,
        )

        try:
            os.startfile(
                folder
            )

        except OSError:
            pass

    # ========================================================
    # Shutdown
    # ========================================================

    def shutdown_worker(self):
        if (
            self.maintenance_thread is not None
            and self.maintenance_thread.isRunning()
        ):
            self.maintenance_thread.requestInterruption()

            self.maintenance_thread.quit()

            self.maintenance_thread.wait(
                1500
            )

    # ========================================================
    # Formatting
    # ========================================================

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

        return f"{size} B"