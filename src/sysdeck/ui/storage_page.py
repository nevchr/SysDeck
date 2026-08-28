import heapq
import os
import string
import time

import psutil

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


# ============================================================
# Background folder scanner
# ============================================================

class StorageScanWorker(QObject):
    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, folder):
        super().__init__()
        self.folder = os.path.abspath(folder)

    @Slot()
    def scan(self):
        try:
            total_size = 0
            file_count = 0
            skipped_count = 0

            # Direct file size contained by each folder.
            folder_sizes = {}

            # Min-heap containing only the 10 largest files.
            largest_files = []

            last_progress_update = time.monotonic()

            def walk_error(_error):
                nonlocal skipped_count
                skipped_count += 1

            for current_root, directories, files in os.walk(
                self.folder,
                topdown=True,
                onerror=walk_error,
                followlinks=False,
            ):
                if (
                    QThread.currentThread()
                    .isInterruptionRequested()
                ):
                    return

                folder_sizes.setdefault(
                    current_root,
                    0,
                )

                # Don't traverse directory symlinks.
                safe_directories = []

                for directory in directories:
                    path = os.path.join(
                        current_root,
                        directory,
                    )

                    try:
                        if not os.path.islink(path):
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

                        size = os.path.getsize(
                            path
                        )

                    except (
                        PermissionError,
                        FileNotFoundError,
                        OSError,
                    ):
                        skipped_count += 1
                        continue

                    file_count += 1
                    total_size += size

                    folder_sizes[current_root] += size

                    file_entry = (
                        size,
                        path,
                    )

                    if len(largest_files) < 10:
                        heapq.heappush(
                            largest_files,
                            file_entry,
                        )

                    elif size > largest_files[0][0]:
                        heapq.heapreplace(
                            largest_files,
                            file_entry,
                        )

                    now = time.monotonic()

                    # Don't spam the UI thread with progress
                    # signals for every single file.
                    if (
                        file_count % 200 == 0
                        or now - last_progress_update >= 0.3
                    ):
                        self.progress.emit(
                            {
                                "files": file_count,
                                "size": total_size,
                                "skipped": skipped_count,
                            }
                        )

                        last_progress_update = now

            # ------------------------------------------------
            # Calculate cumulative folder sizes
            # ------------------------------------------------

            deepest_first = sorted(
                folder_sizes.keys(),
                key=lambda path: path.count(
                    os.sep
                ),
                reverse=True,
            )

            for folder in deepest_first:
                if (
                    QThread.currentThread()
                    .isInterruptionRequested()
                ):
                    return

                if (
                    os.path.normcase(folder)
                    == os.path.normcase(
                        self.folder
                    )
                ):
                    continue

                parent = os.path.dirname(
                    folder
                )

                if parent in folder_sizes:
                    folder_sizes[parent] += (
                        folder_sizes[folder]
                    )

            largest_folders = sorted(
                [
                    (size, path)
                    for path, size
                    in folder_sizes.items()
                    if (
                        path != self.folder
                        and size > 0
                    )
                ],
                reverse=True,
            )[:10]

            largest_files = sorted(
                largest_files,
                reverse=True,
            )

            results = {
                "root": self.folder,
                "files": file_count,
                "size": total_size,
                "skipped": skipped_count,
                "largest_files": largest_files,
                "largest_folders": largest_folders,
            }

            self.finished.emit(
                results
            )

        except Exception as error:
            self.failed.emit(
                str(error)
            )


# ============================================================
# Storage page
# ============================================================

class StoragePage(QWidget):
    def __init__(self):
        super().__init__()

        self.scan_thread = None
        self.scan_worker = None
        self.selected_folder = None

        self.setup_ui()
        self.refresh_drives()

        app = QApplication.instance()

        if app is not None:
            app.aboutToQuit.connect(
                self.shutdown_scan
            )

    # ========================================================
    # UI
    # ========================================================

    def setup_ui(self):
        outer_layout = QVBoxLayout(self)

        outer_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        scroll_area = QScrollArea()

        scroll_area.setWidgetResizable(
            True
        )

        scroll_area.setFrameShape(
            QFrame.Shape.NoFrame
        )

        content = QWidget()
        content.setObjectName(
            "storageContent"
        )

        layout = QVBoxLayout(
            content
        )

        layout.setContentsMargins(
            46,
            40,
            46,
            40,
        )

        layout.setSpacing(
            20
        )

        

        scroll_area.setWidget(
            content
        )

        outer_layout.addWidget(
            scroll_area
        )

        # ----------------------------------------------------
        # Header
        # ----------------------------------------------------

        header = QHBoxLayout()

        header_text = QVBoxLayout()
        header_text.setSpacing(6)

        title = QLabel(
            "Storage"
        )

        title.setObjectName(
            "pageTitle"
        )

        description = QLabel(
            "View drive usage and analyze storage across your computer."
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

        self.refresh_button = QPushButton(
            "Refresh"
        )

        self.refresh_button.setObjectName(
            "secondaryButton"
        )

        self.refresh_button.clicked.connect(
            self.refresh_drives
        )

        self.analyze_button = QPushButton(
            "Analyze Folder"
        )

        self.analyze_button.setObjectName(
            "primaryButton"
        )

        self.analyze_button.clicked.connect(
            self.choose_folder
        )

        header.addLayout(
            header_text
        )

        header.addStretch()

        header.addWidget(
            self.refresh_button
        )

        header.addWidget(
            self.analyze_button
        )

        layout.addLayout(
            header
        )

        # ----------------------------------------------------
        # Selected path
        # ----------------------------------------------------

        self.selected_folder_label = QLabel(
            "No folder selected"
        )

        self.selected_folder_label.setObjectName(
            "selectedPath"
        )

        self.selected_folder_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        layout.addWidget(
            self.selected_folder_label
        )

        # ----------------------------------------------------
        # Drive cards
        # ----------------------------------------------------

        self.drive_container = QWidget()

        self.drive_layout = QGridLayout(
            self.drive_container
        )

        self.drive_layout.setContentsMargins(
            0,
            4,
            0,
            0,
        )

        self.drive_layout.setHorizontalSpacing(
            18
        )

        self.drive_layout.setVerticalSpacing(
            18
        )

        self.drive_layout.setColumnStretch(
            0,
            1,
        )

        self.drive_layout.setColumnStretch(
            1,
            1,
        )

        layout.addWidget(
            self.drive_container
        )

        # ----------------------------------------------------
        # Scan status
        # ----------------------------------------------------

        self.scan_panel = QWidget()

        self.scan_panel.setObjectName(
            "scanPanel"
        )

        scan_layout = QVBoxLayout(
            self.scan_panel
        )

        scan_layout.setContentsMargins(
            18,
            14,
            18,
            14,
        )

        scan_layout.setSpacing(
            10
        )

        self.scan_status = QLabel(
            "Choose a folder to begin analysis."
        )

        self.scan_status.setObjectName(
            "scanStatus"
        )

        self.scan_progress = QProgressBar()

        self.scan_progress.setObjectName(
            "scanProgress"
        )

        # 0,0 creates an indeterminate/loading bar.
        self.scan_progress.setRange(
            0,
            0,
        )

        self.scan_progress.setTextVisible(
            False
        )

        self.scan_progress.hide()

        scan_layout.addWidget(
            self.scan_status
        )

        scan_layout.addWidget(
            self.scan_progress
        )

        layout.addWidget(
            self.scan_panel
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

        self.files_scanned_value = QLabel(
            "0"
        )

        self.total_size_value = QLabel(
            "0 B"
        )

        self.skipped_value = QLabel(
            "0"
        )

        summary_layout.addWidget(
            self.create_summary_card(
                "Files Scanned",
                self.files_scanned_value,
            ),
            0,
            0,
        )

        summary_layout.addWidget(
            self.create_summary_card(
                "Total Size",
                self.total_size_value,
            ),
            0,
            1,
        )

        summary_layout.addWidget(
            self.create_summary_card(
                "Skipped Items",
                self.skipped_value,
            ),
            0,
            2,
        )

        self.summary_container.hide()

        layout.addWidget(
            self.summary_container
        )

        # ----------------------------------------------------
        # Largest files / folders
        # ----------------------------------------------------

        self.results_container = QWidget()

        results_layout = QGridLayout(
            self.results_container
        )

        results_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        results_layout.setHorizontalSpacing(
            18
        )

        results_layout.setColumnStretch(
            0,
            1,
        )

        results_layout.setColumnStretch(
            1,
            1,
        )

        self.files_table = (
            self.create_results_table()
        )

        self.folders_table = (
            self.create_results_table()
        )

        results_layout.addWidget(
            self.create_result_card(
                "Largest Files",
                self.files_table,
            ),
            0,
            0,
        )

        results_layout.addWidget(
            self.create_result_card(
                "Largest Folders",
                self.folders_table,
            ),
            0,
            1,
        )

        self.results_container.hide()

        layout.addWidget(
            self.results_container
        )

        layout.addStretch()

    # ========================================================
    # Drive usage
    # ========================================================

    def refresh_drives(self):
        self.clear_drive_cards()

        drives = self.get_drives()

        for index, drive in enumerate(
            drives
        ):
            row = index // 2
            column = index % 2

            self.drive_layout.addWidget(
                self.create_drive_card(
                    drive
                ),
                row,
                column,
            )

    def get_drives(self):
        drives = []

        for letter in string.ascii_uppercase:
            path = f"{letter}:\\"

            if not os.path.exists(
                path
            ):
                continue

            try:
                usage = psutil.disk_usage(
                    path
                )

            except (
                PermissionError,
                OSError,
            ):
                continue

            drives.append(
                {
                    "letter": letter,
                    "total": usage.total,
                    "used": usage.used,
                    "free": usage.free,
                    "percent": usage.percent,
                }
            )

        return drives

    def create_drive_card(
        self,
        drive,
    ):
        card = QWidget()

        card.setObjectName(
            "driveCard"
        )

        card.setMinimumHeight(
            190
        )

        card.setMaximumHeight(
            220
        )

        card_layout = QVBoxLayout(
            card
        )

        card_layout.setContentsMargins(
            22,
            20,
            22,
            20,
        )

        card_layout.setSpacing(
            10
        )

        title_row = QHBoxLayout()

        drive_title = QLabel(
            f"Local Disk ({drive['letter']}:)"
        )

        drive_title.setObjectName(
            "driveTitle"
        )

        percent = QLabel(
            f"{drive['percent']:.0f}%"
        )

        percent.setObjectName(
            "drivePercent"
        )

        title_row.addWidget(
            drive_title
        )

        title_row.addStretch()

        title_row.addWidget(
            percent
        )

        usage = QLabel(
            f"{self.format_size(drive['used'])} used of "
            f"{self.format_size(drive['total'])}"
        )

        usage.setObjectName(
            "driveUsageText"
        )

        progress = QProgressBar()

        progress.setObjectName(
            "storageProgress"
        )

        progress.setRange(
            0,
            100,
        )

        progress.setValue(
            int(drive["percent"])
        )

        progress.setTextVisible(
            False
        )

        free = QLabel(
            f"{self.format_size(drive['free'])} free"
        )

        free.setObjectName(
            "driveFreeText"
        )

        card_layout.addLayout(
            title_row
        )

        card_layout.addWidget(
            usage
        )

        card_layout.addWidget(
            progress
        )

        card_layout.addWidget(
            free
        )

        return card

    # ========================================================
    # Scan UI components
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

    def create_result_card(
        self,
        title,
        table,
    ):
        card = QWidget()

        card.setObjectName(
            "resultCard"
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
            12
        )

        label = QLabel(
            title
        )

        label.setObjectName(
            "resultTitle"
        )

        card_layout.addWidget(
            label
        )

        card_layout.addWidget(
            table
        )

        return card

    def create_results_table(self):
        table = QTableWidget(
            0,
            2,
        )

        table.setObjectName(
            "storageResultTable"
        )

        table.setHorizontalHeaderLabels(
            [
                "Path",
                "Size",
            ]
        )

        table.verticalHeader().hide()

        table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )

        table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )

        table.setShowGrid(
            False
        )

        table.setAlternatingRowColors(
            True
        )

        table.setMinimumHeight(
            320
        )

        header = table.horizontalHeader()

        header.setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.Stretch,
        )

        header.setSectionResizeMode(
            1,
            QHeaderView.ResizeMode.ResizeToContents,
        )

        return table

    # ========================================================
    # Folder selection + scanning
    # ========================================================

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Choose Folder to Analyze",
        )

        if not folder:
            return

        self.selected_folder = folder

        self.selected_folder_label.setText(
            folder
        )

        self.selected_folder_label.setToolTip(
            folder
        )

        self.start_scan(
            folder
        )

    def start_scan(
        self,
        folder,
    ):
        if (
            self.scan_thread is not None
            and self.scan_thread.isRunning()
        ):
            return

        self.results_container.hide()
        self.summary_container.hide()

        self.files_table.setRowCount(
            0
        )

        self.folders_table.setRowCount(
            0
        )

        self.analyze_button.setEnabled(
            False
        )

        self.refresh_button.setEnabled(
            False
        )

        self.scan_progress.show()

        self.scan_status.setText(
            "Starting scan..."
        )

        self.scan_thread = QThread(
            self
        )

        self.scan_worker = StorageScanWorker(
            folder
        )

        self.scan_worker.moveToThread(
            self.scan_thread
        )

        self.scan_thread.started.connect(
            self.scan_worker.scan
        )

        self.scan_worker.progress.connect(
            self.update_scan_progress
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
    def update_scan_progress(
        self,
        progress,
    ):
        self.scan_status.setText(
            f"Scanning... "
            f"{progress['files']:,} files · "
            f"{self.format_size(progress['size'])} · "
            f"{progress['skipped']:,} skipped"
        )

    @Slot(object)
    def handle_scan_finished(
        self,
        results,
    ):
        self.scan_progress.hide()

        self.analyze_button.setEnabled(
            True
        )

        self.refresh_button.setEnabled(
            True
        )

        self.files_scanned_value.setText(
            f"{results['files']:,}"
        )

        self.total_size_value.setText(
            self.format_size(
                results["size"]
            )
        )

        self.skipped_value.setText(
            f"{results['skipped']:,}"
        )

        self.scan_status.setText(
            f"Analysis complete · "
            f"{results['files']:,} files scanned"
        )

        self.populate_table(
            self.files_table,
            results[
                "largest_files"
            ],
            results["root"],
        )

        self.populate_table(
            self.folders_table,
            results[
                "largest_folders"
            ],
            results["root"],
        )

        self.summary_container.show()
        self.results_container.show()

    @Slot(str)
    def handle_scan_failed(
        self,
        error,
    ):
        self.scan_progress.hide()

        self.analyze_button.setEnabled(
            True
        )

        self.refresh_button.setEnabled(
            True
        )

        self.scan_status.setText(
            f"Scan failed: {error}"
        )

    def populate_table(
        self,
        table,
        entries,
        root,
    ):
        table.setRowCount(
            len(entries)
        )

        for row, (
            size,
            path,
        ) in enumerate(entries):

            try:
                display_path = os.path.relpath(
                    path,
                    root,
                )

            except ValueError:
                display_path = path

            path_item = QTableWidgetItem(
                display_path
            )

            path_item.setToolTip(
                path
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

            table.setItem(
                row,
                0,
                path_item,
            )

            table.setItem(
                row,
                1,
                size_item,
            )

    # ========================================================
    # Cleanup
    # ========================================================

    def clear_drive_cards(self):
        while self.drive_layout.count():
            item = self.drive_layout.takeAt(
                0
            )

            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

    def cleanup_scan_thread(self):
        if self.scan_thread is not None:
            self.scan_thread.deleteLater()

        self.scan_thread = None
        self.scan_worker = None

    def shutdown_scan(self):
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
    # Formatting
    # ========================================================

    def format_size(
        self,
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