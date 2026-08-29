import datetime
import hashlib
import os
import re
import subprocess

from send2trash import send2trash

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
    get_index_counts,
)


# ============================================================
# Duplicate scanner
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

            # Only files sharing a size can possibly be exact duplicates.
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

            size_groups = {}
            skipped_count = 0

            # ------------------------------------------------
            # Validate indexed files and collect timestamps
            # ------------------------------------------------

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

                    stat = os.stat(path)

                    if stat.st_size != size:
                        skipped_count += 1
                        continue

                    created = getattr(
                        stat,
                        "st_birthtime",
                        stat.st_ctime,
                    )

                    accessed = stat.st_atime
                    modified = stat.st_mtime

                except (
                    PermissionError,
                    FileNotFoundError,
                    OSError,
                ):
                    skipped_count += 1
                    continue

                size_groups.setdefault(
                    size,
                    [],
                ).append(
                    {
                        "path": path,
                        "name": name,
                        "parent": parent,
                        "created": created,
                        "accessed": accessed,
                        "modified": modified,
                    }
                )

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
            # Stage 1 — quick content fingerprint
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
                        [],
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
            # Stage 2 — full SHA-256 verification
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
                        [],
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
            # Confirm duplicate groups + choose keeper
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

                keeper = self.choose_keeper(
                    files
                )

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
                        "keeper_path": keeper["path"],
                    }
                )

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

    # ========================================================
    # Keeper recommendation
    # ========================================================

    @staticmethod
    def filename_penalty(name):
        """
        Lower score = more likely to be the original filename.
        """

        stem, _extension = os.path.splitext(
            name
        )

        penalty = 0

        duplicate_patterns = [
            r"\(\d+\)$",
            r"\s-\scopy(?:\s\d+)?$",
            r"\scopy(?:\s\d+)?$",
            r"_copy(?:_\d+)?$",
        ]

        for pattern in duplicate_patterns:
            if re.search(
                pattern,
                stem,
                re.IGNORECASE,
            ):
                penalty += 10

        return penalty

    @classmethod
    def choose_keeper(
        cls,
        files,
    ):
        """
        Preference order:

        1. Cleaner filename
        2. Oldest creation time
        3. Most recently accessed
        4. Stable path fallback

        Access time is intentionally only a tiebreaker because
        Windows/NTFS access timestamps are not always reliable.
        """

        return min(
            files,
            key=lambda file_info: (
                cls.filename_penalty(
                    file_info["name"]
                ),
                file_info["created"],
                -file_info["accessed"],
                file_info["path"].lower(),
            ),
        )

    # ========================================================
    # Hashing
    # ========================================================

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
            digest.update(
                file.read(
                    self.QUICK_HASH_SIZE
                )
            )

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
# Recycle Bin worker
# ============================================================

class CleanupWorker(QObject):
    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        paths,
    ):
        super().__init__()

        self.paths = paths

    @Slot()
    def cleanup(self):
        successful = []
        failed = []

        try:
            total = len(
                self.paths
            )

            for index, path in enumerate(
                self.paths,
                start=1,
            ):
                if (
                    QThread.currentThread()
                    .isInterruptionRequested()
                ):
                    return

                try:
                    if not os.path.exists(path):
                        failed.append(
                            (
                                path,
                                "File no longer exists",
                            )
                        )

                        continue

                    send2trash(
                        path
                    )

                    successful.append(
                        path
                    )

                except Exception as error:
                    failed.append(
                        (
                            path,
                            str(error),
                        )
                    )

                self.progress.emit(
                    {
                        "processed": index,
                        "total": total,
                    }
                )

            # Remove successfully recycled files from the index.
            if successful:
                connection = connect_database()

                try:
                    connection.executemany(
                        """
                        DELETE FROM files
                        WHERE path = ?
                        """,
                        [
                            (path,)
                            for path
                            in successful
                        ],
                    )

                    connection.commit()

                finally:
                    connection.close()

            self.finished.emit(
                {
                    "successful": successful,
                    "failed": failed,
                }
            )

        except Exception as error:
            self.failed.emit(
                str(error)
            )


# ============================================================
# Files page
# ============================================================

class FilesPage(QWidget):
    def __init__(self):
        super().__init__()

        self.scan_thread = None
        self.scan_worker = None

        self.cleanup_thread = None
        self.cleanup_worker = None

        self.duplicate_groups = []

        self.updating_table = False
        self.rescan_after_cleanup = False

        self.setup_ui()
        self.refresh_index_info()

        app = QApplication.instance()

        if app is not None:
            app.aboutToQuit.connect(
                self.shutdown_workers
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
            "Review exact duplicates and safely clean redundant copies."
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
            "Nothing is ever permanently deleted."
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
        # Summary
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
        # File actions
        # ----------------------------------------------------

        file_actions = QHBoxLayout()

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

        file_actions.addWidget(
            self.result_status
        )

        file_actions.addStretch()

        file_actions.addWidget(
            self.copy_path_button
        )

        file_actions.addWidget(
            self.open_button
        )

        file_actions.addWidget(
            self.folder_button
        )

        layout.addLayout(
            file_actions
        )

        # ----------------------------------------------------
        # Cleanup actions
        # ----------------------------------------------------

        cleanup_actions = QHBoxLayout()

        self.selection_status = QLabel(
            "0 files selected · 0 B"
        )

        self.selection_status.setObjectName(
            "searchStatus"
        )

        self.select_all_button = QPushButton(
            "Select All Duplicates"
        )

        self.select_all_button.setObjectName(
            "secondaryButton"
        )

        self.select_all_button.setEnabled(
            False
        )

        self.select_all_button.clicked.connect(
            self.select_all_duplicates
        )

        self.clear_selection_button = QPushButton(
            "Clear Selection"
        )

        self.clear_selection_button.setObjectName(
            "secondaryButton"
        )

        self.clear_selection_button.setEnabled(
            False
        )

        self.clear_selection_button.clicked.connect(
            self.clear_cleanup_selection
        )

        self.make_keeper_button = QPushButton(
            "Make Keeper"
        )

        self.make_keeper_button.setObjectName(
            "secondaryButton"
        )

        self.make_keeper_button.setEnabled(
            False
        )

        self.make_keeper_button.clicked.connect(
            self.make_selected_keeper
        )

        self.cleanup_button = QPushButton(
            "Move Selected to Recycle Bin"
        )

        self.cleanup_button.setObjectName(
            "primaryButton"
        )

        self.cleanup_button.setEnabled(
            False
        )

        self.cleanup_button.clicked.connect(
            self.recycle_selected
        )

        cleanup_actions.addWidget(
            self.selection_status
        )

        cleanup_actions.addStretch()

        cleanup_actions.addWidget(
            self.select_all_button
        )

        cleanup_actions.addWidget(
            self.clear_selection_button
        )

        cleanup_actions.addWidget(
            self.make_keeper_button
        )

        cleanup_actions.addWidget(
            self.cleanup_button
        )

        layout.addLayout(
            cleanup_actions
        )

        # ----------------------------------------------------
        # Results table
        # ----------------------------------------------------

        self.results_table = QTableWidget(
            0,
            7,
        )

        self.results_table.setObjectName(
            "searchResults"
        )

        self.results_table.setHorizontalHeaderLabels(
            [
                "Remove",
                "Group",
                "Status",
                "Name",
                "Size",
                "Folder",
                "Created",
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

        self.results_table.itemChanged.connect(
            self.handle_item_changed
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
            QHeaderView.ResizeMode.ResizeToContents,
        )

        header_view.setSectionResizeMode(
            2,
            QHeaderView.ResizeMode.ResizeToContents,
        )

        header_view.setSectionResizeMode(
            3,
            QHeaderView.ResizeMode.Stretch,
        )

        header_view.setSectionResizeMode(
            4,
            QHeaderView.ResizeMode.ResizeToContents,
        )

        header_view.setSectionResizeMode(
            5,
            QHeaderView.ResizeMode.Stretch,
        )

        header_view.setSectionResizeMode(
            6,
            QHeaderView.ResizeMode.ResizeToContents,
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
    # Index information
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
            (
                file_count,
                root_count,
            ) = get_index_counts(
                connection
            )

        finally:
            connection.close()

        if root_count == 0:
            self.index_status.setText(
                "No locations indexed yet. "
                "Index a location in Search first."
            )

            self.scan_button.setEnabled(
                False
            )

            return

        if file_count == 0:
            self.index_status.setText(
                f"{root_count:,} indexed "
                f"location{'' if root_count == 1 else 's'} · "
                "no files currently indexed"
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
    # Duplicate scanning
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

        self.cleanup_button.setEnabled(
            False
        )

        self.select_all_button.setEnabled(
            False
        )

        self.clear_selection_button.setEnabled(
            False
        )

        self.summary_container.hide()

        self.duplicate_groups = []

        self.results_table.setRowCount(
            0
        )

        self.selection_status.setText(
            "0 files selected · 0 B"
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
        self.scan_status.setText(
            f"{progress['phase']}... "
            f"{progress['processed']:,} / "
            f"{progress['total']:,} files · "
            f"{progress['skipped']:,} skipped"
        )

    @Slot(object)
    def handle_scan_finished(
        self,
        results,
    ):
        self.scan_button.setEnabled(
            True
        )

        self.duplicate_groups = (
            results["groups"]
        )

        self.groups_value.setText(
            f"{len(self.duplicate_groups):,}"
        )

        self.copies_value.setText(
            f"{results['duplicate_copies']:,}"
        )

        self.savings_value.setText(
            self.format_size(
                results["potential_savings"]
            )
        )

        self.summary_container.show()

        self.populate_results(
            self.duplicate_groups
        )

        has_groups = bool(
            self.duplicate_groups
        )

        self.select_all_button.setEnabled(
            has_groups
        )

        self.clear_selection_button.setEnabled(
            has_groups
        )

        self.scan_status.setText(
            f"Scan complete · "
            f"{results['candidate_files']:,} candidate files checked · "
            f"{results['skipped']:,} skipped"
        )

        if has_groups:
            self.result_status.setText(
                f"{len(self.duplicate_groups):,} exact duplicate "
                f"group{'' if len(self.duplicate_groups) == 1 else 's'}"
            )

        else:
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

    # ========================================================
    # Result table
    # ========================================================

    def populate_results(
        self,
        groups,
        checked_paths=None,
    ):
        if checked_paths is None:
            checked_paths = set()

        row_count = sum(
            len(group["files"])
            for group in groups
        )

        self.updating_table = True

        self.results_table.setUpdatesEnabled(
            False
        )

        self.results_table.setRowCount(
            row_count
        )

        row = 0

        for group_index, group in enumerate(
            groups
        ):
            group_number = (
                group_index + 1
            )

            keeper_path = (
                group["keeper_path"]
            )

            # Show keeper first.
            ordered_files = sorted(
                group["files"],
                key=lambda file_info:
                    file_info["path"] != keeper_path,
            )

            for file_info in ordered_files:
                path = file_info[
                    "path"
                ]

                is_keeper = (
                    path == keeper_path
                )

                # --------------------------------------------
                # Remove checkbox
                # --------------------------------------------

                remove_item = QTableWidgetItem()

                remove_item.setData(
                    Qt.ItemDataRole.UserRole,
                    group["size"],
                )

                if is_keeper:
                    remove_item.setText(
                        "—"
                    )

                    remove_item.setFlags(
                        Qt.ItemFlag.ItemIsEnabled
                        | Qt.ItemFlag.ItemIsSelectable
                    )

                else:
                    remove_item.setFlags(
                        Qt.ItemFlag.ItemIsEnabled
                        | Qt.ItemFlag.ItemIsSelectable
                        | Qt.ItemFlag.ItemIsUserCheckable
                    )

                    remove_item.setCheckState(
                        Qt.CheckState.Checked
                        if path in checked_paths
                        else Qt.CheckState.Unchecked
                    )

                # --------------------------------------------
                # Group
                # --------------------------------------------

                group_item = QTableWidgetItem(
                    f"#{group_number}"
                )

                group_item.setData(
                    Qt.ItemDataRole.UserRole,
                    group_index,
                )

                # --------------------------------------------
                # Status
                # --------------------------------------------

                status_item = QTableWidgetItem(
                    "Suggested keep"
                    if is_keeper
                    else "Duplicate"
                )

                if is_keeper:
                    status_item.setToolTip(
                        "SysDeck recommends keeping this copy "
                        "based on filename and file timestamps."
                    )

                # --------------------------------------------
                # File data
                # --------------------------------------------

                name_item = QTableWidgetItem(
                    file_info["name"]
                )

                name_item.setData(
                    Qt.ItemDataRole.UserRole,
                    path,
                )

                name_item.setData(
                    Qt.ItemDataRole.UserRole + 1,
                    group_index,
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

                created_item = QTableWidgetItem(
                    self.format_timestamp(
                        file_info["created"]
                    )
                )

                self.results_table.setItem(
                    row,
                    0,
                    remove_item,
                )

                self.results_table.setItem(
                    row,
                    1,
                    group_item,
                )

                self.results_table.setItem(
                    row,
                    2,
                    status_item,
                )

                self.results_table.setItem(
                    row,
                    3,
                    name_item,
                )

                self.results_table.setItem(
                    row,
                    4,
                    size_item,
                )

                self.results_table.setItem(
                    row,
                    5,
                    folder_item,
                )

                self.results_table.setItem(
                    row,
                    6,
                    created_item,
                )

                row += 1

        self.results_table.setUpdatesEnabled(
            True
        )

        self.results_table.viewport().update()

        self.updating_table = False

        self.update_action_buttons()
        self.update_selection_status()

    def handle_item_changed(
        self,
        item,
    ):
        if self.updating_table:
            return

        if item.column() != 0:
            return

        self.update_selection_status()

    # ========================================================
    # Selection
    # ========================================================

    def select_all_duplicates(self):
        self.updating_table = True

        for row in range(
            self.results_table.rowCount()
        ):
            item = self.results_table.item(
                row,
                0,
            )

            if item is None:
                continue

            if (
                item.flags()
                & Qt.ItemFlag.ItemIsUserCheckable
            ):
                item.setCheckState(
                    Qt.CheckState.Checked
                )

        self.updating_table = False

        self.update_selection_status()

    def clear_cleanup_selection(self):
        self.updating_table = True

        for row in range(
            self.results_table.rowCount()
        ):
            item = self.results_table.item(
                row,
                0,
            )

            if item is None:
                continue

            if (
                item.flags()
                & Qt.ItemFlag.ItemIsUserCheckable
            ):
                item.setCheckState(
                    Qt.CheckState.Unchecked
                )

        self.updating_table = False

        self.update_selection_status()

    def get_checked_paths(self):
        selected = []

        for row in range(
            self.results_table.rowCount()
        ):
            remove_item = (
                self.results_table.item(
                    row,
                    0,
                )
            )

            name_item = (
                self.results_table.item(
                    row,
                    3,
                )
            )

            if (
                remove_item is None
                or name_item is None
            ):
                continue

            if (
                remove_item.flags()
                & Qt.ItemFlag.ItemIsUserCheckable
                and remove_item.checkState()
                == Qt.CheckState.Checked
            ):
                path = name_item.data(
                    Qt.ItemDataRole.UserRole
                )

                size = remove_item.data(
                    Qt.ItemDataRole.UserRole
                )

                selected.append(
                    (
                        path,
                        size,
                    )
                )

        return selected

    def update_selection_status(self):
        selected = (
            self.get_checked_paths()
        )

        count = len(
            selected
        )

        total_size = sum(
            size
            for _path, size
            in selected
        )

        self.selection_status.setText(
            f"{count:,} file"
            f"{'' if count == 1 else 's'} selected · "
            f"{self.format_size(total_size)}"
        )

        self.cleanup_button.setEnabled(
            count > 0
        )

    # ========================================================
    # Manual keeper selection
    # ========================================================

    def make_selected_keeper(self):
        selected = (
            self.get_selected_info()
        )

        if selected is None:
            return

        path, group_index = selected

        group = self.duplicate_groups[
            group_index
        ]

        if path == group["keeper_path"]:
            return

        checked_paths = {
            selected_path
            for selected_path, _size
            in self.get_checked_paths()
        }

        # The new keeper can never remain selected for cleanup.
        checked_paths.discard(
            path
        )

        group["keeper_path"] = (
            path
        )

        self.populate_results(
            self.duplicate_groups,
            checked_paths,
        )

        self.result_status.setText(
            "Keeper changed"
        )

    # ========================================================
    # Recycle Bin cleanup
    # ========================================================

    def recycle_selected(self):
        selected = (
            self.get_checked_paths()
        )

        if not selected:
            return

        paths = [
            path
            for path, _size
            in selected
        ]

        total_size = sum(
            size
            for _path, size
            in selected
        )

        message = (
            f"Move {len(paths):,} file"
            f"{'' if len(paths) == 1 else 's'} "
            f"({self.format_size(total_size)}) "
            f"to the Windows Recycle Bin?\n\n"
            "The suggested keeper in each group will remain untouched."
        )

        confirmation = QMessageBox.question(
            self,
            "Move duplicates to Recycle Bin",
            message,
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if (
            confirmation
            != QMessageBox.StandardButton.Yes
        ):
            return

        self.start_cleanup(
            paths
        )

    def start_cleanup(
        self,
        paths,
    ):
        if (
            self.cleanup_thread is not None
            and self.cleanup_thread.isRunning()
        ):
            return

        self.set_cleanup_controls_enabled(
            False
        )

        self.scan_status.setText(
            f"Moving {len(paths):,} selected files "
            "to Recycle Bin..."
        )

        self.cleanup_thread = QThread(
            self
        )

        self.cleanup_worker = CleanupWorker(
            paths
        )

        self.cleanup_worker.moveToThread(
            self.cleanup_thread
        )

        self.cleanup_thread.started.connect(
            self.cleanup_worker.cleanup
        )

        self.cleanup_worker.progress.connect(
            self.handle_cleanup_progress
        )

        self.cleanup_worker.finished.connect(
            self.handle_cleanup_finished
        )

        self.cleanup_worker.failed.connect(
            self.handle_cleanup_failed
        )

        self.cleanup_worker.finished.connect(
            self.cleanup_thread.quit
        )

        self.cleanup_worker.failed.connect(
            self.cleanup_thread.quit
        )

        self.cleanup_worker.finished.connect(
            self.cleanup_worker.deleteLater
        )

        self.cleanup_worker.failed.connect(
            self.cleanup_worker.deleteLater
        )

        self.cleanup_thread.finished.connect(
            self.cleanup_cleanup_thread
        )

        self.cleanup_thread.start()

    @Slot(object)
    def handle_cleanup_progress(
        self,
        progress,
    ):
        self.scan_status.setText(
            f"Moving to Recycle Bin... "
            f"{progress['processed']:,} / "
            f"{progress['total']:,}"
        )

    @Slot(object)
    def handle_cleanup_finished(
        self,
        results,
    ):
        successful = results[
            "successful"
        ]

        failed = results[
            "failed"
        ]

        self.refresh_index_info()

        if failed:
            self.scan_status.setText(
                f"Moved {len(successful):,} files to Recycle Bin · "
                f"{len(failed):,} failed"
            )

            failed_preview = "\n".join(
                path
                for path, _error
                in failed[:5]
            )

            QMessageBox.warning(
                self,
                "Some files could not be moved",
                f"{len(failed):,} file"
                f"{'' if len(failed) == 1 else 's'} "
                "could not be moved.\n\n"
                f"{failed_preview}",
            )

        else:
            self.scan_status.setText(
                f"Moved {len(successful):,} files "
                "to Recycle Bin."
            )

        self.rescan_after_cleanup = (
            len(successful) > 0
        )

    @Slot(str)
    def handle_cleanup_failed(
        self,
        error,
    ):
        self.scan_status.setText(
            f"Cleanup failed: {error}"
        )

        self.rescan_after_cleanup = False

        self.set_cleanup_controls_enabled(
            True
        )

    def cleanup_cleanup_thread(self):
        if self.cleanup_thread is not None:
            self.cleanup_thread.deleteLater()

        self.cleanup_thread = None
        self.cleanup_worker = None

        should_rescan = (
            self.rescan_after_cleanup
        )

        self.rescan_after_cleanup = False

        if should_rescan:
            QTimer.singleShot(
                100,
                self.start_duplicate_scan,
            )

        else:
            self.set_cleanup_controls_enabled(
                True
            )

    def set_cleanup_controls_enabled(
        self,
        enabled,
    ):
        has_groups = bool(
            self.duplicate_groups
        )

        self.scan_button.setEnabled(
            enabled
        )

        self.select_all_button.setEnabled(
            enabled and has_groups
        )

        self.clear_selection_button.setEnabled(
            enabled and has_groups
        )

        self.make_keeper_button.setEnabled(
            enabled
            and self.get_selected_info()
            is not None
        )

        if enabled:
            self.update_selection_status()

        else:
            self.cleanup_button.setEnabled(
                False
            )

    # ========================================================
    # Selected row
    # ========================================================

    def get_selected_info(self):
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

        name_item = (
            self.results_table.item(
                row,
                3,
            )
        )

        if name_item is None:
            return None

        path = name_item.data(
            Qt.ItemDataRole.UserRole
        )

        group_index = name_item.data(
            Qt.ItemDataRole.UserRole + 1
        )

        if (
            path is None
            or group_index is None
        ):
            return None

        return (
            path,
            group_index,
        )

    def get_selected_path(self):
        selected = (
            self.get_selected_info()
        )

        if selected is None:
            return None

        return selected[0]

    def update_action_buttons(self):
        selected = (
            self.get_selected_info()
        )

        has_selection = (
            selected is not None
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

        if not has_selection:
            self.make_keeper_button.setEnabled(
                False
            )

            return

        path, group_index = selected

        is_keeper = (
            path
            == self.duplicate_groups[
                group_index
            ]["keeper_path"]
        )

        cleanup_running = (
            self.cleanup_thread is not None
            and self.cleanup_thread.isRunning()
        )

        self.make_keeper_button.setEnabled(
            not is_keeper
            and not cleanup_running
        )

    # ========================================================
    # Normal file actions
    # ========================================================

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
    # Shutdown
    # ========================================================

    def shutdown_workers(self):
        for thread in (
            self.scan_thread,
            self.cleanup_thread,
        ):
            if (
                thread is not None
                and thread.isRunning()
            ):
                thread.requestInterruption()
                thread.quit()
                thread.wait(
                    1500
                )

    # ========================================================
    # Formatting
    # ========================================================

    @staticmethod
    def format_timestamp(
        timestamp,
    ):
        try:
            return (
                datetime.datetime
                .fromtimestamp(
                    timestamp
                )
                .strftime(
                    "%Y-%m-%d %H:%M"
                )
            )

        except (
            OSError,
            OverflowError,
            ValueError,
        ):
            return "Unknown"

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