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
    QFileDialog,
    QFrame,
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

from ..core.database import connect_database


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

            # Replace the previous index for this same root.
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

                directories[:] = safe_directories

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
                        or now - last_progress_time >= 0.4
                    ):
                        self.progress.emit(
                            {
                                "indexed": indexed_count,
                                "skipped": skipped_count,
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
                    "root": self.root_folder,
                    "indexed": indexed_count,
                    "skipped": skipped_count,
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


class SearchPage(QWidget):
    def __init__(self):
        super().__init__()

        self.index_thread = None
        self.index_worker = None

        self.setup_ui()
        self.setup_search_timer()

        self.refresh_index_status()
        self.perform_search()

        app = QApplication.instance()

        if app is not None:
            app.aboutToQuit.connect(
                self.shutdown_indexer
            )

    def setup_ui(self):
        layout = QVBoxLayout(self)

        layout.setContentsMargins(
            46,
            40,
            46,
            40,
        )

        layout.setSpacing(18)

        # -----------------------------------------------------
        # Header
        # -----------------------------------------------------

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

        # -----------------------------------------------------
        # Index information
        # -----------------------------------------------------

        self.index_status = QLabel(
            "Checking index..."
        )

        self.index_status.setObjectName(
            "searchStatus"
        )

        layout.addWidget(
            self.index_status
        )

        # -----------------------------------------------------
        # Search box
        # -----------------------------------------------------

        self.search_input = QLineEdit()

        self.search_input.setObjectName(
            "searchInput"
        )

        self.search_input.setPlaceholderText(
            "Search files and folders..."
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

        # -----------------------------------------------------
        # Results toolbar
        # -----------------------------------------------------

        results_header = QHBoxLayout()

        self.results_status = QLabel(
            "No results"
        )

        self.results_status.setObjectName(
            "searchStatus"
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
            self.open_button
        )

        results_header.addWidget(
            self.folder_button
        )

        layout.addLayout(
            results_header
        )

        # -----------------------------------------------------
        # Results table
        # -----------------------------------------------------

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
            lambda _item: self.open_selected()
        )

        header_view = (
            self.results_table.horizontalHeader()
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
            200
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

        self.index_status.setText(
            f"Indexed {results['indexed']:,} files · "
            f"{results['skipped']:,} skipped"
        )

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
    # Search
    # ========================================================

    def queue_search(self):
        self.search_timer.start()

    def perform_search(self):
        query = (
            self.search_input.text().strip()
            if hasattr(
                self,
                "search_input",
            )
            else ""
        )

        connection = connect_database()

        try:
            if query:
                wildcard = (
                    f"%{query}%"
                )

                rows = connection.execute(
                    """
                    SELECT
                        name,
                        parent,
                        extension,
                        size,
                        modified,
                        path
                    FROM files
                    WHERE
                        name LIKE ? COLLATE NOCASE
                        OR path LIKE ? COLLATE NOCASE
                    ORDER BY
                        CASE
                            WHEN name LIKE ? COLLATE NOCASE
                            THEN 0
                            ELSE 1
                        END,
                        name COLLATE NOCASE
                    LIMIT 500
                    """,
                    (
                        wildcard,
                        wildcard,
                        wildcard,
                    ),
                ).fetchall()

            else:
                rows = connection.execute(
                    """
                    SELECT
                        name,
                        parent,
                        extension,
                        size,
                        modified,
                        path
                    FROM files
                    ORDER BY
                        modified DESC
                    LIMIT 250
                    """
                ).fetchall()

        finally:
            connection.close()

        self.populate_results(
            rows
        )

    def populate_results(
        self,
        rows,
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
                datetime.datetime.fromtimestamp(
                    modified
                ).strftime(
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

        self.results_status.setText(
            f"{len(rows):,} results"
        )

        self.update_action_buttons()

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

        if file_count == 0:
            self.index_status.setText(
                "No files indexed yet."
            )

        else:
            self.index_status.setText(
                f"{file_count:,} files indexed "
                f"across {root_count:,} location"
                f"{'' if root_count == 1 else 's'}."
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

        row = selected_rows[0].row()

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

        self.open_button.setEnabled(
            has_selection
        )

        self.folder_button.setEnabled(
            has_selection
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
                    os.path.normpath(path),
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
    def format_size(size):
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