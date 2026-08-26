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

#contentArea {
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
#metricCard {
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
#performanceChart {
    background-color: #1e1e1e;
    border: 1px solid #292929;
    border-radius: 12px;
}
"""