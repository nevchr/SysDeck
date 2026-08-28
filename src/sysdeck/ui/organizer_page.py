import os
import shutil

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
    QFileDialog,
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

from ..core.database import connect_database


# ============================================================
# File categories
# ============================================================

CATEGORY_EXTENSIONS = {
    "Images": {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".bmp",
        ".webp",
        ".tif",
        ".tiff",
        ".heic",
        ".heif",
        ".raw",
        ".cr2",
        ".cr3",
        ".nef",
        ".arw",
        ".dng",
    },

    "Videos": {
        ".mp4",
        ".mov",
        ".mkv",
        ".avi",
        ".webm",
        ".wmv",
        ".m4v",
        ".flv",
    },

    "Audio": {
        ".mp3",
        ".wav",
        ".flac",
        ".m4a",
        ".aac",
        ".ogg",
        ".wma",
        ".aiff",
        ".aif",
    },

    "Documents": {
        ".pdf",
        ".doc",
        ".docx",
        ".txt",
        ".rtf",
        ".odt",
        ".ppt",
        ".pptx",
        ".xls",
        ".xlsx",
        ".pages",
    },

    "Archives": {
        ".zip",
        ".rar",
        ".7z",
        ".tar",
        ".gz",
        ".bz2",
        ".xz",
    },

    "Installers": {
        ".exe",
        ".msi",
        ".msix",
        ".appx",
        ".appxbundle",
    },

    "Code": {
        ".py",
        ".java",
        ".js",
        ".ts",
        ".jsx",
        ".tsx",
        ".html",
        ".htm",
        ".css",
        ".scss",
        ".cpp",
        ".c",
        ".h",
        ".hpp",
        ".cs",
        ".rs",
        ".go",
        ".php",
        ".lua",
        ".sh",
        ".ps1",
        ".bat",
        ".cmd",
        ".md",
    },

    "Data": {
        ".csv",
        ".json",
        ".xml",
        ".yaml",
        ".yml",
        ".sql",
        ".db",
        ".sqlite",
        ".sqlite3",
        ".parquet",
    },

    "Fonts": {
        ".ttf",
        ".otf",
        ".woff",
        ".woff2",
    },

    "Disk Images": {
        ".iso",
        ".img",
        ".dmg",
        ".vhd",
        ".vhdx",
    },
}


def get_category(
    filename,
):
    extension = os.path.splitext(
        filename
    )[1].lower()

    for category, extensions in (
        CATEGORY_EXTENSIONS.items()
    ):
        if extension in extensions:
            return category

    return "Other"


# ============================================================
# Background preview scanner
# ============================================================

class OrganizerScanWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        folder,
    ):
        super().__init__()

        self.folder = os.path.abspath(
            folder
        )

    @Slot()
    def scan(self):
        try:
            items = []
            total_size = 0
            skipped = 0

            category_counts = {}

            with os.scandir(
                self.folder
            ) as entries:

                for entry in entries:
                    if (
                        QThread.currentThread()
                        .isInterruptionRequested()
                    ):
                        return

                    try:
                        if (
                            not entry.is_file(
                                follow_symlinks=False
                            )
                        ):
                            continue

                        if entry.is_symlink():
                            continue

                        stat = entry.stat(
                            follow_symlinks=False
                        )

                    except (
                        PermissionError,
                        FileNotFoundError,
                        OSError,
                    ):
                        skipped += 1
                        continue

                    category = get_category(
                        entry.name
                    )

                    destination_folder = os.path.join(
                        self.folder,
                        category,
                    )

                    items.append(
                        {
                            "path": entry.path,
                            "name": entry.name,
                            "extension": (
                                os.path.splitext(
                                    entry.name
                                )[1].lower()
                            ),
                            "size": stat.st_size,
                            "category": category,
                            "destination_folder":
                                destination_folder,
                        }
                    )

                    total_size += (
                        stat.st_size
                    )

                    category_counts[
                        category
                    ] = (
                        category_counts.get(
                            category,
                            0,
                        )
                        + 1
                    )

            items.sort(
                key=lambda item: (
                    item["category"].lower(),
                    item["name"].lower(),
                )
            )

            self.finished.emit(
                {
                    "folder": self.folder,
                    "items": items,
                    "file_count": len(items),
                    "total_size": total_size,
                    "category_count":
                        len(category_counts),

                    "category_counts":
                        category_counts,

                    "skipped": skipped,
                }
            )

        except Exception as error:
            self.failed.emit(
                str(error)
            )


# ============================================================
# Background organizer
# ============================================================

class OrganizerMoveWorker(QObject):
    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        items,
    ):
        super().__init__()

        self.items = items

    @Slot()
    def organize(self):
        connection = None

        successful = []
        failed = []

        try:
            connection = connect_database()

            total = len(
                self.items
            )

            for index, item in enumerate(
                self.items,
                start=1,
            ):
                if (
                    QThread.currentThread()
                    .isInterruptionRequested()
                ):
                    return

                source_path = (
                    item["path"]
                )

                destination_folder = (
                    item["destination_folder"]
                )

                try:
                    if not os.path.isfile(
                        source_path
                    ):
                        failed.append(
                            (
                                source_path,
                                "File no longer exists",
                            )
                        )

                        continue

                    os.makedirs(
                        destination_folder,
                        exist_ok=True,
                    )

                    destination_path = (
                        self.get_unique_destination(
                            destination_folder,
                            item["name"],
                        )
                    )

                    shutil.move(
                        source_path,
                        destination_path,
                    )

                    # ----------------------------------------
                    # Update the existing SysDeck index row,
                    # if this file happened to be indexed.
                    # ----------------------------------------

                    try:
                        stat = os.stat(
                            destination_path
                        )

                        new_name = os.path.basename(
                            destination_path
                        )

                        new_parent = os.path.dirname(
                            destination_path
                        )

                        new_extension = (
                            os.path.splitext(
                                new_name
                            )[1].lower()
                        )

                        # If an old/stale index row already
                        # points at the destination, remove it.
                        connection.execute(
                            """
                            DELETE FROM files
                            WHERE path = ?
                              AND path != ?
                            """,
                            (
                                destination_path,
                                source_path,
                            ),
                        )

                        connection.execute(
                            """
                            UPDATE files
                            SET
                                path = ?,
                                name = ?,
                                parent = ?,
                                extension = ?,
                                size = ?,
                                modified = ?
                            WHERE path = ?
                            """,
                            (
                                destination_path,
                                new_name,
                                new_parent,
                                new_extension,
                                stat.st_size,
                                stat.st_mtime,
                                source_path,
                            ),
                        )

                    except Exception:
                        # A database update should never cause
                        # an already-successful file move to be
                        # treated as a filesystem failure.
                        pass

                    successful.append(
                        {
                            "old_path":
                                source_path,

                            "new_path":
                                destination_path,

                            "size":
                                item["size"],
                        }
                    )

                except Exception as error:
                    failed.append(
                        (
                            source_path,
                            str(error),
                        )
                    )

                self.progress.emit(
                    {
                        "processed":
                            index,

                        "total":
                            total,
                    }
                )

            connection.commit()

            self.finished.emit(
                {
                    "successful":
                        successful,

                    "failed":
                        failed,
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
    def get_unique_destination(
        folder,
        filename,
    ):
        destination = os.path.join(
            folder,
            filename,
        )

        if not os.path.exists(
            destination
        ):
            return destination

        stem, extension = os.path.splitext(
            filename
        )

        counter = 1

        while True:
            candidate = os.path.join(
                folder,
                f"{stem} ({counter}){extension}",
            )

            if not os.path.exists(
                candidate
            ):
                return candidate

            counter += 1


# ============================================================
# Organizer page
# ============================================================

class OrganizerPage(QWidget):
    def __init__(self):
        super().__init__()

        self.selected_folder = None
        self.preview_items = []

        self.scan_thread = None
        self.scan_worker = None

        self.move_thread = None
        self.move_worker = None

        self.setup_ui()

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
            "File Organizer"
        )

        title.setObjectName(
            "pageTitle"
        )

        description = QLabel(
            "Preview and organize loose files into clean category folders."
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

        self.choose_button = QPushButton(
            "Choose Folder"
        )

        self.choose_button.setObjectName(
            "primaryButton"
        )

        self.choose_button.clicked.connect(
            self.choose_folder
        )

        header.addLayout(
            header_text
        )

        header.addStretch()

        header.addWidget(
            self.choose_button
        )

        layout.addLayout(
            header
        )

        # ----------------------------------------------------
        # Folder + safety information
        # ----------------------------------------------------

        self.folder_label = QLabel(
            "No folder selected"
        )

        self.folder_label.setObjectName(
            "searchStatus"
        )

        self.folder_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self.status_label = QLabel(
            "Preview only — nothing moves until you confirm."
        )

        self.status_label.setObjectName(
            "searchStatus"
        )

        layout.addWidget(
            self.folder_label
        )

        layout.addWidget(
            self.status_label
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

        for column in range(
            3
        ):
            summary_layout.setColumnStretch(
                column,
                1,
            )

        self.files_value = QLabel(
            "0"
        )

        self.size_value = QLabel(
            "0 B"
        )

        self.categories_value = QLabel(
            "0"
        )

        summary_layout.addWidget(
            self.create_summary_card(
                "Files to Organize",
                self.files_value,
            ),
            0,
            0,
        )

        summary_layout.addWidget(
            self.create_summary_card(
                "Total Size",
                self.size_value,
            ),
            0,
            1,
        )

        summary_layout.addWidget(
            self.create_summary_card(
                "Categories",
                self.categories_value,
            ),
            0,
            2,
        )

        self.summary_container.hide()

        layout.addWidget(
            self.summary_container
        )

        # ----------------------------------------------------
        # Preview actions
        # ----------------------------------------------------

        actions = QHBoxLayout()

        self.preview_status = QLabel(
            "Choose a folder to build a preview."
        )

        self.preview_status.setObjectName(
            "searchStatus"
        )

        self.open_folder_button = QPushButton(
            "Open Folder"
        )

        self.open_folder_button.setObjectName(
            "secondaryButton"
        )

        self.open_folder_button.setEnabled(
            False
        )

        self.open_folder_button.clicked.connect(
            self.open_selected_folder
        )

        self.rescan_button = QPushButton(
            "Refresh Preview"
        )

        self.rescan_button.setObjectName(
            "secondaryButton"
        )

        self.rescan_button.setEnabled(
            False
        )

        self.rescan_button.clicked.connect(
            self.rescan
        )

        self.organize_button = QPushButton(
            "Organize Files"
        )

        self.organize_button.setObjectName(
            "primaryButton"
        )

        self.organize_button.setEnabled(
            False
        )

        self.organize_button.clicked.connect(
            self.confirm_organize
        )

        actions.addWidget(
            self.preview_status
        )

        actions.addStretch()

        actions.addWidget(
            self.open_folder_button
        )

        actions.addWidget(
            self.rescan_button
        )

        actions.addWidget(
            self.organize_button
        )

        layout.addLayout(
            actions
        )

        # ----------------------------------------------------
        # Preview table
        # ----------------------------------------------------

        self.preview_table = QTableWidget(
            0,
            4,
        )

        self.preview_table.setObjectName(
            "searchResults"
        )

        self.preview_table.setHorizontalHeaderLabels(
            [
                "File",
                "Category",
                "Size",
                "Destination",
            ]
        )

        self.preview_table.verticalHeader().hide()

        self.preview_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )

        self.preview_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )

        self.preview_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )

        self.preview_table.setAlternatingRowColors(
            True
        )

        self.preview_table.setShowGrid(
            False
        )

        header_view = (
            self.preview_table
            .horizontalHeader()
        )

        header_view.setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.Stretch,
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

        layout.addWidget(
            self.preview_table,
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
    # Folder selection
    # ========================================================

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Choose Folder to Organize",
        )

        if not folder:
            return

        self.selected_folder = (
            os.path.abspath(
                folder
            )
        )

        self.folder_label.setText(
            self.selected_folder
        )

        self.folder_label.setToolTip(
            self.selected_folder
        )

        self.open_folder_button.setEnabled(
            True
        )

        self.start_scan()

    def rescan(self):
        if not self.selected_folder:
            return

        self.start_scan()

    # ========================================================
    # Preview scan
    # ========================================================

    def start_scan(self):
        if not self.selected_folder:
            return

        if (
            self.scan_thread is not None
            and self.scan_thread.isRunning()
        ):
            return

        self.set_controls_enabled(
            False
        )

        self.preview_items = []

        self.preview_table.setRowCount(
            0
        )

        self.summary_container.hide()

        self.status_label.setText(
            "Scanning loose files..."
        )

        self.preview_status.setText(
            "Building preview..."
        )

        self.scan_thread = QThread(
            self
        )

        self.scan_worker = (
            OrganizerScanWorker(
                self.selected_folder
            )
        )

        self.scan_worker.moveToThread(
            self.scan_thread
        )

        self.scan_thread.started.connect(
            self.scan_worker.scan
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
    def handle_scan_finished(
        self,
        results,
    ):
        self.preview_items = (
            results["items"]
        )

        self.populate_preview(
            self.preview_items
        )

        self.files_value.setText(
            f"{results['file_count']:,}"
        )

        self.size_value.setText(
            self.format_size(
                results["total_size"]
            )
        )

        self.categories_value.setText(
            f"{results['category_count']:,}"
        )

        self.summary_container.show()

        self.status_label.setText(
            "Preview ready — no files have been moved."
        )

        self.preview_status.setText(
            f"{results['file_count']:,} loose files · "
            f"{results['category_count']:,} categories · "
            f"{results['skipped']:,} skipped"
        )

        self.set_controls_enabled(
            True
        )

    @Slot(str)
    def handle_scan_failed(
        self,
        error,
    ):
        self.status_label.setText(
            f"Preview failed: {error}"
        )

        self.preview_status.setText(
            "Unable to build preview"
        )

        self.set_controls_enabled(
            True
        )

    def cleanup_scan_thread(self):
        if self.scan_thread is not None:
            self.scan_thread.deleteLater()

        self.scan_thread = None
        self.scan_worker = None

    # ========================================================
    # Preview table
    # ========================================================

    def populate_preview(
        self,
        items,
    ):
        self.preview_table.setUpdatesEnabled(
            False
        )

        self.preview_table.setRowCount(
            len(items)
        )

        for row, item in enumerate(
            items
        ):
            name_item = QTableWidgetItem(
                item["name"]
            )

            name_item.setToolTip(
                item["path"]
            )

            category_item = QTableWidgetItem(
                item["category"]
            )

            size_item = QTableWidgetItem(
                self.format_size(
                    item["size"]
                )
            )

            size_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight
                | Qt.AlignmentFlag.AlignVCenter
            )

            destination_item = (
                QTableWidgetItem(
                    item[
                        "destination_folder"
                    ]
                )
            )

            destination_item.setToolTip(
                item[
                    "destination_folder"
                ]
            )

            self.preview_table.setItem(
                row,
                0,
                name_item,
            )

            self.preview_table.setItem(
                row,
                1,
                category_item,
            )

            self.preview_table.setItem(
                row,
                2,
                size_item,
            )

            self.preview_table.setItem(
                row,
                3,
                destination_item,
            )

        self.preview_table.setUpdatesEnabled(
            True
        )

        self.preview_table.viewport().update()

    # ========================================================
    # Organize
    # ========================================================

    def confirm_organize(self):
        if not self.preview_items:
            return

        file_count = len(
            self.preview_items
        )

        total_size = sum(
            item["size"]
            for item
            in self.preview_items
        )

        confirmation = QMessageBox.question(
            self,
            "Organize files",
            (
                f"Organize {file_count:,} file"
                f"{'' if file_count == 1 else 's'} "
                f"({self.format_size(total_size)}) "
                "into category folders?\n\n"
                "Existing files will never be overwritten. "
                "If a filename already exists, SysDeck will "
                "create a unique name automatically."
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

        self.start_move()

    def start_move(self):
        if (
            self.move_thread is not None
            and self.move_thread.isRunning()
        ):
            return

        self.set_controls_enabled(
            False
        )

        self.status_label.setText(
            "Organizing files..."
        )

        self.preview_status.setText(
            f"Moving 0 / {len(self.preview_items):,}"
        )

        self.move_thread = QThread(
            self
        )

        self.move_worker = (
            OrganizerMoveWorker(
                list(
                    self.preview_items
                )
            )
        )

        self.move_worker.moveToThread(
            self.move_thread
        )

        self.move_thread.started.connect(
            self.move_worker.organize
        )

        self.move_worker.progress.connect(
            self.handle_move_progress
        )

        self.move_worker.finished.connect(
            self.handle_move_finished
        )

        self.move_worker.failed.connect(
            self.handle_move_failed
        )

        self.move_worker.finished.connect(
            self.move_thread.quit
        )

        self.move_worker.failed.connect(
            self.move_thread.quit
        )

        self.move_worker.finished.connect(
            self.move_worker.deleteLater
        )

        self.move_worker.failed.connect(
            self.move_worker.deleteLater
        )

        self.move_thread.finished.connect(
            self.cleanup_move_thread
        )

        self.move_thread.start()

    @Slot(object)
    def handle_move_progress(
        self,
        progress,
    ):
        self.preview_status.setText(
            f"Moving "
            f"{progress['processed']:,} / "
            f"{progress['total']:,}"
        )

    @Slot(object)
    def handle_move_finished(
        self,
        results,
    ):
        successful = (
            results["successful"]
        )

        failed = (
            results["failed"]
        )

        self.status_label.setText(
            f"Organized {len(successful):,} file"
            f"{'' if len(successful) == 1 else 's'}."
        )

        if failed:
            preview = "\n".join(
                path
                for path, _error
                in failed[:5]
            )

            QMessageBox.warning(
                self,
                "Some files could not be moved",
                (
                    f"{len(failed):,} file"
                    f"{'' if len(failed) == 1 else 's'} "
                    "could not be organized.\n\n"
                    f"{preview}"
                ),
            )

        self.preview_items = []

    @Slot(str)
    def handle_move_failed(
        self,
        error,
    ):
        self.status_label.setText(
            f"Organization failed: {error}"
        )

        self.preview_status.setText(
            "Move operation failed"
        )

        self.set_controls_enabled(
            True
        )

    def cleanup_move_thread(self):
        if self.move_thread is not None:
            self.move_thread.deleteLater()

        self.move_thread = None
        self.move_worker = None

        # Refresh the folder automatically so the
        # finished state is immediately visible.
        if (
            self.selected_folder
            and os.path.isdir(
                self.selected_folder
            )
        ):
            self.start_scan()

        else:
            self.set_controls_enabled(
                True
            )

    # ========================================================
    # Controls
    # ========================================================

    def set_controls_enabled(
        self,
        enabled,
    ):
        self.choose_button.setEnabled(
            enabled
        )

        self.open_folder_button.setEnabled(
            enabled
            and self.selected_folder
            is not None
        )

        self.rescan_button.setEnabled(
            enabled
            and self.selected_folder
            is not None
        )

        self.organize_button.setEnabled(
            enabled
            and len(
                self.preview_items
            ) > 0
        )

    def open_selected_folder(self):
        if (
            not self.selected_folder
            or not os.path.isdir(
                self.selected_folder
            )
        ):
            return

        try:
            os.startfile(
                self.selected_folder
            )

        except OSError:
            pass

    # ========================================================
    # Shutdown
    # ========================================================

    def shutdown_workers(self):
        for thread in (
            self.scan_thread,
            self.move_thread,
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