import datetime
import os
import subprocess
import time

from PySide6.QtCore import (
    QObject,
    QThread,
    Qt,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
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
# Background file indexer
# ============================================================

class FileIndexWorker(QObject):
    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, root_folder):
        super().__init__()

        self.root_folder = os.path.abspath(
            root_folder
        )

    @Slot()
    def index_folder(self):
        connection = None

        try:
            connection = connect_database()

            # Re-indexing the same location replaces
            # its old records instead of duplicating them.
            connection.execute(
                """
                DELETE FROM files
                WHERE root_path = ?
                """,
                (self.root_folder,),
            )

            connection.commit()

            indexed_count = 0
            skipped_count = 0

            batch = []

            last_progress_time = (
                time.monotonic()
            )

            def handle_walk_error(_error):
                nonlocal skipped_count
                skipped_count += 1

            for current_root, directories, files in os.walk(
                self.root_folder,
                topdown=True,
                onerror=handle_walk_error,
                followlinks=False,
            ):
                if (
                    QThread.currentThread()
                    .isInterruptionRequested()
                ):
                    return

                safe_directories = []

                for directory in directories:
                    directory_path = os.path.join(
                        current_root,
                        directory,
                    )

                    try:
                        if not os.path.islink(
                            directory_path
                        ):
                            safe_directories.append(
                                directory
                            )

                    except OSError:
                        skipped_count += 1

                directories[:] = (
                    safe_directories
                )

                for filename in files:
                    if (
                        QThread.currentThread()
                        .isInterruptionRequested()
                    ):
                        return

                    path = os.path.join(
                        current_root,
                        filename,
                    )

                    try:
                        if os.path.islink(path):
                            continue

                        stat = os.stat(path)

                    except (
                        PermissionError,
                        FileNotFoundError,
                        OSError,
                    ):
                        skipped_count += 1
                        continue

                    extension = os.path.splitext(
                        filename
                    )[1].lower()

                    batch.append(
                        (
                            self.root_folder,
                            path,
                            filename,
                            current_root,
                            extension,
                            stat.st_size,
                            stat.st_mtime,
                        )
                    )

                    indexed_count += 1

                    if len(batch) >= 500:
                        self.write_batch(
                            connection,
                            batch,
                        )

                        batch.clear()

                    now = time.monotonic()

                    if (
                        indexed_count % 500 == 0
                        or now - last_progress_time
                        >= 0.4
                    ):
                        self.progress.emit(
                            {
                                "indexed":
                                    indexed_count,

                                "skipped":
                                    skipped_count,
                            }
                        )

                        last_progress_time = now

            if batch:
                self.write_batch(
                    connection,
                    batch,
                )

            connection.commit()

            self.finished.emit(
                {
                    "root":
                        self.root_folder,

                    "indexed":
                        indexed_count,

                    "skipped":
                        skipped_count,
                }
            )

        except Exception as error:
            self.failed.emit(
                str(error)
            )

        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def write_batch(
        connection,
        batch,
    ):
        connection.executemany(
            """
            INSERT INTO files (
                root_path,
                path,
                name,
                parent,
                extension,
                size,
                modified
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)

            ON CONFLICT(path) DO UPDATE SET
                root_path = excluded.root_path,
                name = excluded.name,
                parent = excluded.parent,
                extension = excluded.extension,
                size = excluded.size,
                modified = excluded.modified
            """,
            batch,
        )

        connection.commit()


# ============================================================
# Search page
# ============================================================

class SearchPage(QWidget):
    def __init__(self):
        super().__init__()

        self.index_thread = None
        self.index_worker = None

        self.setup_ui()
        self.setup_search_timer()

        self.refresh_filter_options()
        self.refresh_index_status()
        self.perform_search()

        app = QApplication.instance()

        if app is not None:
            app.aboutToQuit.connect(
                self.shutdown_indexer
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

        layout.setSpacing(16)

        # ----------------------------------------------------
        # Header
        # ----------------------------------------------------

        header = QHBoxLayout()

        header_text = QVBoxLayout()
        header_text.setSpacing(6)

        title = QLabel(
            "Search"
        )

        title.setObjectName(
            "pageTitle"
        )

        description = QLabel(
            "Index and instantly search files across your computer."
        )

        description.setObjectName(
            "pageDescription"
        )

        header_text.addWidget(
            title
        )

        header_text.addWidget(
            description
        )

        self.index_button = QPushButton(
            "Index Folder"
        )

        self.index_button.setObjectName(
            "primaryButton"
        )

        self.index_button.clicked.connect(
            self.choose_index_folder
        )

        header.addLayout(
            header_text
        )

        header.addStretch()

        header.addWidget(
            self.index_button
        )

        layout.addLayout(
            header
        )

        # ----------------------------------------------------
        # Index information
        # ----------------------------------------------------

        self.index_status = QLabel(
            "Checking index..."
        )

        self.index_status.setObjectName(
            "searchStatus"
        )

        layout.addWidget(
            self.index_status
        )

        # ----------------------------------------------------
        # Main search box
        # ----------------------------------------------------

        self.search_input = QLineEdit()

        self.search_input.setObjectName(
            "searchInput"
        )

        self.search_input.setPlaceholderText(
            "Search by filename or path..."
        )

        self.search_input.setClearButtonEnabled(
            True
        )

        self.search_input.textChanged.connect(
            self.queue_search
        )

        layout.addWidget(
            self.search_input
        )

        # ----------------------------------------------------
        # Filters
        # ----------------------------------------------------

        filter_row = QHBoxLayout()
        filter_row.setSpacing(10)

        self.root_filter = QComboBox()

        self.root_filter.setObjectName(
            "searchFilter"
        )

        self.root_filter.setMinimumWidth(
            190
        )

        self.root_filter.currentIndexChanged.connect(
            self.queue_search
        )

        self.extension_filter = QComboBox()

        self.extension_filter.setObjectName(
            "searchFilter"
        )

        self.extension_filter.setMinimumWidth(
            115
        )

        self.extension_filter.currentIndexChanged.connect(
            self.queue_search
        )

        self.size_filter = QComboBox()

        self.size_filter.setObjectName(
            "searchFilter"
        )

        self.size_filter.addItem(
            "Any size",
            0,
        )

        self.size_filter.addItem(
            "≥ 1 MB",
            1024 ** 2,
        )

        self.size_filter.addItem(
            "≥ 10 MB",
            10 * 1024 ** 2,
        )

        self.size_filter.addItem(
            "≥ 100 MB",
            100 * 1024 ** 2,
        )

        self.size_filter.addItem(
            "≥ 1 GB",
            1024 ** 3,
        )

        self.size_filter.currentIndexChanged.connect(
            self.queue_search
        )

        self.modified_filter = QComboBox()

        self.modified_filter.setObjectName(
            "searchFilter"
        )

        self.modified_filter.addItem(
            "Any date",
            None,
        )

        self.modified_filter.addItem(
            "Today",
            86400,
        )

        self.modified_filter.addItem(
            "Last 7 days",
            7 * 86400,
        )

        self.modified_filter.addItem(
            "Last 30 days",
            30 * 86400,
        )

        self.modified_filter.addItem(
            "Last year",
            365 * 86400,
        )

        self.modified_filter.currentIndexChanged.connect(
            self.queue_search
        )

        self.sort_filter = QComboBox()

        self.sort_filter.setObjectName(
            "searchFilter"
        )

        self.sort_filter.addItem(
            "Relevance",
            "relevance",
        )

        self.sort_filter.addItem(
            "Name A–Z",
            "name",
        )

        self.sort_filter.addItem(
            "Largest first",
            "size",
        )

        self.sort_filter.addItem(
            "Newest first",
            "modified",
        )

        self.sort_filter.currentIndexChanged.connect(
            self.queue_search
        )

        self.clear_filters_button = QPushButton(
            "Clear Filters"
        )

        self.clear_filters_button.setObjectName(
            "secondaryButton"
        )

        self.clear_filters_button.clicked.connect(
            self.clear_filters
        )

        filter_row.addWidget(
            self.root_filter
        )

        filter_row.addWidget(
            self.extension_filter
        )

        filter_row.addWidget(
            self.size_filter
        )

        filter_row.addWidget(
            self.modified_filter
        )

        filter_row.addWidget(
            self.sort_filter
        )

        filter_row.addStretch()

        filter_row.addWidget(
            self.clear_filters_button
        )

        layout.addLayout(
            filter_row
        )

        # ----------------------------------------------------
        # Result actions
        # ----------------------------------------------------

        results_header = QHBoxLayout()

        self.results_status = QLabel(
            "No results"
        )

        self.results_status.setObjectName(
            "searchStatus"
        )

        self.copy_path_button = QPushButton(
            "Copy Path"
        )

        self.copy_path_button.setObjectName(
            "secondaryButton"
        )

        self.copy_path_button.setEnabled(
            False
        )

        self.copy_path_button.clicked.connect(
            self.copy_selected_path
        )

        self.open_button = QPushButton(
            "Open"
        )

        self.open_button.setObjectName(
            "secondaryButton"
        )

        self.open_button.setEnabled(
            False
        )

        self.open_button.clicked.connect(
            self.open_selected
        )

        self.folder_button = QPushButton(
            "Open Containing Folder"
        )

        self.folder_button.setObjectName(
            "secondaryButton"
        )

        self.folder_button.setEnabled(
            False
        )

        self.folder_button.clicked.connect(
            self.open_selected_folder
        )

        results_header.addWidget(
            self.results_status
        )

        results_header.addStretch()

        results_header.addWidget(
            self.copy_path_button
        )

        results_header.addWidget(
            self.open_button
        )

        results_header.addWidget(
            self.folder_button
        )

        layout.addLayout(
            results_header
        )

        # ----------------------------------------------------
        # Results table
        # ----------------------------------------------------

        self.results_table = QTableWidget(
            0,
            5,
        )

        self.results_table.setObjectName(
            "searchResults"
        )

        self.results_table.setHorizontalHeaderLabels(
            [
                "Name",
                "Folder",
                "Type",
                "Size",
                "Modified",
            ]
        )

        self.results_table.verticalHeader().hide()

        self.results_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )

        self.results_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )

        self.results_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )

        self.results_table.setAlternatingRowColors(
            True
        )

        self.results_table.setShowGrid(
            False
        )

        self.results_table.itemSelectionChanged.connect(
            self.update_action_buttons
        )

        self.results_table.itemDoubleClicked.connect(
            lambda _item:
            self.open_selected()
        )

        header_view = (
            self.results_table
            .horizontalHeader()
        )

        header_view.setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.Stretch,
        )

        header_view.setSectionResizeMode(
            1,
            QHeaderView.ResizeMode.Stretch,
        )

        header_view.setSectionResizeMode(
            2,
            QHeaderView.ResizeMode.ResizeToContents,
        )

        header_view.setSectionResizeMode(
            3,
            QHeaderView.ResizeMode.ResizeToContents,
        )

        header_view.setSectionResizeMode(
            4,
            QHeaderView.ResizeMode.ResizeToContents,
        )

        layout.addWidget(
            self.results_table,
            1,
        )

    def setup_search_timer(self):
        self.search_timer = QTimer(
            self
        )

        self.search_timer.setSingleShot(
            True
        )

        self.search_timer.setInterval(
            180
        )

        self.search_timer.timeout.connect(
            self.perform_search
        )

    # ========================================================
    # Indexing
    # ========================================================

    def choose_index_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Choose Folder to Index",
        )

        if not folder:
            return

        self.start_index(
            folder
        )

    def start_index(
        self,
        folder,
    ):
        if (
            self.index_thread is not None
            and self.index_thread.isRunning()
        ):
            return

        self.index_button.setEnabled(
            False
        )

        self.index_status.setText(
            f"Starting index: {folder}"
        )

        self.index_thread = QThread(
            self
        )

        self.index_worker = FileIndexWorker(
            folder
        )

        self.index_worker.moveToThread(
            self.index_thread
        )

        self.index_thread.started.connect(
            self.index_worker.index_folder
        )

        self.index_worker.progress.connect(
            self.handle_index_progress
        )

        self.index_worker.finished.connect(
            self.handle_index_finished
        )

        self.index_worker.failed.connect(
            self.handle_index_failed
        )

        self.index_worker.finished.connect(
            self.index_thread.quit
        )

        self.index_worker.failed.connect(
            self.index_thread.quit
        )

        self.index_worker.finished.connect(
            self.index_worker.deleteLater
        )

        self.index_worker.failed.connect(
            self.index_worker.deleteLater
        )

        self.index_thread.finished.connect(
            self.cleanup_index_thread
        )

        self.index_thread.start()

    @Slot(object)
    def handle_index_progress(
        self,
        progress,
    ):
        self.index_status.setText(
            f"Indexing... "
            f"{progress['indexed']:,} files · "
            f"{progress['skipped']:,} skipped"
        )

    @Slot(object)
    def handle_index_finished(
        self,
        results,
    ):
        self.index_button.setEnabled(
            True
        )

        self.refresh_filter_options()
        self.refresh_index_status()

        self.perform_search()

    @Slot(str)
    def handle_index_failed(
        self,
        error,
    ):
        self.index_button.setEnabled(
            True
        )

        self.index_status.setText(
            f"Index failed: {error}"
        )

    def cleanup_index_thread(self):
        if self.index_thread is not None:
            self.index_thread.deleteLater()

        self.index_thread = None
        self.index_worker = None

    def shutdown_indexer(self):
        if (
            self.index_thread is not None
            and self.index_thread.isRunning()
        ):
            self.index_thread.requestInterruption()

            self.index_thread.quit()

            self.index_thread.wait(
                1500
            )

    # ========================================================
    # Filter data
    # ========================================================

    def refresh_filter_options(self):
        current_root = (
            self.root_filter.currentData()
            if self.root_filter.count()
            else None
        )

        current_extension = (
            self.extension_filter.currentData()
            if self.extension_filter.count()
            else None
        )

        connection = connect_database()

        try:
            roots = connection.execute(
                """
                SELECT DISTINCT root_path
                FROM files
                ORDER BY root_path COLLATE NOCASE
                """
            ).fetchall()

            extensions = connection.execute(
                """
                SELECT DISTINCT extension
                FROM files
                WHERE extension != ''
                ORDER BY extension COLLATE NOCASE
                """
            ).fetchall()

        finally:
            connection.close()

        self.root_filter.blockSignals(
            True
        )

        self.extension_filter.blockSignals(
            True
        )

        self.root_filter.clear()

        self.root_filter.addItem(
            "All locations",
            None,
        )

        for root, in roots:
            self.root_filter.addItem(
                root,
                root,
            )

        self.extension_filter.clear()

        self.extension_filter.addItem(
            "All types",
            None,
        )

        for extension, in extensions:
            self.extension_filter.addItem(
                extension.upper(),
                extension,
            )

        self.restore_combo_value(
            self.root_filter,
            current_root,
        )

        self.restore_combo_value(
            self.extension_filter,
            current_extension,
        )

        self.root_filter.blockSignals(
            False
        )

        self.extension_filter.blockSignals(
            False
        )

    @staticmethod
    def restore_combo_value(
        combo,
        value,
    ):
        if value is None:
            combo.setCurrentIndex(0)
            return

        index = combo.findData(
            value
        )

        if index >= 0:
            combo.setCurrentIndex(
                index
            )

        else:
            combo.setCurrentIndex(
                0
            )

    def clear_filters(self):
        self.root_filter.setCurrentIndex(
            0
        )

        self.extension_filter.setCurrentIndex(
            0
        )

        self.size_filter.setCurrentIndex(
            0
        )

        self.modified_filter.setCurrentIndex(
            0
        )

        self.sort_filter.setCurrentIndex(
            0
        )

        self.queue_search()

    # ========================================================
    # Searching
    # ========================================================

    def queue_search(
        self,
        *_args,
    ):
        self.search_timer.start()

    def perform_search(self):
        query = (
            self.search_input
            .text()
            .strip()
        )

        root = (
            self.root_filter
            .currentData()
        )

        extension = (
            self.extension_filter
            .currentData()
        )

        minimum_size = (
            self.size_filter
            .currentData()
            or 0
        )

        modified_age = (
            self.modified_filter
            .currentData()
        )

        sort_mode = (
            self.sort_filter
            .currentData()
            or "relevance"
        )

        where_clauses = []
        parameters = []

        # ----------------------------------------------------
        # Multi-word search
        # ----------------------------------------------------

        terms = [
            term
            for term
            in query.split()
            if term
        ]

        for term in terms:
            wildcard = (
                f"%{term}%"
            )

            where_clauses.append(
                """
                (
                    name LIKE ? COLLATE NOCASE
                    OR
                    path LIKE ? COLLATE NOCASE
                )
                """
            )

            parameters.extend(
                [
                    wildcard,
                    wildcard,
                ]
            )

        # ----------------------------------------------------
        # Filters
        # ----------------------------------------------------

        if root:
            where_clauses.append(
                "root_path = ?"
            )

            parameters.append(
                root
            )

        if extension:
            where_clauses.append(
                "extension = ? COLLATE NOCASE"
            )

            parameters.append(
                extension
            )

        if minimum_size > 0:
            where_clauses.append(
                "size >= ?"
            )

            parameters.append(
                minimum_size
            )

        if modified_age is not None:
            cutoff = (
                time.time()
                - modified_age
            )

            where_clauses.append(
                "modified >= ?"
            )

            parameters.append(
                cutoff
            )

        where_sql = ""

        if where_clauses:
            where_sql = (
                "WHERE "
                + " AND ".join(
                    where_clauses
                )
            )

        # ----------------------------------------------------
        # Sort order
        # ----------------------------------------------------

        if (
            sort_mode == "relevance"
            and query
        ):
            first_term = terms[0]

            exact = first_term

            prefix = (
                f"{first_term}%"
            )

            relevance_sql = """
                CASE
                    WHEN name = ? COLLATE NOCASE
                        THEN 0

                    WHEN name LIKE ? COLLATE NOCASE
                        THEN 1

                    ELSE 2
                END,
                name COLLATE NOCASE
            """

            select_parameters = (
                parameters
                + [
                    exact,
                    prefix,
                ]
            )

        elif sort_mode == "name":
            relevance_sql = (
                "name COLLATE NOCASE ASC"
            )

            select_parameters = (
                parameters
            )

        elif sort_mode == "size":
            relevance_sql = (
                "size DESC"
            )

            select_parameters = (
                parameters
            )

        else:
            relevance_sql = (
                "modified DESC"
            )

            select_parameters = (
                parameters
            )

        connection = connect_database()

        try:
            total_results = connection.execute(
                f"""
                SELECT COUNT(*)
                FROM files
                {where_sql}
                """,
                parameters,
            ).fetchone()[0]

            rows = connection.execute(
                f"""
                SELECT
                    name,
                    parent,
                    extension,
                    size,
                    modified,
                    path
                FROM files
                {where_sql}
                ORDER BY
                    {relevance_sql}
                LIMIT 500
                """,
                select_parameters,
            ).fetchall()

        finally:
            connection.close()

        self.populate_results(
            rows,
            total_results,
        )

    def populate_results(
        self,
        rows,
        total_results,
    ):
        self.results_table.setUpdatesEnabled(
            False
        )

        self.results_table.setRowCount(
            len(rows)
        )

        for row_index, row in enumerate(
            rows
        ):
            (
                name,
                parent,
                extension,
                size,
                modified,
                path,
            ) = row

            name_item = QTableWidgetItem(
                name
            )

            name_item.setData(
                Qt.ItemDataRole.UserRole,
                path,
            )

            folder_item = QTableWidgetItem(
                parent
            )

            folder_item.setToolTip(
                parent
            )

            file_type = (
                extension[1:].upper()
                if extension
                else "FILE"
            )

            type_item = QTableWidgetItem(
                file_type
            )

            size_item = QTableWidgetItem(
                self.format_size(
                    size
                )
            )

            size_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight
                | Qt.AlignmentFlag.AlignVCenter
            )

            modified_text = (
                datetime.datetime
                .fromtimestamp(
                    modified
                )
                .strftime(
                    "%Y-%m-%d %H:%M"
                )
            )

            modified_item = QTableWidgetItem(
                modified_text
            )

            self.results_table.setItem(
                row_index,
                0,
                name_item,
            )

            self.results_table.setItem(
                row_index,
                1,
                folder_item,
            )

            self.results_table.setItem(
                row_index,
                2,
                type_item,
            )

            self.results_table.setItem(
                row_index,
                3,
                size_item,
            )

            self.results_table.setItem(
                row_index,
                4,
                modified_item,
            )

        self.results_table.setUpdatesEnabled(
            True
        )

        self.results_table.viewport().update()

        if total_results > len(rows):
            self.results_status.setText(
                f"Showing {len(rows):,} of "
                f"{total_results:,} results"
            )

        else:
            self.results_status.setText(
                f"{total_results:,} result"
                f"{'' if total_results == 1 else 's'}"
            )

        self.update_action_buttons()

    # ========================================================
    # Index information
    # ========================================================

    def refresh_index_status(self):
        connection = connect_database()

        try:
            file_count = connection.execute(
                """
                SELECT COUNT(*)
                FROM files
                """
            ).fetchone()[0]

            root_count = connection.execute(
                """
                SELECT COUNT(
                    DISTINCT root_path
                )
                FROM files
                """
            ).fetchone()[0]

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

        if file_count == 0:
            self.index_status.setText(
                "No files indexed yet."
            )

        else:
            location_word = (
                "location"
                if root_count == 1
                else "locations"
            )

            self.index_status.setText(
                f"{file_count:,} files indexed across "
                f"{root_count:,} {location_word} · "
                f"Index size {self.format_size(database_size)}"
            )

    # ========================================================
    # File actions
    # ========================================================

    def get_selected_path(self):
        selected_rows = (
            self.results_table
            .selectionModel()
            .selectedRows()
        )

        if not selected_rows:
            return None

        row = (
            selected_rows[0]
            .row()
        )

        item = self.results_table.item(
            row,
            0,
        )

        if item is None:
            return None

        return item.data(
            Qt.ItemDataRole.UserRole
        )

    def update_action_buttons(self):
        has_selection = (
            self.get_selected_path()
            is not None
        )

        self.copy_path_button.setEnabled(
            has_selection
        )

        self.open_button.setEnabled(
            has_selection
        )

        self.folder_button.setEnabled(
            has_selection
        )

    def copy_selected_path(self):
        path = self.get_selected_path()

        if not path:
            return

        clipboard = (
            QApplication.clipboard()
        )

        clipboard.setText(
            path
        )

        self.results_status.setText(
            "Path copied to clipboard"
        )

    def open_selected(self):
        path = self.get_selected_path()

        if (
            not path
            or not os.path.exists(path)
        ):
            return

        try:
            os.startfile(path)

        except OSError:
            pass

    def open_selected_folder(self):
        path = self.get_selected_path()

        if not path:
            return

        if not os.path.exists(path):
            return

        try:
            subprocess.Popen(
                [
                    "explorer.exe",
                    "/select,",
                    os.path.normpath(
                        path
                    ),
                ]
            )

        except OSError:
            try:
                os.startfile(
                    os.path.dirname(
                        path
                    )
                )

            except OSError:
                pass

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