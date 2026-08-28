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


class ProcessTableModel(QAbstractTableModel):
    HEADERS = [
        "Name",
        "PID",
        "CPU",
        "Memory",
    ]

    def __init__(self):
        super().__init__()
        self.rows = []

    def rowCount(
        self,
        parent=QModelIndex(),
    ):
        return len(self.rows)

    def columnCount(
        self,
        parent=QModelIndex(),
    ):
        return 4

    def data(
        self,
        index,
        role=Qt.ItemDataRole.DisplayRole,
    ):
        if not index.isValid():
            return None

        name, pid, cpu, memory = (
            self.rows[index.row()]
        )

        column = index.column()

        raw_values = [
            name,
            pid,
            cpu,
            memory,
        ]

        if role == Qt.ItemDataRole.UserRole:
            return raw_values[column]

        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return name

            if column == 1:
                return str(pid)

            if column == 2:
                return f"{cpu:.1f}%"

            if column == 3:
                return self.format_memory(
                    memory
                )

        if role == Qt.ItemDataRole.TextAlignmentRole:
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
        ):
            return self.HEADERS[section]

        return None

    def update_rows(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    @staticmethod
    def format_memory(memory_mb):
        if memory_mb >= 1024:
            return f"{memory_mb / 1024:.1f} GB"

        return f"{memory_mb:.1f} MB"


class ProcessWorker(QObject):
    data_ready = Signal(list)

    def __init__(self):
        super().__init__()

        self.logical_cpu_count = (
            psutil.cpu_count(logical=True) or 1
        )

    @Slot()
    def refresh(self):
        processes = []

        for process in psutil.process_iter(
            [
                "pid",
                "name",
                "memory_info",
            ]
        ):
            try:
                pid = process.info["pid"]

                # PID 0 = System Idle Process.
                if pid == 0:
                    continue

                name = (
                    process.info["name"]
                    or "Unknown"
                )

                raw_cpu = process.cpu_percent(
                    interval=None
                )

                cpu = (
                    raw_cpu
                    / self.logical_cpu_count
                )

                cpu = min(
                    max(cpu, 0.0),
                    100.0,
                )

                memory_info = (
                    process.info["memory_info"]
                )

                if memory_info is None:
                    continue

                memory_mb = (
                    memory_info.rss
                    / (1024 ** 2)
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
                KeyError,
                AttributeError,
            ):
                continue

        self.data_ready.emit(
            processes
        )


class ProcessesPage(QWidget):
    refresh_requested = Signal()

    def __init__(self):
        super().__init__()

        self.refresh_in_progress = False

        self.setup_ui()
        self.setup_worker()
        self.setup_timer()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        layout.setContentsMargins(
            46,
            40,
            46,
            40,
        )

        layout.setSpacing(18)

        title = QLabel("Processes")
        title.setObjectName("pageTitle")

        description = QLabel(
            "View and inspect running applications and background processes."
        )

        description.setObjectName(
            "pageDescription"
        )

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

        self.status = QLabel(
            "Waiting for process data..."
        )

        self.status.setObjectName(
            "processStatus"
        )

        self.model = ProcessTableModel()

        self.proxy = QSortFilterProxyModel(
            self
        )

        self.proxy.setSourceModel(
            self.model
        )

        self.proxy.setFilterCaseSensitivity(
            Qt.CaseSensitivity.CaseInsensitive
        )

        # Search all columns.
        self.proxy.setFilterKeyColumn(
            -1
        )

        # Sort using raw numeric values instead of
        # strings like "10%" and "9%".
        self.proxy.setSortRole(
            Qt.ItemDataRole.UserRole
        )

        self.search.textChanged.connect(
            self.proxy.setFilterFixedString
        )

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

        self.table.verticalHeader().hide()

        self.table.verticalHeader().setDefaultSectionSize(
            34
        )

        header = (
            self.table.horizontalHeader()
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

        header.setSectionResizeMode(
            3,
            QHeaderView.ResizeMode.ResizeToContents,
        )

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addSpacing(4)
        layout.addWidget(self.search)
        layout.addWidget(self.status)
        layout.addWidget(self.table, 1)

    def setup_worker(self):
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

        self.worker_thread.start()

        app = QApplication.instance()

        if app is not None:
            app.aboutToQuit.connect(
                self.shutdown_worker
            )

    def setup_timer(self):
        self.timer = QTimer(
            self
        )

        self.timer.setInterval(
            4000
        )

        self.timer.timeout.connect(
            self.request_refresh
        )

    def showEvent(self, event):
        super().showEvent(event)

        if not self.timer.isActive():
            self.timer.start()

        QTimer.singleShot(
            0,
            self.request_refresh,
        )

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def request_refresh(self):
        if self.refresh_in_progress:
            return

        self.refresh_in_progress = True

        self.status.setText(
            "Refreshing processes..."
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

        self.status.setText(
            f"{len(processes)} processes · "
            "updates every 4 seconds"
        )

    def shutdown_worker(self):
        self.timer.stop()

        if self.worker_thread.isRunning():
            self.worker_thread.quit()
            self.worker_thread.wait(1500)