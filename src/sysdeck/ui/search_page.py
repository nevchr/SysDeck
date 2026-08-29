import datetime
import os
import subprocess
import time

from PySide6.QtCore import (
    QAbstractTableModel,
    QObject,
    QRunnable,
    QThread,
    QThreadPool,
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
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..core.database import (
    connect_database,
    find_indexed_root_conflict,
    get_database_path,
    get_index_counts,
    get_indexed_roots,
    normalize_root_path,
    register_indexed_root,
)


# ============================================================
# Background file indexer
# ============================================================

class FileIndexWorker(QObject):
    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        root_folder,
    ):
        super().__init__()

        self.root_folder = normalize_root_path(
            root_folder
        )

    @Slot()
    def index_folder(self):
        connection = None

        try:
            connection = connect_database()

            # ------------------------------------------------
            # Build the new index in a temporary table first.
            #
            # The existing index remains completely untouched
            # until the filesystem scan succeeds.
            # ------------------------------------------------

            connection.execute(
                """
                DROP TABLE IF EXISTS
                temp_index_files
                """
            )

            connection.execute(
                """
                CREATE TEMP TABLE temp_index_files (
                    path TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    parent TEXT NOT NULL,
                    extension TEXT,
                    size INTEGER NOT NULL,
                    modified REAL NOT NULL
                )
                """
            )

            connection.commit()

            indexed_count = 0
            skipped_count = 0

            batch = []

            last_progress_time = (
                time.monotonic()
            )

            def handle_walk_error(
                _error,
            ):
                nonlocal skipped_count

                skipped_count += 1

            # ------------------------------------------------
            # Filesystem scan
            # ------------------------------------------------

            for (
                current_root,
                directories,
                files,
            ) in os.walk(
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
                        if os.path.islink(
                            path
                        ):
                            continue

                        stat = os.stat(
                            path
                        )

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
                        self.write_staging_batch(
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

                        last_progress_time = (
                            now
                        )

            if batch:
                self.write_staging_batch(
                    connection,
                    batch,
                )

            if (
                QThread.currentThread()
                .isInterruptionRequested()
            ):
                return

            # ------------------------------------------------
            # Atomic index replacement
            #
            # Only now do we touch the persistent index.
            #
            # If anything below fails, rollback restores the
            # previous index completely.
            # ------------------------------------------------

            try:
                connection.execute(
                    "BEGIN IMMEDIATE"
                )

                connection.execute(
                    """
                    DELETE FROM files
                    WHERE root_path = ?
                    """,
                    (
                        self.root_folder,
                    ),
                )

                connection.execute(
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

                    SELECT
                        ?,
                        path,
                        name,
                        parent,
                        extension,
                        size,
                        modified

                    FROM temp_index_files
                    """,
                    (
                        self.root_folder,
                    ),
                )

                register_indexed_root(
                    connection,
                    self.root_folder,
                )

                connection.commit()

            except Exception:
                connection.rollback()
                raise

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
    def write_staging_batch(
        connection,
        batch,
    ):
        connection.executemany(
            """
            INSERT OR REPLACE INTO
            temp_index_files (
                path,
                name,
                parent,
                extension,
                size,
                modified
            )

            VALUES (?, ?, ?, ?, ?, ?)
            """,
            batch,
        )

        # This only commits the temporary staging data.
        # The persistent files table has not been modified yet.
        connection.commit()

# ============================================================
# Search result model
# ============================================================

class SearchResultsModel(
    QAbstractTableModel
):
    HEADERS = [
        "Name",
        "Folder",
        "Type",
        "Size",
        "Modified",
    ]

    def __init__(
        self,
        parent=None,
    ):
        super().__init__(
            parent
        )

        self.rows = []

    def rowCount(
        self,
        parent=None,
    ):
        return len(
            self.rows
        )

    def columnCount(
        self,
        parent=None,
    ):
        return len(
            self.HEADERS
        )

    def headerData(
        self,
        section,
        orientation,
        role=Qt.ItemDataRole.DisplayRole,
    ):
        if (
            role
            != Qt.ItemDataRole.DisplayRole
        ):
            return None

        if (
            orientation
            == Qt.Orientation.Horizontal
            and 0
            <= section
            < len(self.HEADERS)
        ):
            return self.HEADERS[
                section
            ]

        return None

    def data(
        self,
        index,
        role=Qt.ItemDataRole.DisplayRole,
    ):
        if (
            not index.isValid()
            or not (
                0
                <= index.row()
                < len(self.rows)
            )
        ):
            return None

        row = self.rows[
            index.row()
        ]

        column = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return row["name"]

            if column == 1:
                return row["parent"]

            if column == 2:
                return row["type"]

            if column == 3:
                return self.format_size(
                    row["size"]
                )

            if column == 4:
                return (
                    datetime.datetime
                    .fromtimestamp(
                        row["modified"]
                    )
                    .strftime(
                        "%Y-%m-%d %H:%M"
                    )
                )

        if role == Qt.ItemDataRole.ToolTipRole:
            if column in (
                0,
                1,
            ):
                return row["path"]

        if role == Qt.ItemDataRole.UserRole:
            return row["path"]

        if (
            role
            == Qt.ItemDataRole.TextAlignmentRole
            and column == 3
        ):
            return int(
                Qt.AlignmentFlag.AlignRight
                | Qt.AlignmentFlag.AlignVCenter
            )

        return None

    def set_rows(
        self,
        rows,
    ):
        self.beginResetModel()

        self.rows = rows

        self.endResetModel()

    def clear(
        self,
    ):
        self.set_rows(
            []
        )

    def get_path(
        self,
        row,
    ):
        if not (
            0
            <= row
            < len(self.rows)
        ):
            return None

        return self.rows[
            row
        ]["path"]

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


# ============================================================
# Background search task
# ============================================================

class SearchTaskSignals(QObject):
    finished = Signal(object)
    failed = Signal(object)


class SearchTask(QRunnable):
    def __init__(
        self,
        request_id,
        request,
    ):
        super().__init__()

        self.request_id = (
            request_id
        )

        self.request = (
            request
        )

        self.signals = (
            SearchTaskSignals()
        )

    @Slot()
    def run(self):
        connection = None

        try:
            connection = connect_database()

            result = self.execute_search(
                connection,
                self.request,
            )

            result[
                "request_id"
            ] = self.request_id

            self.signals.finished.emit(
                result
            )

        except Exception as error:
            self.signals.failed.emit(
                {
                    "request_id":
                        self.request_id,

                    "error":
                        str(error),
                }
            )

        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def execute_search(
        connection,
        request,
    ):
        query = request[
            "query"
        ]

        root = request[
            "root"
        ]

        extension = request[
            "extension"
        ]

        minimum_size = request[
            "minimum_size"
        ]

        modified_age = request[
            "modified_age"
        ]

        sort_mode = request[
            "sort_mode"
        ]

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
        # Sorting
        # ----------------------------------------------------

        order_parameters = []

        if (
            sort_mode == "relevance"
            and terms
        ):
            first_term = terms[
                0
            ]

            order_sql = """
                CASE
                    WHEN name = ? COLLATE NOCASE
                        THEN 0

                    WHEN name LIKE ? COLLATE NOCASE
                        THEN 1

                    ELSE 2
                END,
                name COLLATE NOCASE ASC
            """

            order_parameters = [
                first_term,
                f"{first_term}%",
            ]

        elif sort_mode == "name":
            order_sql = (
                "name COLLATE NOCASE ASC"
            )

        elif sort_mode == "size":
            order_sql = (
                "size DESC"
            )

        elif sort_mode == "modified":
            order_sql = (
                "modified DESC"
            )

        else:
            # Blank search + relevance selected.
            order_sql = (
                "modified DESC"
            )

        # ----------------------------------------------------
        # Count
        # ----------------------------------------------------

        total_results = connection.execute(
            f"""
            SELECT COUNT(*)
            FROM files
            {where_sql}
            """,
            parameters,
        ).fetchone()[0]

        # ----------------------------------------------------
        # Visible results
        # ----------------------------------------------------

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
                {order_sql}
            LIMIT 500
            """,
            (
                parameters
                + order_parameters
            ),
        ).fetchall()

        formatted_rows = []

        for (
            name,
            parent,
            extension,
            size,
            modified,
            path,
        ) in rows:
            formatted_rows.append(
                {
                    "name":
                        name,

                    "parent":
                        parent,

                    "extension":
                        extension,

                    "type":
                        (
                            extension[1:].upper()
                            if extension
                            else "FILE"
                        ),

                    "size":
                        size,

                    "modified":
                        modified,

                    "path":
                        path,
                }
            )

        return {
            "rows":
                formatted_rows,

            "total_results":
                total_results,
        }


# ============================================================
# Search page
# ============================================================

class SearchPage(QWidget):
    def __init__(self):
        super().__init__()

        # ----------------------------------------------------
        # Index worker
        # ----------------------------------------------------

        self.index_thread = None
        self.index_worker = None

        # ----------------------------------------------------
        # Search worker pool
        #
        # Only one SQL query runs at once.
        #
        # When another search is requested, any queued stale
        # searches are discarded and only the newest remains.
        # ----------------------------------------------------

        self.search_pool = QThreadPool(
            self
        )

        self.search_pool.setMaxThreadCount(
            1
        )

        self.latest_search_id = 0

        self.setup_ui()
        self.setup_search_timer()

        self.refresh_filter_options()
        self.refresh_index_status()

        self.perform_search()

        app = QApplication.instance()

        if app is not None:
            app.aboutToQuit.connect(
                self.shutdown_workers
            )

    # ========================================================
    # UI
    # ========================================================

    def setup_ui(self):
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
            16
        )

        # ----------------------------------------------------
        # Header
        # ----------------------------------------------------

        header = QHBoxLayout()

        header_text = QVBoxLayout()

        header_text.setSpacing(
            6
        )

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
        # Index status
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
        # Search input
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

        filter_row.setSpacing(
            10
        )

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
        # Result controls
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
        # Results model + view
        # ----------------------------------------------------

        self.results_model = (
            SearchResultsModel(
                self
            )
        )

        self.results_table = (
            QTableView()
        )

        self.results_table.setObjectName(
            "searchResults"
        )

        self.results_table.setModel(
            self.results_model
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

        self.results_table.selectionModel().selectionChanged.connect(
            self.update_action_buttons
        )

        self.results_table.doubleClicked.connect(
            lambda _index:
            self.open_selected()
        )

        header_view = (
            self.results_table
            .horizontalHeader()
        )

        header_view.setStretchLastSection(
            False
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

    # ========================================================
    # Search debounce
    # ========================================================

    def setup_search_timer(self):
        self.search_timer = QTimer(
            self
        )

        self.search_timer.setSingleShot(
            True
        )

        # Slightly longer than v0.2 to avoid starting
        # unnecessary searches while typing quickly.
        self.search_timer.setInterval(
            275
        )

        self.search_timer.timeout.connect(
            self.perform_search
        )

    def queue_search(
        self,
        *_args,
    ):
        self.search_timer.start()

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

        folder = normalize_root_path(
            folder
        )

        if not os.path.isdir(
            folder
        ):
            QMessageBox.warning(
                self,
                "Location unavailable",
                (
                    "The selected folder does not exist "
                    "or is currently unavailable."
                ),
            )

            return

        connection = connect_database()

        try:
            conflict = find_indexed_root_conflict(
                connection,
                folder,
            )

        finally:
            connection.close()

        if conflict is not None:
            existing_root = conflict[
                "root"
            ]

            if (
                conflict["type"]
                == "covered_by"
            ):
                QMessageBox.information(
                    self,
                    "Already indexed",
                    (
                        "This folder is already covered by:\n\n"
                        f"{existing_root}\n\n"
                        "You don't need to index it separately. "
                        "Reindex the existing location from Settings "
                        "if you want to refresh it."
                    ),
                )

            else:
                QMessageBox.information(
                    self,
                    "Contains an indexed location",
                    (
                        "This folder contains an indexed location:\n\n"
                        f"{existing_root}\n\n"
                        "Remove that location from the index first, "
                        "then index this broader folder."
                    ),
                )

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
            roots = get_indexed_roots(
    connection
)

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
            combo.setCurrentIndex(
                0
            )

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
    # Background searching
    # ========================================================

    def perform_search(self):
        request = {
            "query":
                self.search_input
                .text()
                .strip(),

            "root":
                self.root_filter
                .currentData(),

            "extension":
                self.extension_filter
                .currentData(),

            "minimum_size":
                (
                    self.size_filter
                    .currentData()
                    or 0
                ),

            "modified_age":
                self.modified_filter
                .currentData(),

            "sort_mode":
                (
                    self.sort_filter
                    .currentData()
                    or "relevance"
                ),
        }

        self.latest_search_id += 1

        request_id = (
            self.latest_search_id
        )

        # Remove searches that haven't started yet.
        #
        # If one query is currently running, it is allowed
        # to finish in the background. Its result will simply
        # be ignored if a newer request exists.
        self.search_pool.clear()

        task = SearchTask(
            request_id,
            request,
        )

        task.signals.finished.connect(
            self.handle_search_finished
        )

        task.signals.failed.connect(
            self.handle_search_failed
        )

        self.results_status.setText(
            "Searching..."
        )

        self.search_pool.start(
            task
        )

    @Slot(object)
    def handle_search_finished(
        self,
        result,
    ):
        if (
            result["request_id"]
            != self.latest_search_id
        ):
            return

        rows = result[
            "rows"
        ]

        total_results = result[
            "total_results"
        ]

        self.results_model.set_rows(
            rows
        )

        if total_results > len(
            rows
        ):
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

    @Slot(object)
    def handle_search_failed(
        self,
        result,
    ):
        if (
            result["request_id"]
            != self.latest_search_id
        ):
            return

        self.results_status.setText(
            f"Search failed: "
            f"{result['error']}"
        )

    # ========================================================
    # Index information
    # ========================================================

    def refresh_index_status(self):
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

        database_path = (
            get_database_path()
        )

        try:
            database_size = os.path.getsize(
                database_path
            )

        except OSError:
            database_size = 0

        if root_count == 0:
            self.index_status.setText(
                "No locations indexed yet."
            )

            return

        location_word = (
            "location"
            if root_count == 1
            else "locations"
        )

        self.index_status.setText(
            f"{file_count:,} files indexed across "
            f"{root_count:,} {location_word} · "
            f"Index size "
            f"{self.format_size(database_size)}"
        )
    # ========================================================
    # Selected file
    # ========================================================

    def get_selected_path(self):
        selection_model = (
            self.results_table
            .selectionModel()
        )

        if selection_model is None:
            return None

        selected_rows = (
            selection_model
            .selectedRows()
        )

        if not selected_rows:
            return None

        row = selected_rows[
            0
        ].row()

        return self.results_model.get_path(
            row
        )

    def update_action_buttons(
        self,
        *_args,
    ):
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

    # ========================================================
    # File actions
    # ========================================================

    def copy_selected_path(self):
        path = self.get_selected_path()

        if not path:
            return

        QApplication.clipboard().setText(
            path
        )

        self.results_status.setText(
            "Path copied to clipboard"
        )

    def open_selected(self):
        path = self.get_selected_path()

        if (
            not path
            or not os.path.exists(
                path
            )
        ):
            return

        try:
            os.startfile(
                path
            )

        except OSError:
            pass

    def open_selected_folder(self):
        path = self.get_selected_path()

        if not path:
            return

        if not os.path.exists(
            path
        ):
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
    # Shutdown
    # ========================================================

    def shutdown_workers(self):
        self.search_timer.stop()

        # Discard any queued searches.
        self.search_pool.clear()

        if (
            self.index_thread is not None
            and self.index_thread.isRunning()
        ):
            self.index_thread.requestInterruption()

            self.index_thread.quit()

            self.index_thread.wait(
                1500
            )

        # Give an active SQL query a moment to finish.
        self.search_pool.waitForDone(
            1000
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