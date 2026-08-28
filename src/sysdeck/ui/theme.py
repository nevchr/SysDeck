APP_STYLE = """
QMainWindow {
    background-color: #171717;
}

QWidget {
    color: #f2f2f2;
    font-family: "Segoe UI";
    font-size: 14px;
}

#sidebar {
    background-color: #1b1b1b;
    border-right: 1px solid #252525;
}

#appTitle {
    font-size: 19px;
    font-weight: 600;
    padding: 2px 4px;
}

QPushButton#navButton {
    background-color: transparent;
    border: none;
    border-radius: 8px;
    text-align: left;
    padding: 11px 12px;
    color: #c8c8c8;
}

QPushButton#navButton:hover {
    background-color: #242424;
    color: #ffffff;
}

QPushButton#navButton:checked {
    background-color: #2b2b2b;
    color: #ffffff;
}

#contentArea,
#storageContent {
    background-color: #171717;
}

#pageTitle {
    font-size: 29px;
    font-weight: 600;
}

#pageDescription {
    color: #929292;
    font-size: 14px;
}

#metricCard,
#driveCard,
#summaryCard,
#resultCard,
#scanPanel {
    background-color: #1e1e1e;
    border: 1px solid #292929;
    border-radius: 12px;
}

#metricTitle {
    color: #929292;
    font-size: 13px;
}

#metricValue {
    color: #f5f5f5;
    font-size: 30px;
    font-weight: 600;
}

#metricDetail {
    color: #777777;
    font-size: 12px;
}

#driveTitle {
    color: #f2f2f2;
    font-size: 16px;
    font-weight: 600;
}

#drivePercent {
    color: #bdbdbd;
    font-size: 14px;
    font-weight: 600;
}

#driveUsageText {
    color: #9a9a9a;
    font-size: 13px;
}

#driveFreeText {
    color: #777777;
    font-size: 12px;
}

#selectedPath,
#searchStatus,
#processStatus {
    color: #777777;
    font-size: 12px;
}

#scanStatus {
    color: #a0a0a0;
    font-size: 13px;
}

#summaryTitle {
    color: #828282;
    font-size: 12px;
}

#summaryValue {
    color: #f2f2f2;
    font-size: 22px;
    font-weight: 600;
}

#resultTitle {
    color: #f0f0f0;
    font-size: 16px;
    font-weight: 600;
}

QProgressBar#storageProgress {
    background-color: #292929;
    border: none;
    border-radius: 4px;

    min-height: 8px;
    max-height: 8px;
}

QProgressBar#storageProgress::chunk {
    background-color: #b5b5b5;
    border-radius: 4px;
}

QProgressBar#scanProgress {
    background-color: #292929;

    border: none;
    border-radius: 3px;

    min-height: 5px;
    max-height: 5px;
}

QProgressBar#scanProgress::chunk {
    background-color: #a8a8a8;
    border-radius: 3px;
}

QPushButton#primaryButton {
    background-color: #eeeeee;
    color: #181818;

    border: none;
    border-radius: 8px;

    padding: 9px 14px;

    font-weight: 600;
}

QPushButton#primaryButton:hover {
    background-color: #ffffff;
}

QPushButton#primaryButton:pressed {
    background-color: #d8d8d8;
}

QPushButton#primaryButton:disabled {
    background-color: #555555;
    color: #999999;
}

QPushButton#secondaryButton {
    background-color: #232323;
    color: #d0d0d0;

    border: 1px solid #303030;
    border-radius: 8px;

    padding: 9px 14px;
}

QPushButton#secondaryButton:hover {
    background-color: #292929;
    color: #ffffff;
}

QPushButton#secondaryButton:pressed {
    background-color: #333333;
}

QPushButton#secondaryButton:disabled {
    background-color: #1f1f1f;
    color: #555555;
}

QLineEdit#processSearch,
QLineEdit#searchInput {
    background-color: #1e1e1e;
    color: #f2f2f2;

    border: 1px solid #303030;
    border-radius: 9px;

    padding: 9px 11px;

    selection-background-color: #444444;
}

QLineEdit#searchInput {
    padding: 12px 14px;
    font-size: 15px;
    border-radius: 10px;
}

QLineEdit#processSearch:hover,
QLineEdit#searchInput:hover {
    border-color: #3a3a3a;
}

QLineEdit#processSearch:focus,
QLineEdit#searchInput:focus {
    border-color: #505050;
}

QComboBox#searchFilter {
    background-color: #202020;
    color: #d0d0d0;

    border: 1px solid #303030;
    border-radius: 8px;

    padding: 8px 10px;
}

QComboBox#searchFilter:hover {
    background-color: #252525;
    border-color: #3a3a3a;
}

QComboBox#searchFilter:focus {
    border-color: #505050;
}

QComboBox#searchFilter::drop-down {
    border: none;
    width: 24px;
}

QComboBox#searchFilter QAbstractItemView {
    background-color: #202020;
    color: #dedede;

    border: 1px solid #343434;

    selection-background-color: #303030;
    selection-color: #ffffff;

    outline: none;
}

QTableView#processTable,
QTableWidget#storageResultTable,
QTableWidget#searchResults {
    background-color: #1b1b1b;
    alternate-background-color: #1e1e1e;

    color: #dedede;

    border: 1px solid #292929;
    border-radius: 9px;

    outline: none;

    selection-background-color: #303030;
    selection-color: #ffffff;
}

QTableView#processTable::item,
QTableWidget#storageResultTable::item,
QTableWidget#searchResults::item {
    padding-left: 8px;
    padding-right: 8px;
    border: none;
}

QTableView#processTable::item:selected,
QTableWidget#storageResultTable::item:selected,
QTableWidget#searchResults::item:selected {
    background-color: #303030;
    color: #ffffff;
}

QHeaderView::section {
    background-color: #202020;
    color: #929292;

    border: none;
    border-bottom: 1px solid #303030;

    padding: 9px;

    font-size: 12px;
    font-weight: 600;
}

QScrollArea {
    background-color: transparent;
    border: none;
}

QScrollBar:vertical {
    background-color: transparent;
    width: 10px;
    margin: 2px;
}

QScrollBar::handle:vertical {
    background-color: #363636;
    border-radius: 4px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background-color: #464646;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    background-color: transparent;
    height: 10px;
}

QScrollBar::handle:horizontal {
    background-color: #363636;
    border-radius: 4px;
    min-width: 30px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #464646;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0px;
}
#sectionTitle {
    color: #eeeeee;
    font-size: 18px;
    font-weight: 600;
}

QPushButton#dashboardAction {
    background-color: #1e1e1e;
    color: #d8d8d8;

    border: 1px solid #292929;
    border-radius: 10px;

    padding: 14px;

    text-align: left;
}

QPushButton#dashboardAction:hover {
    background-color: #252525;
    border-color: #363636;
    color: #ffffff;
}

QPushButton#dashboardAction:pressed {
    background-color: #2b2b2b;
}
"""