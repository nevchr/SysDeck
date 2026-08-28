import hashlib
import os
import subprocess

from PySide6.QtCore import (
    QObject,
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
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.database import connect_database


# ============================================================
# Background duplicate scanner
# ============================================================

class DuplicateScanWorker(QObject):
    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    QUICK_HASH_SIZE = 64 * 1024

    @Slot()
    def scan(self):
        connection = None

        try:
            connection = connect_database()

            indexed_count = connection.execute(
                """
                SELECT COUNT(*)
                FROM files
                """
            ).fetchone()[0]

            if indexed_count == 0:
                self.failed.emit(
                    "No files are indexed. "
                    "Index a folder in Search first."
                )
                return

            # Only retrieve files whose size is shared by
            # at least one other indexed file.
            rows = connection.execute(
                """
                SELECT
                    files.size,
                    files.path,
                    files.name,
                    files.parent
                FROM files
                INNER JOIN (
                    SELECT size
                    FROM files
                    WHERE size > 0
                    GROUP BY size
                    HAVING COUNT(*) > 1
                ) AS candidates
                    ON files.size = candidates.size
                ORDER BY files.size DESC
                """
            ).fetchall()

            connection.close()
            connection = None

            # ------------------------------------------------
            # Group potential duplicates by file size
            # ------------------------------------------------

            size_groups = {}

            skipped_count = 0

            for size, path, name, parent in rows:
                if (
                    QThread.currentThread()
                    .isInterruptionRequested()
                ):
                    return

                try:
                    if not os.path.isfile(path):
                        skipped_count += 1
                        continue

                    # The index may be stale. If the current
                    # size differs, don't compare it using the
                    # old indexed metadata.
                    if os.path.getsize(path) != size:
                        skipped_count += 1
                        continue

                except OSError:
                    skipped_count += 1
                    continue

                size_groups.setdefault(
                    size,
                    []
                ).append(
                    {
                        "path": path,
                        "name": name,
                        "parent": parent,
                    }
                )

            # Remove groups that no longer contain two
            # accessible files.
            size_groups = {
                size: files
                for size, files
                in size_groups.items()
                if len(files) >= 2
            }

            candidate_count = sum(
                len(files)
                for files
                in size_groups.values()
            )

            if candidate_count == 0:
                self.finished.emit(
                    {
                        "groups": [],
                        "duplicate_copies": 0,
                        "potential_savings": 0,
                        "candidate_files": 0,
                        "skipped": skipped_count,
                    }
                )
                return

            # ------------------------------------------------
            # Stage 1:
            # Quick hash first + last pieces of files.
            # This avoids fully hashing every same-sized file.
            # ------------------------------------------------

            quick_groups = {}

            processed = 0

            for size, files in size_groups.items():
                for file_info in files:
                    if (
                        QThread.currentThread()
                        .isInterruptionRequested()
                    ):
                        return

                    try:
                        signature = self.quick_hash(
                            file_info["path"],
                            size,
                        )

                    except (
                        PermissionError,
                        FileNotFoundError,
                        OSError,
                    ):
                        skipped_count += 1
                        processed += 1
                        continue

                    key = (
                        size,
                        signature,
                    )

                    quick_groups.setdefault(
                        key,
                        []
                    ).append(
                        file_info
                    )

                    processed += 1

                    if (
                        processed % 25 == 0
                        or processed == candidate_count
                    ):
                        self.progress.emit(
                            {
                                "phase": "Comparing",
                                "processed": processed,
                                "total": candidate_count,
                                "skipped": skipped_count,
                            }
                        )

            # Only quick-hash groups with 2+ files need
            # expensive full SHA-256 verification.
            verification_groups = {
                key: files
                for key, files
                in quick_groups.items()
                if len(files) >= 2
            }

            verify_total = sum(
                len(files)
                for files
                in verification_groups.values()
            )

            # ------------------------------------------------
            # Stage 2:
            # Full SHA-256 verification.
            # ------------------------------------------------

            full_hash_groups = {}

            verified = 0

            for (
                size,
                _quick_signature,
            ), files in verification_groups.items():

                for file_info in files:
                    if (
                        QThread.currentThread()
                        .isInterruptionRequested()
                    ):
                        return

                    try:
                        full_hash = self.full_hash(
                            file_info["path"]
                        )

                    except (
                        PermissionError,
                        FileNotFoundError,
                        OSError,
                    ):
                        skipped_count += 1
                        verified += 1
                        continue

                    key = (
                        size,
                        full_hash,
                    )

                    full_hash_groups.setdefault(
                        key,
                        []
                    ).append(
                        file_info
                    )

                    verified += 1

                    if (
                        verified % 10 == 0
                        or verified == verify_total
                    ):
                        self.progress.emit(
                            {
                                "phase": "Verifying",
                                "processed": verified,
                                "total": verify_total,
                                "skipped": skipped_count,
                            }
                        )

            # ------------------------------------------------
            # Exact duplicate groups
            # ------------------------------------------------

            duplicate_groups = []

            duplicate_copies = 0
            potential_savings = 0

            for (
                size,
                full_hash,
            ), files in full_hash_groups.items():

                if len(files) < 2:
                    continue

                redundant_copies = (
                    len(files) - 1
                )

                wasted_space = (
                    size * redundant_copies
                )

                duplicate_copies += (
                    redundant_copies
                )

                potential_savings += (
                    wasted_space
                )

                duplicate_groups.append(
                    {
                        "size": size,
                        "hash": full_hash,
                        "files": files,
                        "copies": len(files),
                        "wasted": wasted_space,
                    }
                )

            # Most recoverable space first.
            duplicate_groups.sort(
                key=lambda group: (
                    group["wasted"],
                    group["size"],
                ),
                reverse=True,
            )

            self.finished.emit(
                {
                    "groups": duplicate_groups,
                    "duplicate_copies":
                        duplicate_copies,

                    "potential_savings":
                        potential_savings,

                    "candidate_files":
                        candidate_count,

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

    def quick_hash(
        self,
        path,
        size,
    ):
        digest = hashlib.blake2b(
            digest_size=16
        )

        with open(
            path,
            "rb",
        ) as file:
            first_chunk = file.read(
                self.QUICK_HASH_SIZE
            )

            digest.update(
                first_chunk
            )

            # For larger files, also inspect the end.
            if size > (
                self.QUICK_HASH_SIZE * 2
            ):
                file.seek(
                    -self.QUICK_HASH_SIZE,
                    os.SEEK_END,
                )

                digest.update(
                    file.read(
                        self.QUICK_HASH_SIZE
                    )
                )

        return digest.digest()

    @staticmethod
    def full_hash(path):
        digest = hashlib.sha256()

        with open(
            path,
            "rb",
        ) as file:
            while True:
                chunk = file.read(
                    1024 * 1024
                )

                if not chunk:
                    break

                digest.update(
                    chunk
                )

        return digest.hexdigest()


# ============================================================
# Files page
# ============================================================

class FilesPage(QWidget):
    def __init__(self):
        super().__init__()

        self.scan_thread = None
        self.scan_worker = None

        self.setup_ui()
        self.refresh_index_info()

        app = QApplication.instance()

        if app is not None:
            app.aboutToQuit.connect(
                self.shutdown_scanner
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
            18
        )

        # ----------------------------------------------------
        # Header
        # ----------------------------------------------------

        header = QHBoxLayout()

        header_text = QVBoxLayout()
        header_text.setSpacing(6)

        title = QLabel(
            "Files"
        )

        title.setObjectName(
            "pageTitle"
        )

        description = QLabel(
            "Find exact duplicate files using your existing SysDeck index."
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

        self.scan_button = QPushButton(
            "Find Duplicates"
        )

        self.scan_button.setObjectName(
            "primaryButton"
        )

        self.scan_button.clicked.connect(
            self.start_duplicate_scan
        )

        header.addLayout(
            header_text
        )

        header.addStretch()

        header.addWidget(
            self.scan_button
        )

        layout.addLayout(
            header
        )

        # ----------------------------------------------------
        # Status
        # ----------------------------------------------------

        self.index_status = QLabel(
            "Checking index..."
        )

        self.index_status.setObjectName(
            "searchStatus"
        )

        self.scan_status = QLabel(
            "Nothing is deleted automatically."
        )

        self.scan_status.setObjectName(
            "searchStatus"
        )

        layout.addWidget(
            self.index_status
        )

        layout.addWidget(
            self.scan_status
        )

        # ----------------------------------------------------
        # Summary cards
        # ----------------------------------------------------

        self.summary_container = QWidget()

        summary_layout = QGridLayout(
            self.summary_container
        )

        summary_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        summary_layout.setHorizontalSpacing(
            18
        )

        summary_layout.setColumnStretch(
            0,
            1,
        )

        summary_layout.setColumnStretch(
            1,
            1,
        )

        summary_layout.setColumnStretch(
            2,
            1,
        )

        self.groups_value = QLabel(
            "0"
        )

        self.copies_value = QLabel(
            "0"
        )

        self.savings_value = QLabel(
            "0 B"
        )

        summary_layout.addWidget(
            self.create_summary_card(
                "Duplicate Groups",
                self.groups_value,
            ),
            0,
            0,
        )

        summary_layout.addWidget(
            self.create_summary_card(
                "Redundant Copies",
                self.copies_value,
            ),
            0,
            1,
        )

        summary_layout.addWidget(
            self.create_summary_card(
                "Potential Savings",
                self.savings_value,
            ),
            0,
            2,
        )

        self.summary_container.hide()

        layout.addWidget(
            self.summary_container
        )

        # ----------------------------------------------------
        # Actions
        # ----------------------------------------------------

        action_row = QHBoxLayout()

        self.result_status = QLabel(
            "No scan results"
        )

        self.result_status.setObjectName(
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

        action_row.addWidget(
            self.result_status
        )

        action_row.addStretch()

        action_row.addWidget(
            self.copy_path_button
        )

        action_row.addWidget(
            self.open_button
        )

        action_row.addWidget(
            self.folder_button
        )

        layout.addLayout(
            action_row
        )

        # ----------------------------------------------------
        # Duplicate results
        # ----------------------------------------------------

        self.results_table = QTableWidget(
            0,
            4,
        )

        # Reuse Search's table styling.
        self.results_table.setObjectName(
            "searchResults"
        )

        self.results_table.setHorizontalHeaderLabels(
            [
                "Group",
                "Name",
                "Size",
                "Folder",
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
            QHeaderView.ResizeMode.ResizeToContents,
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
            QHeaderView.ResizeMode.Stretch,
        )

        layout.addWidget(
            self.results_table,
            1,
        )

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

        label = QLabel(
            title
        )

        label.setObjectName(
            "summaryTitle"
        )

        value.setObjectName(
            "summaryValue"
        )

        card_layout.addWidget(
            label
        )

        card_layout.addWidget(
            value
        )

        return card

    # ========================================================
    # Index info
    # ========================================================

    def showEvent(
        self,
        event,
    ):
        super().showEvent(
            event
        )

        self.refresh_index_info()

    def refresh_index_info(self):
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
                "No files indexed yet. "
                "Index a location in Search first."
            )

            self.scan_button.setEnabled(
                False
            )

            return

        self.scan_button.setEnabled(
            True
        )

        location_word = (
            "location"
            if root_count == 1
            else "locations"
        )

        self.index_status.setText(
            f"Using {file_count:,} indexed files across "
            f"{root_count:,} {location_word}"
        )

    # ========================================================
    # Duplicate scan
    # ========================================================

    def start_duplicate_scan(self):
        if (
            self.scan_thread is not None
            and self.scan_thread.isRunning()
        ):
            return

        self.scan_button.setEnabled(
            False
        )

        self.summary_container.hide()

        self.results_table.setRowCount(
            0
        )

        self.result_status.setText(
            "Scanning..."
        )

        self.scan_status.setText(
            "Finding same-sized files..."
        )

        self.scan_thread = QThread(
            self
        )

        self.scan_worker = (
            DuplicateScanWorker()
        )

        self.scan_worker.moveToThread(
            self.scan_thread
        )

        self.scan_thread.started.connect(
            self.scan_worker.scan
        )

        self.scan_worker.progress.connect(
            self.handle_scan_progress
        )

        self.scan_worker.finished.connect(
            self.handle_scan_finished
        )

        self.scan_worker.failed.connect(
            self.handle_scan_failed
        )

        self.scan_worker.finished.connect(
            self.scan_thread.quit
        )

        self.scan_worker.failed.connect(
            self.scan_thread.quit
        )

        self.scan_worker.finished.connect(
            self.scan_worker.deleteLater
        )

        self.scan_worker.failed.connect(
            self.scan_worker.deleteLater
        )

        self.scan_thread.finished.connect(
            self.cleanup_scan_thread
        )

        self.scan_thread.start()

    @Slot(object)
    def handle_scan_progress(
        self,
        progress,
    ):
        phase = progress[
            "phase"
        ]

        processed = progress[
            "processed"
        ]

        total = progress[
            "total"
        ]

        skipped = progress[
            "skipped"
        ]

        self.scan_status.setText(
            f"{phase}... "
            f"{processed:,} / {total:,} files · "
            f"{skipped:,} skipped"
        )

    @Slot(object)
    def handle_scan_finished(
        self,
        results,
    ):
        self.scan_button.setEnabled(
            True
        )

        groups = results[
            "groups"
        ]

        duplicate_copies = results[
            "duplicate_copies"
        ]

        potential_savings = results[
            "potential_savings"
        ]

        skipped = results[
            "skipped"
        ]

        candidate_files = results[
            "candidate_files"
        ]

        self.groups_value.setText(
            f"{len(groups):,}"
        )

        self.copies_value.setText(
            f"{duplicate_copies:,}"
        )

        self.savings_value.setText(
            self.format_size(
                potential_savings
            )
        )

        self.summary_container.show()

        self.populate_results(
            groups
        )

        if groups:
            self.scan_status.setText(
                f"Scan complete · "
                f"{candidate_files:,} candidate files checked · "
                f"{skipped:,} skipped"
            )

            self.result_status.setText(
                f"{len(groups):,} exact duplicate "
                f"group{'' if len(groups) == 1 else 's'}"
            )

        else:
            self.scan_status.setText(
                f"Scan complete · "
                f"{candidate_files:,} candidate files checked · "
                f"{skipped:,} skipped"
            )

            self.result_status.setText(
                "No exact duplicates found"
            )

    @Slot(str)
    def handle_scan_failed(
        self,
        error,
    ):
        self.scan_button.setEnabled(
            True
        )

        self.scan_status.setText(
            f"Duplicate scan failed: {error}"
        )

        self.result_status.setText(
            "Scan failed"
        )

    def cleanup_scan_thread(self):
        if self.scan_thread is not None:
            self.scan_thread.deleteLater()

        self.scan_thread = None
        self.scan_worker = None

    def shutdown_scanner(self):
        if (
            self.scan_thread is not None
            and self.scan_thread.isRunning()
        ):
            self.scan_thread.requestInterruption()

            self.scan_thread.quit()

            self.scan_thread.wait(
                1500
            )

    # ========================================================
    # Results
    # ========================================================

    def populate_results(
        self,
        groups,
    ):
        row_count = sum(
            len(group["files"])
            for group in groups
        )

        self.results_table.setUpdatesEnabled(
            False
        )

        self.results_table.setRowCount(
            row_count
        )

        row = 0

        for group_number, group in enumerate(
            groups,
            start=1,
        ):
            group_label = (
                f"#{group_number} "
                f"({group['copies']} copies)"
            )

            for file_info in group[
                "files"
            ]:
                path = file_info[
                    "path"
                ]

                group_item = QTableWidgetItem(
                    group_label
                )

                name_item = QTableWidgetItem(
                    file_info["name"]
                )

                name_item.setData(
                    Qt.ItemDataRole.UserRole,
                    path,
                )

                size_item = QTableWidgetItem(
                    self.format_size(
                        group["size"]
                    )
                )

                size_item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight
                    | Qt.AlignmentFlag.AlignVCenter
                )

                folder_item = QTableWidgetItem(
                    file_info["parent"]
                )

                folder_item.setToolTip(
                    file_info["parent"]
                )

                self.results_table.setItem(
                    row,
                    0,
                    group_item,
                )

                self.results_table.setItem(
                    row,
                    1,
                    name_item,
                )

                self.results_table.setItem(
                    row,
                    2,
                    size_item,
                )

                self.results_table.setItem(
                    row,
                    3,
                    folder_item,
                )

                row += 1

        self.results_table.setUpdatesEnabled(
            True
        )

        self.results_table.viewport().update()

        self.update_action_buttons()

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

        row = selected_rows[
            0
        ].row()

        item = self.results_table.item(
            row,
            1,
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

        QApplication.clipboard().setText(
            path
        )

        self.result_status.setText(
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
            os.startfile(
                path
            )

        except OSError:
            pass

    def open_selected_folder(self):
        path = self.get_selected_path()

        if (
            not path
            or not os.path.exists(path)
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