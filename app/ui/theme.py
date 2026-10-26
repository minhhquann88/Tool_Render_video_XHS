from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

ACCENT = "#ff2e4d"

_QSS = f"""
* {{ font-family: "Segoe UI"; font-size: 13px; }}
QToolTip {{ background: #24262d; color: #e6e7ea; border: 1px solid #343842; padding: 4px 6px; }}

QFrame#Card {{ background: #1e2026; border: 1px solid #2a2d34; border-radius: 10px; }}
QLabel#AppTitle {{ font-size: 18px; font-weight: 700; color: #ffffff; }}
QLabel#SectionTitle {{ font-size: 14px; font-weight: 600; color: #ffffff; }}
QLabel#Muted {{ color: #8a8f98; }}

QLabel#Summary {{ font-size: 13px; color: #e6e7ea; padding: 10px 12px; background: #16171c;
                  border: 1px solid #2a2d34; border-radius: 8px; }}
QLabel#Summary[ok="true"] {{ color: #3ecf8e; border-color: #1f4a37; background: #12221b; }}

QPushButton#StepTab {{ background: transparent; border: none; border-bottom: 2px solid #2a2d34; border-radius: 0;
                       padding: 10px 4px; color: #8a8f98; font-weight: 600; }}
QPushButton#StepTab:hover {{ color: #e6e7ea; background: #22252b; }}
QPushButton#StepTab[done="true"] {{ color: #3ecf8e; }}
QPushButton#StepTab:checked {{ color: #ffffff; border-bottom: 2px solid {ACCENT}; background: #22252b; }}
QPushButton#Big {{ padding: 10px 16px; font-size: 14px; }}
QFrame#StepPanel {{ background: #1e2026; border: 1px solid #2a2d34; border-radius: 10px; }}

QPushButton {{ background: #2a2d34; border: 1px solid #343842; border-radius: 6px; padding: 6px 12px; color: #e6e7ea; }}
QPushButton:hover {{ background: #343842; }}
QPushButton:pressed {{ background: #3d424d; }}
QPushButton:disabled {{ color: #5d626b; background: #22252b; border-color: #2a2d34; }}
QPushButton[accent="true"] {{ background: {ACCENT}; border-color: {ACCENT}; color: white; font-weight: 600; }}
QPushButton[accent="true"]:hover {{ background: #ff4a64; }}
QPushButton[accent="true"]:disabled {{ background: #5a2630; border-color: #5a2630; color: #b9a0a5; }}
QPushButton#IconButton {{ padding: 4px; min-width: 30px; }}
QCheckBox:disabled, QGroupBox:disabled {{ color: #5d626b; }}

QLineEdit, QPlainTextEdit, QSpinBox, QComboBox {{
    background: #121317; border: 1px solid #2c2f36; border-radius: 6px; padding: 5px 8px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{ background: #1e2026; border: 1px solid #343842; selection-background-color: #3a1820; }}

QListWidget, QTableWidget {{
    background: #121317; border: 1px solid #2c2f36; border-radius: 8px;
    alternate-background-color: #16171c; gridline-color: #24262c; outline: none;
}}
QListWidget::item {{ padding: 8px 6px; border-radius: 6px; margin: 2px; }}
QListWidget::item:selected, QTableWidget::item:selected {{ background: #3a1820; color: #ffffff; }}
QListWidget::item:hover {{ background: #1f2127; }}
QHeaderView::section {{ background: #1e2026; color: #8a8f98; border: none; border-bottom: 1px solid #2c2f36; padding: 6px; }}
QTableCornerButton::section {{ background: #1e2026; border: none; }}

QTabWidget::pane {{ border: 1px solid #2a2d34; border-radius: 10px; background: #1e2026; top: -1px; }}
QTabBar::tab {{ background: transparent; padding: 8px 16px; color: #8a8f98; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: #ffffff; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:hover {{ color: #e6e7ea; }}

QGroupBox {{ border: 1px solid #2a2d34; border-radius: 8px; margin-top: 14px; padding: 12px 10px 10px 10px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #c9ccd1; }}

QSlider::groove:horizontal {{ height: 4px; background: #2c2f36; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: #ffffff; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px; }}

QProgressBar {{ background: #121317; border: 1px solid #2c2f36; border-radius: 6px; text-align: center; min-height: 18px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #343842; border-radius: 4px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #343842; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}

QSplitter::handle {{ background: transparent; }}
QStatusBar {{ background: #121317; color: #8a8f98; }}
QPlainTextEdit#Log {{ background: #101114; font-family: Consolas, monospace; font-size: 12px; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    colors = {
        QPalette.Window: "#16171b",
        QPalette.WindowText: "#e6e7ea",
        QPalette.Base: "#121317",
        QPalette.AlternateBase: "#16171c",
        QPalette.Text: "#e6e7ea",
        QPalette.Button: "#2a2d34",
        QPalette.ButtonText: "#e6e7ea",
        QPalette.Highlight: ACCENT,
        QPalette.HighlightedText: "#ffffff",
        QPalette.ToolTipBase: "#24262d",
        QPalette.ToolTipText: "#e6e7ea",
        QPalette.PlaceholderText: "#6b7079",
        QPalette.Link: "#4ea1ff",
    }
    for role, color in colors.items():
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    app.setStyleSheet(_QSS)


def accent(button):
    """Đánh dấu nút chính (màu đỏ XHS)."""
    button.setProperty("accent", True)
    return button
