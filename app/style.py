# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Graphite theme; state colors always accompany text."""
from pathlib import Path
STYLESHEET = """
QWidget { color: #e8ebef; font-family: 'Segoe UI'; font-size: 10pt; }
QMainWindow, QWidget#workspaces, QWidget#root, QScrollArea, QStatusBar { background: #101318; }
QFrame#sparkTitleBar { background: #151c25; border-bottom: 1px solid #2b3644; }
QLabel#sparkWindowName { color: #edf4fc; font-size: 11pt; font-weight: 600; }
QLabel#sparkWindowVersion { color: #8495aa; font-size: 8pt; padding-top: 2px; }
QScrollArea { border: none; }
QFrame#panel { background: #191e26; border: 1px solid #2b323d; border-radius: 8px; }
QLabel { background: transparent; }
QLabel#title { font-size: 18pt; font-weight: 600; color: #f6f7f9; }
QLabel#version, QLabel#muted, QLabel#hint { color: #9da7b5; font-size: 9pt; }
QLabel#sectionLabel { color: #9da7b5; font-size: 8pt; font-weight: 600; }
QLabel#fieldLabel { color: #bac3cf; font-size: 9pt; }
QLabel#identity { color: #e8ebef; font-weight: 600; }
QLabel#technical { font-family: Consolas; color: #9da7b5; font-size: 9pt; }
QLabel#operationStatus { font-weight: 600; font-size: 11pt; }
QLabel#operationStatus[tone="success"] { color: #72d7a1; }
QLabel#operationStatus[tone="error"] { color: #ff9292; }
QLabel#operationStatus[tone="warning"] { color: #f1be72; }
QLabel#percent { font-size: 17pt; font-weight: 600; }
QLabel#badge { color: #aeb8c6; background: #202630; border-radius: 6px; padding: 5px 10px; font-size: 9pt; }
QLabel#badge[state="connected"] { color: #86ddb0; background: #19362a; }
QLabel#badge[state="busy"] { color: #93c9ff; background: #1d324a; }
QLabel#credit { color: #8490a1; font-size: 8pt; padding: 3px 10px; }
QStatusBar { border-top: 1px solid #252c35; }
QLineEdit, QComboBox, QSpinBox {
 background: #11161d; color: #edf0f4; border: 1px solid #3a4351; border-radius: 6px;
 min-height: 32px; padding: 2px 10px; selection-background-color: #245d94;
}
QComboBox { padding: 2px 36px 2px 12px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 28px; border-left: 1px solid #303946; border-top-right-radius: 5px; border-bottom-right-radius: 5px; background: #1d242e; }
QComboBox::down-arrow { image: url(APP_ARROW_URL); width: 12px; height: 12px; }
QSpinBox { padding: 2px 28px 2px 10px; }
QSpinBox::up-button, QSpinBox::down-button { subcontrol-origin: padding; width: 23px; border: none; border-left: 1px solid #303946; background: #1d242e; }
QSpinBox::up-button { subcontrol-position: top right; border-top-right-radius: 5px; border-bottom: 1px solid #303946; }
QSpinBox::down-button { subcontrol-position: bottom right; border-bottom-right-radius: 5px; }
QSpinBox::up-arrow { image: url(APP_UP_ARROW_URL); width: 10px; height: 10px; }
QSpinBox::down-arrow { image: url(APP_ARROW_URL); width: 10px; height: 10px; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #65b5ff; }
QComboBox:disabled { color: #788494; background: #171c24; }
QSpinBox:disabled { color: #a8b2c1; background: #171c24; }
QComboBox QAbstractItemView { background: #202731; color: #edf0f4; border: 1px solid #414c5b; selection-background-color: #245d94; padding: 4px; }
QPushButton, QToolButton { background: #262e39; color: #e8ebef; border: 1px solid #414c5b; border-radius: 6px; min-height: 32px; padding: 3px 14px; }
QPushButton:hover, QToolButton:hover { background: #323d4c; border-color: #64758a; }
QPushButton:pressed { background: #1d2530; }
QPushButton:focus, QToolButton:focus { border-color: #65b5ff; }
QPushButton:disabled { background: #1c222b; color: #768292; border-color: #303946; }
QPushButton#primary { background: #226db4; border-color: #3887cf; color: white; }
QPushButton#primary:hover { background: #2b7bc6; }
QPushButton#primary:disabled { background: #20354a; color: #839bb0; border-color: #32485d; }
QPushButton#action { min-height: 38px; font-weight: 600; }
QPushButton#danger { min-height: 38px; color: #f1b0b0; border-color: #805050; background: #2b2228; }
QPushButton#danger:hover { background: #42292e; border-color: #b76b72; }
QPushButton#danger:disabled { color: #897c82; border-color: #44343b; background: #231e24; }
QPushButton#quiet, QPushButton#small, QToolButton { background: transparent; }
QPushButton#small { min-height: 24px; padding: 1px 10px; font-size: 9pt; border-color: #303946; }
QToolButton { border: none; padding: 1px 4px; }
QProgressBar { background: #10151c; border: none; border-radius: 4px; min-height: 9px; max-height: 9px; }
QProgressBar::chunk { background: #15803d; border-radius: 4px; }
QPlainTextEdit { background: #11161d; color: #bac3cf; border: 1px solid #303946; border-radius: 6px; padding: 6px; font-family: Consolas; font-size: 9pt; selection-background-color: #245d94; }
QScrollBar:vertical { background: #101318; width: 9px; margin: 0; }
QScrollBar::handle:vertical { background: #414c5b; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QDialog, QMessageBox { background: #191e26; }
QToolTip { background: #262e39; color: #edf0f4; border: 1px solid #414c5b; padding: 5px; }
QTabWidget::pane { border: none; background: #101318; }
QTabBar { background: #101318; }
QTabBar::tab { background: #101318; color: #8f9cad; padding: 12px 24px; border-bottom: 2px solid #262e39; }
QTabBar::tab:selected { color: #eef4fc; background: #191e26; border-bottom: 2px solid #5ed8bd; }
QTabBar::tab:hover { color: #d7e7f9; background: #1c2530; }
QTabBar::tab:disabled { color: #5c6878; }
QFrame#interfaceBar { background: #121820; border-bottom: 1px solid #26313d; }
QLabel#interfaceLabel { color: #a5b2c1; font-size: 9pt; }
QLabel#interfaceSeparator { color: #4a596b; font-size: 9pt; }
QLabel#interfaceDevice { color: #c6d4e3; font-size: 9pt; }
QLabel#interfaceStatus { color: #81d9bd; font-size: 9pt; }
QTabWidget#batterySections QTabBar::tab { padding: 8px 16px; }
QLabel#workspaceTitle { color: #f1f5fb; font-size: 15pt; font-weight: 600; }
QFrame#metricCard { background: #191e26; border: 1px solid #303b48; border-radius: 10px; }
QLabel#metricValue { color: #81e2cd; font-size: 24pt; font-weight: 600; }
QListWidget { background: #131922; border: 1px solid #2c3745; border-radius: 6px; outline: 0; }
QListWidget::item { padding: 9px 10px; border-bottom: 1px solid #222d39; }
QListWidget::item:selected { color: #e8fff9; background: #193d39; border-left: 3px solid #5ed8bd; }
QListWidget::item:hover { background: #222e3b; }
QTableWidget { background: #131922; border: 1px solid #2d3845; border-radius: 6px; selection-background-color: #23453f; }
QTableWidget::item { padding: 5px 7px; border-bottom: 1px solid #242f3c; }
QHeaderView::section { color: #a5b5c7; background: #1d2835; border: none; padding: 7px; font-size: 9pt; }
QTableCornerButton::section { background: #1d2835; border: none; }
QCheckBox { color: #acbacb; spacing: 8px; padding: 5px 0; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #596c82; border-radius: 4px; background: #131922; }
QCheckBox::indicator:checked { background: #359f8a; border-color: #5ed8bd; }
QScrollBar:horizontal { background: #101318; height: 9px; margin: 0; }
QScrollBar::handle:horizontal { background: #414c5b; border-radius: 4px; min-width: 24px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QWidget#batteryWorkspace, QWidget#batteryBody { background: #101318; }
QFrame#batteryHeader { background: #171d25; border: 1px solid #2b3541; border-radius: 8px; }
QWidget#batteryWorkspace QComboBox, QWidget#batteryWorkspace QLineEdit,
QWidget#batteryWorkspace QSpinBox { min-height: 26px; }
QWidget#batteryWorkspace QComboBox QLineEdit { border: none; background: transparent; min-height: 0; padding: 0; }
QWidget#batteryWorkspace QPushButton { min-height: 26px; }
QWidget#batteryWorkspace QFrame#metricCard { border: none; background: transparent; }
QWidget#batteryWorkspace QLabel#metricValue { font-size: 18pt; color: #e7f1f1; font-weight: 600; }
QWidget#batteryWorkspace QLabel#metricUnit { color: #9caebd; font-size: 9pt; }
QLabel#batteryIdentity { font-size: 13pt; font-weight: 600; color: #edf3fb; }
QLabel#batteryValue { color: #e2eaf4; font-size: 10pt; }
QLabel#batteryState { font-size: 17pt; font-weight: 600; color: #93a0b1; }
QLabel#batteryState[tone="warning"], QLabel#batteryBalance[tone="warning"],
QLabel#batteryFinding[tone="warning"] { color: #efc16f; }
QLabel#batteryState[tone="success"], QLabel#batteryBalance[tone="success"] { color: #81d9bd; }
QLabel#batteryBalance, QLabel#batteryFinding { color: #9aaaba; font-size: 9pt; }
QLabel#batteryFeedback { color: #9aaaba; font-size: 9pt; }
QLabel#batteryFeedback[tone="success"] { color: #84cdb7; }
QLabel#batteryFeedback[tone="error"] { color: #ffaaaa; }
QToolButton#batteryInlineAction { color: #83b5df; min-height: 20px; padding: 0 2px; border: none; background: transparent; font-size: 9pt; }
QToolButton#batteryInlineAction:hover { color: #b4d9f9; }
QToolButton#batteryReport { min-height: 24px; padding: 2px 10px; border: 1px solid #354354; border-radius: 5px; background: #19232e; font-size: 9pt; }
QToolButton#batteryLive { min-height: 26px; padding: 2px 12px; border: 1px solid #354354; border-radius: 5px; background: #19232e; }
QToolButton#batteryLive:checked { color: #9ce5ce; background: #1d3933; border-color: #4c9a84; }
QWidget#batteryWorkspace QMenu { background: #202a36; color: #e5ecf5; border: 1px solid #405064; padding: 4px; }
QWidget#batteryWorkspace QMenu::item { padding: 7px 20px; }
QWidget#batteryWorkspace QMenu::item:selected { background: #284c60; }
"""
STYLESHEET = STYLESHEET.replace("APP_ARROW_URL", (Path(__file__).parent / "assets/chevron-down.png").as_posix())
STYLESHEET = STYLESHEET.replace("APP_UP_ARROW_URL", (Path(__file__).parent / "assets/chevron-up.png").as_posix())
