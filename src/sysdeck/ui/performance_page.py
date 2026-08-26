import time
from collections import deque

import psutil

from PySide6.QtCore import QPointF, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class HistoryGraph(QWidget):
    def __init__(self, history, max_points=60):
        super().__init__()

        self.history = history
        self.max_points = max_points

        self.setMinimumHeight(180)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if len(self.history) < 2:
            return

        padding = 8

        graph_width = self.width() - (padding * 2)
        graph_height = self.height() - (padding * 2)

        pen = QPen(QColor("#b8b8b8"))
        pen.setWidthF(2.0)

        painter.setPen(pen)

        points = []

        for index, value in enumerate(self.history):
            x = padding + (
                index / (self.max_points - 1)
            ) * graph_width

            y = padding + (
                1 - (value / 100)
            ) * graph_height

            points.append(QPointF(x, y))

        for index in range(len(points) - 1):
            painter.drawLine(
                points[index],
                points[index + 1],
            )


class PerformancePage(QWidget):
    def __init__(self):
        super().__init__()

        self.history_length = 60

        self.cpu_history = deque(
            maxlen=self.history_length
        )

        self.memory_history = deque(
            maxlen=self.history_length
        )

        # Used to calculate per-second disk/network activity.
        self.last_disk_counters = None
        self.last_network_counters = None
        self.last_rate_sample_time = None

        self.setup_ui()
        self.setup_timer()
        self.update_stats()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        layout.setContentsMargins(46, 40, 46, 40)
        layout.setSpacing(24)

        # -----------------------------------------------------
        # Page heading
        # -----------------------------------------------------

        title = QLabel("Performance")
        title.setObjectName("pageTitle")

        description = QLabel(
            "Live overview of system resources and activity."
        )
        description.setObjectName("pageDescription")

        layout.addWidget(title)
        layout.addWidget(description)

        # -----------------------------------------------------
        # Metric cards
        # -----------------------------------------------------

        stats_grid = QGridLayout()

        stats_grid.setHorizontalSpacing(18)
        stats_grid.setVerticalSpacing(18)

        stats_grid.setColumnStretch(0, 1)
        stats_grid.setColumnStretch(1, 1)
        stats_grid.setColumnStretch(2, 1)

        self.cpu_value = QLabel("--")
        self.memory_value = QLabel("--")
        self.uptime_value = QLabel("--")

        self.process_value = QLabel("--")
        self.disk_value = QLabel("--")
        self.network_value = QLabel("--")

        self.cpu_detail = QLabel("--")
        self.memory_detail = QLabel("--")
        self.uptime_detail = QLabel("Since last boot")

        self.process_detail = QLabel("Running processes")
        self.disk_detail = QLabel("Write --")
        self.network_detail = QLabel("Upload --")

        cpu_card = self.create_metric_card(
            "CPU Usage",
            self.cpu_value,
            self.cpu_detail,
        )

        memory_card = self.create_metric_card(
            "Memory Usage",
            self.memory_value,
            self.memory_detail,
        )

        uptime_card = self.create_metric_card(
            "System Uptime",
            self.uptime_value,
            self.uptime_detail,
        )

        process_card = self.create_metric_card(
            "Processes",
            self.process_value,
            self.process_detail,
        )

        disk_card = self.create_metric_card(
            "Disk Activity",
            self.disk_value,
            self.disk_detail,
        )

        network_card = self.create_metric_card(
            "Network Activity",
            self.network_value,
            self.network_detail,
        )

        stats_grid.addWidget(cpu_card, 0, 0)
        stats_grid.addWidget(memory_card, 0, 1)
        stats_grid.addWidget(uptime_card, 0, 2)

        stats_grid.addWidget(process_card, 1, 0)
        stats_grid.addWidget(disk_card, 1, 1)
        stats_grid.addWidget(network_card, 1, 2)

        layout.addLayout(stats_grid)

        # -----------------------------------------------------
        # History graphs
        # -----------------------------------------------------

        charts_grid = QGridLayout()

        charts_grid.setHorizontalSpacing(18)
        charts_grid.setVerticalSpacing(18)

        charts_grid.setColumnStretch(0, 1)
        charts_grid.setColumnStretch(1, 1)

        self.cpu_chart = HistoryGraph(
            self.cpu_history,
            self.history_length,
        )

        self.memory_chart = HistoryGraph(
            self.memory_history,
            self.history_length,
        )

        cpu_chart_card = self.create_chart_card(
            "CPU History",
            self.cpu_chart,
        )

        memory_chart_card = self.create_chart_card(
            "Memory History",
            self.memory_chart,
        )

        charts_grid.addWidget(
            cpu_chart_card,
            0,
            0,
        )

        charts_grid.addWidget(
            memory_chart_card,
            0,
            1,
        )

        layout.addLayout(charts_grid)
        layout.addStretch()

    def create_metric_card(
        self,
        title,
        value_label,
        detail_label,
    ):
        card = QWidget()
        card.setObjectName("metricCard")

        layout = QVBoxLayout(card)

        layout.setContentsMargins(
            20,
            18,
            20,
            18,
        )

        layout.setSpacing(8)

        title_label = QLabel(title)
        title_label.setObjectName("metricTitle")

        value_label.setObjectName("metricValue")
        detail_label.setObjectName("metricDetail")

        layout.addWidget(title_label)
        layout.addWidget(value_label)
        layout.addWidget(detail_label)

        return card

    def create_chart_card(
        self,
        title,
        chart_widget,
    ):
        card = QWidget()
        card.setObjectName("metricCard")

        layout = QVBoxLayout(card)

        layout.setContentsMargins(
            18,
            16,
            18,
            16,
        )

        layout.setSpacing(10)

        title_label = QLabel(title)
        title_label.setObjectName("metricTitle")

        layout.addWidget(title_label)
        layout.addWidget(chart_widget)

        return card

    def setup_timer(self):
        self.timer = QTimer(self)

        self.timer.timeout.connect(
            self.update_stats
        )

        self.timer.start(1000)

    def update_stats(self):
        # -----------------------------------------------------
        # CPU
        # -----------------------------------------------------

        cpu_percent = psutil.cpu_percent(
            interval=None
        )

        physical_cores = psutil.cpu_count(
            logical=False
        )

        logical_cores = psutil.cpu_count(
            logical=True
        )

        # -----------------------------------------------------
        # Memory
        # -----------------------------------------------------

        memory = psutil.virtual_memory()

        memory_percent = memory.percent

        memory_used_gb = (
            memory.used / (1024 ** 3)
        )

        memory_total_gb = (
            memory.total / (1024 ** 3)
        )

        # -----------------------------------------------------
        # Uptime + processes
        # -----------------------------------------------------

        uptime_seconds = (
            time.time() - psutil.boot_time()
        )

        process_count = len(
            psutil.pids()
        )

        # -----------------------------------------------------
        # Disk + network rates
        # -----------------------------------------------------

        disk_counters = (
            psutil.disk_io_counters()
        )

        network_counters = (
            psutil.net_io_counters()
        )

        current_time = time.monotonic()

        disk_read_rate = 0
        disk_write_rate = 0

        network_download_rate = 0
        network_upload_rate = 0

        if (
            self.last_rate_sample_time is not None
            and disk_counters is not None
            and self.last_disk_counters is not None
        ):
            elapsed = (
                current_time
                - self.last_rate_sample_time
            )

            if elapsed > 0:
                disk_read_rate = max(
                    0,
                    disk_counters.read_bytes
                    - self.last_disk_counters.read_bytes,
                ) / elapsed

                disk_write_rate = max(
                    0,
                    disk_counters.write_bytes
                    - self.last_disk_counters.write_bytes,
                ) / elapsed

        if (
            self.last_rate_sample_time is not None
            and network_counters is not None
            and self.last_network_counters is not None
        ):
            elapsed = (
                current_time
                - self.last_rate_sample_time
            )

            if elapsed > 0:
                network_download_rate = max(
                    0,
                    network_counters.bytes_recv
                    - self.last_network_counters.bytes_recv,
                ) / elapsed

                network_upload_rate = max(
                    0,
                    network_counters.bytes_sent
                    - self.last_network_counters.bytes_sent,
                ) / elapsed

        self.last_disk_counters = disk_counters
        self.last_network_counters = network_counters

        self.last_rate_sample_time = (
            current_time
        )

        # -----------------------------------------------------
        # Graph history
        # -----------------------------------------------------

        self.cpu_history.append(
            cpu_percent
        )

        self.memory_history.append(
            memory_percent
        )

        self.cpu_chart.update()
        self.memory_chart.update()

        # -----------------------------------------------------
        # Update labels
        # -----------------------------------------------------

        self.cpu_value.setText(
            f"{cpu_percent:.0f}%"
        )

        self.cpu_detail.setText(
            f"{physical_cores} cores · "
            f"{logical_cores} logical"
        )

        self.memory_value.setText(
            f"{memory_percent:.0f}%"
        )

        self.memory_detail.setText(
            f"{memory_used_gb:.1f} / "
            f"{memory_total_gb:.1f} GB"
        )

        self.uptime_value.setText(
            self.format_uptime(
                uptime_seconds
            )
        )

        self.process_value.setText(
            str(process_count)
        )

        self.disk_value.setText(
            f"R {self.format_rate(disk_read_rate)}"
        )

        self.disk_detail.setText(
            f"W {self.format_rate(disk_write_rate)}"
        )

        self.network_value.setText(
            f"↓ {self.format_rate(network_download_rate)}"
        )

        self.network_detail.setText(
            f"↑ {self.format_rate(network_upload_rate)}"
        )

    def format_uptime(self, seconds):
        seconds = int(seconds)

        days, remainder = divmod(
            seconds,
            86400,
        )

        hours, remainder = divmod(
            remainder,
            3600,
        )

        minutes, _ = divmod(
            remainder,
            60,
        )

        if days > 0:
            return f"{days}d {hours}h"

        if hours > 0:
            return f"{hours}h {minutes}m"

        return f"{minutes}m"

    def format_rate(self, bytes_per_second):
        if bytes_per_second >= 1024 ** 3:
            return (
                f"{bytes_per_second / (1024 ** 3):.1f} GB/s"
            )

        if bytes_per_second >= 1024 ** 2:
            return (
                f"{bytes_per_second / (1024 ** 2):.1f} MB/s"
            )

        if bytes_per_second >= 1024:
            return (
                f"{bytes_per_second / 1024:.1f} KB/s"
            )

        return f"{bytes_per_second:.0f} B/s"