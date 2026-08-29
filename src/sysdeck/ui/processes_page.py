import psutil

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QSortFilterProxyModel,
    Qt,
    QThread,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableView,
    QVBoxLayout,
    QWidget,
)


# ============================================================
# Process table model
# ============================================================

class ProcessTableModel(QAbstractTableModel):
    HEADERS = [
        "Name",
        "PID",
        "CPU",
        "Memory",
    ]

    def __init__(
        self,
        parent=None,
    ):
        super().__init__(
            parent
        )

        self.rows = []

    # ========================================================
    # Model dimensions
    # ========================================================

    def rowCount(
        self,
        parent=QModelIndex(),
    ):
        if parent.isValid():
            return 0

        return len(
            self.rows
        )

    def columnCount(
        self,
        parent=QModelIndex(),
    ):
        if parent.isValid():
            return 0

        return len(
            self.HEADERS
        )

    # ========================================================
    # Cell data
    # ========================================================

    def data(
        self,
        index,
        role=Qt.ItemDataRole.DisplayRole,
    ):
        if not index.isValid():
            return None

        row_index = index.row()

        if not (
            0
            <= row_index
            < len(self.rows)
        ):
            return None

        (
            name,
            pid,
            cpu,
            memory,
        ) = self.rows[
            row_index
        ]

        column = index.column()

        # Raw values are used by the proxy for
        # correct numeric sorting.
        if role == Qt.ItemDataRole.UserRole:
            raw_values = (
                name,
                pid,
                cpu,
                memory,
            )

            return raw_values[
                column
            ]

        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return name

            if column == 1:
                return str(
                    pid
                )

            if column == 2:
                return (
                    f"{cpu:.1f}%"
                )

            if column == 3:
                return self.format_memory(
                    memory
                )

        if (
            role
            == Qt.ItemDataRole.TextAlignmentRole
        ):
            if column == 0:
                return int(
                    Qt.AlignmentFlag.AlignLeft
                    | Qt.AlignmentFlag.AlignVCenter
                )

            return int(
                Qt.AlignmentFlag.AlignRight
                | Qt.AlignmentFlag.AlignVCenter
            )

        return None

    # ========================================================
    # Headers
    # ========================================================

    def headerData(
        self,
        section,
        orientation,
        role=Qt.ItemDataRole.DisplayRole,
    ):
        if (
            orientation
            == Qt.Orientation.Horizontal
            and role
            == Qt.ItemDataRole.DisplayRole
            and 0
            <= section
            < len(self.HEADERS)
        ):
            return self.HEADERS[
                section
            ]

        return None

    # ========================================================
    # Updates
    # ========================================================

    def update_rows(
        self,
        rows,
    ):
        """
        Avoid resetting the entire model when the process
        list itself has not changed.

        If the same PIDs are still present, only notify Qt
        that their values changed. A full reset is reserved
        for process creation/termination.
        """

        if rows == self.rows:
            return

        old_pids = tuple(
            row[1]
            for row
            in self.rows
        )

        new_pids = tuple(
            row[1]
            for row
            in rows
        )

        if (
            self.rows
            and len(self.rows)
            == len(rows)
            and old_pids
            == new_pids
        ):
            self.rows = rows

            top_left = self.index(
                0,
                0,
            )

            bottom_right = self.index(
                len(rows) - 1,
                len(self.HEADERS) - 1,
            )

            self.dataChanged.emit(
                top_left,
                bottom_right,
                [
                    Qt.ItemDataRole.DisplayRole,
                    Qt.ItemDataRole.UserRole,
                ],
            )

            return

        self.beginResetModel()

        self.rows = rows

        self.endResetModel()

    # ========================================================
    # Formatting
    # ========================================================

    @staticmethod
    def format_memory(
        memory_mb,
    ):
        if memory_mb >= 1024:
            return (
                f"{memory_mb / 1024:.1f} GB"
            )

        return (
            f"{memory_mb:.1f} MB"
        )


# ============================================================
# Background process worker
# ============================================================

class ProcessWorker(QObject):
    data_ready = Signal(list)
    failed = Signal(str)

    def __init__(
        self,
    ):
        super().__init__()

        self.logical_cpu_count = (
            psutil.cpu_count(
                logical=True
            )
            or 1
        )

    @Slot()
    def refresh(
        self,
    ):
        processes = []

        try:
            # process_iter() reuses Process objects internally,
            # which is useful because cpu_percent(interval=None)
            # needs previous samples to calculate CPU usage.
            for process in psutil.process_iter():
                if (
                    QThread.currentThread()
                    .isInterruptionRequested()
                ):
                    return

                try:
                    pid = process.pid

                    # Windows PID 0 is System Idle Process.
                    # It is not useful in this view and can
                    # produce confusing CPU readings.
                    if pid == 0:
                        continue

                    # oneshot() allows psutil to reuse certain
                    # underlying process queries during this
                    # block instead of repeatedly asking Windows.
                    with process.oneshot():
                        name = (
                            process.name()
                            or "Unknown"
                        )

                        memory_info = (
                            process.memory_info()
                        )

                        raw_cpu = (
                            process.cpu_percent(
                                interval=None
                            )
                        )

                    if memory_info is None:
                        continue

                    # psutil Process.cpu_percent() can report
                    # above 100% on multicore systems.
                    #
                    # Divide by logical CPU count to match the
                    # 0–100% style used by Windows Task Manager.
                    cpu = (
                        raw_cpu
                        / self.logical_cpu_count
                    )

                    cpu = min(
                        max(
                            cpu,
                            0.0,
                        ),
                        100.0,
                    )

                    memory_mb = (
                        memory_info.rss
                        / (1024 ** 2)
                    )

                    # The UI only displays one decimal place.
                    # Keeping the worker data at that precision
                    # avoids meaningless tiny float differences.
                    cpu = round(
                        cpu,
                        1,
                    )

                    memory_mb = round(
                        memory_mb,
                        1,
                    )

                    processes.append(
                        (
                            name,
                            pid,
                            cpu,
                            memory_mb,
                        )
                    )

                except (
                    psutil.NoSuchProcess,
                    psutil.AccessDenied,
                    psutil.ZombieProcess,
                    PermissionError,
                    ProcessLookupError,
                ):
                    continue

            # Keep source ordering stable.
            #
            # The proxy handles the user's visible sorting,
            # while PID ordering lets the model detect whether
            # processes were actually added or removed.
            processes.sort(
                key=lambda row:
                    row[1]
            )

            self.data_ready.emit(
                processes
            )

        except Exception as error:
            self.failed.emit(
                str(error)
            )


# ============================================================
# Processes page
# ============================================================

class ProcessesPage(QWidget):
    refresh_requested = Signal()

    REFRESH_INTERVAL_MS = 4000

    def __init__(
        self,
    ):
        super().__init__()

        self.refresh_in_progress = False

        self.setup_ui()
        self.setup_worker()
        self.setup_timer()

    # ========================================================
    # UI
    # ========================================================

    def setup_ui(
        self,
    ):
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
            18
        )

        # ----------------------------------------------------
        # Header
        # ----------------------------------------------------

        title = QLabel(
            "Processes"
        )

        title.setObjectName(
            "pageTitle"
        )

        description = QLabel(
            "View and inspect running applications and background processes."
        )

        description.setObjectName(
            "pageDescription"
        )

        # ----------------------------------------------------
        # Search
        # ----------------------------------------------------

        self.search = QLineEdit()

        self.search.setObjectName(
            "processSearch"
        )

        self.search.setPlaceholderText(
            "Search processes..."
        )

        self.search.setClearButtonEnabled(
            True
        )

        # ----------------------------------------------------
        # Status
        # ----------------------------------------------------

        self.status = QLabel(
            "Waiting for process data..."
        )

        self.status.setObjectName(
            "processStatus"
        )

        # ----------------------------------------------------
        # Model + proxy
        # ----------------------------------------------------

        self.model = ProcessTableModel(
            self
        )

        self.proxy = QSortFilterProxyModel(
            self
        )

        self.proxy.setSourceModel(
            self.model
        )

        self.proxy.setFilterCaseSensitivity(
            Qt.CaseSensitivity.CaseInsensitive
        )

        # Search every column.
        self.proxy.setFilterKeyColumn(
            -1
        )

        # Sort using the raw numeric values rather
        # than strings such as "10.0%" or "1.2 GB".
        self.proxy.setSortRole(
            Qt.ItemDataRole.UserRole
        )

        self.proxy.setDynamicSortFilter(
            True
        )

        self.search.textChanged.connect(
            self.proxy.setFilterFixedString
        )

        self.search.textChanged.connect(
            self.update_status
        )

        # ----------------------------------------------------
        # Table
        # ----------------------------------------------------

        self.table = QTableView()

        self.table.setObjectName(
            "processTable"
        )

        self.table.setModel(
            self.proxy
        )

        self.table.setSortingEnabled(
            True
        )

        self.table.sortByColumn(
            2,
            Qt.SortOrder.DescendingOrder,
        )

        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )

        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )

        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )

        self.table.setAlternatingRowColors(
            True
        )

        self.table.setShowGrid(
            False
        )

        self.table.setWordWrap(
            False
        )

        # ----------------------------------------------------
        # Vertical rows
        # ----------------------------------------------------

        vertical_header = (
            self.table
            .verticalHeader()
        )

        vertical_header.hide()

        vertical_header.setSectionResizeMode(
            QHeaderView.ResizeMode.Fixed
        )

        vertical_header.setDefaultSectionSize(
            34
        )

        # ----------------------------------------------------
        # Column sizing
        #
        # ResizeToContents can repeatedly inspect rows whenever
        # process data changes. Fixed widths are much cheaper
        # for columns with predictable content.
        # ----------------------------------------------------

        header = (
            self.table
            .horizontalHeader()
        )

        header.setStretchLastSection(
            False
        )

        header.setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.Stretch,
        )

        header.setSectionResizeMode(
            1,
            QHeaderView.ResizeMode.Fixed,
        )

        header.setSectionResizeMode(
            2,
            QHeaderView.ResizeMode.Fixed,
        )

        header.setSectionResizeMode(
            3,
            QHeaderView.ResizeMode.Fixed,
        )

        self.table.setColumnWidth(
            1,
            90,
        )

        self.table.setColumnWidth(
            2,
            95,
        )

        self.table.setColumnWidth(
            3,
            120,
        )

        # ----------------------------------------------------
        # Layout
        # ----------------------------------------------------

        layout.addWidget(
            title
        )

        layout.addWidget(
            description
        )

        layout.addSpacing(
            4
        )

        layout.addWidget(
            self.search
        )

        layout.addWidget(
            self.status
        )

        layout.addWidget(
            self.table,
            1,
        )

    # ========================================================
    # Worker
    # ========================================================

    def setup_worker(
        self,
    ):
        self.worker_thread = QThread(
            self
        )

        self.worker = ProcessWorker()

        self.worker.moveToThread(
            self.worker_thread
        )

        self.refresh_requested.connect(
            self.worker.refresh
        )

        self.worker.data_ready.connect(
            self.receive_processes
        )

        self.worker.failed.connect(
            self.handle_refresh_failed
        )

        self.worker_thread.start()

        app = QApplication.instance()

        if app is not None:
            app.aboutToQuit.connect(
                self.shutdown_worker
            )

    # ========================================================
    # Timer
    # ========================================================

    def setup_timer(
        self,
    ):
        self.timer = QTimer(
            self
        )

        self.timer.setInterval(
            self.REFRESH_INTERVAL_MS
        )

        self.timer.timeout.connect(
            self.request_refresh
        )

    # ========================================================
    # Visibility
    # ========================================================

    def showEvent(
        self,
        event,
    ):
        super().showEvent(
            event
        )

        if not self.timer.isActive():
            self.timer.start()

        # Refresh immediately whenever the page becomes visible
        # instead of waiting up to four seconds.
        QTimer.singleShot(
            0,
            self.request_refresh,
        )

    def hideEvent(
        self,
        event,
    ):
        # No process polling while the user is elsewhere
        # in SysDeck.
        self.timer.stop()

        super().hideEvent(
            event
        )

    # ========================================================
    # Refresh cycle
    # ========================================================

    def request_refresh(
        self,
    ):
        if self.refresh_in_progress:
            return

        if not self.worker_thread.isRunning():
            return

        self.refresh_in_progress = True

        # Don't rewrite the status every four seconds once
        # useful data is already visible.
        if not self.model.rows:
            self.status.setText(
                "Loading processes..."
            )

        self.refresh_requested.emit()

    @Slot(list)
    def receive_processes(
        self,
        processes,
    ):
        self.model.update_rows(
            processes
        )

        self.refresh_in_progress = False

        self.update_status()

    @Slot(str)
    def handle_refresh_failed(
        self,
        error,
    ):
        self.refresh_in_progress = False

        self.status.setText(
            "Process refresh failed · "
            "will retry automatically"
        )

    # ========================================================
    # Status
    # ========================================================

    def update_status(
        self,
        *_args,
    ):
        total_count = (
            self.model.rowCount()
        )

        visible_count = (
            self.proxy.rowCount()
        )

        query = (
            self.search.text().strip()
        )

        if query:
            self.status.setText(
                f"{visible_count:,} matching · "
                f"{total_count:,} processes · "
                "updates every 4 seconds"
            )

        else:
            self.status.setText(
                f"{total_count:,} processes · "
                "updates every 4 seconds"
            )

    # ========================================================
    # Shutdown
    # ========================================================

    def shutdown_worker(
        self,
    ):
        self.timer.stop()

        self.refresh_requested.disconnect(
            self.worker.refresh
        )

        if self.worker_thread.isRunning():
            self.worker_thread.requestInterruption()

            self.worker_thread.quit()

            self.worker_thread.wait(
                2000
            )