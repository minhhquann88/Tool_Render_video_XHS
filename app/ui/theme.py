from pathlib import Path

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

ACCENT = "#ff2e4d"
_ASSETS = (Path(__file__).resolve().parent.parent / "assets").as_posix()  # ảnh mũi tên ô số

_QSS = f"""
* {{ font-family: "Segoe UI"; font-size: 13px; }}
QToolTip {{ background: #24262d; color: #e6e7ea; border: 1px solid #343842; padding: 6px 10px; }}

QFrame#Card {{ background: #1e2026; border: 1px solid #2a2d34; border-radius: 10px; }}
QLabel#AppTitle {{ font-size: 18px; font-weight: 700; color: #ffffff; }}
QLabel#SectionTitle {{ font-size: 14px; font-weight: 600; color: #ffffff; }}
QLabel#Muted {{ color: #8a8f98; }}

QLabel#Summary {{ font-size: 13px; color: #e6e7ea; padding: 12px 14px; background: #16171c;
                  border: 1px solid #2a2d34; border-radius: 8px; }}
QLabel#Summary[ok="true"] {{ color: #3ecf8e; border-color: #1f4a37; background: #12221b; }}
QLabel#Summary[warn="true"] {{ color: #f5b94a; border-color: #5a4316; background: #231c0e; }}

QFrame#TopBar {{ border-bottom: 1px solid #23252b; }}
QFrame#Separator {{ background: #2a2d34; border: none; }}
QFrame#AutoBar {{ background: #1b1d22; border-top: 1px solid #2a2d34;
                  border-bottom-left-radius: 10px; border-bottom-right-radius: 10px; }}

/* mục tiêu */
QFrame#Goal {{ background: #16171c; border: 1px solid #2a2d34; border-radius: 10px; }}
QFrame#Goal:hover {{ background: #24262d; }}
QFrame#Goal[selected="true"] {{ background: #2a1a1f; border-color: {ACCENT}; }}
QFrame#Goal:focus {{ border-color: #7cb7ff; }}
QLabel#GoalTitle {{ font-weight: 600; color: #ffffff; }}
QLabel#GoalDesc {{ font-size: 12px; color: #a9aeb6; }}
QLabel#GoalCount {{ font-size: 11px; color: #9aa0a9; }}
QLabel#GoalCount[selected="true"] {{ color: #ff9fb2; }}

/* bước gập / mở */
QFrame#StepCard {{ background: #1a1c21; border: 1px solid #2a2d34; border-radius: 10px; }}
QFrame#StepCard[open="true"] {{ border-color: #3a3e48; }}
QFrame#StepHead {{ background: transparent; border: none; border-radius: 10px; }}
QFrame#StepHead:hover {{ background: #22252b; }}
QFrame#StepHead:focus {{ background: #22252b; }}
QLabel#Badge {{ border-radius: 14px; background: #2a2d34; color: #ffffff; font-weight: 700; }}
QLabel#Badge[state="open"] {{ background: {ACCENT}; }}
QLabel#Badge[state="done"] {{ background: #173a2b; color: #3ecf8e; }}
QLabel#Badge[state="run"] {{ background: #3d2f12; color: #f5a524; }}
QLabel#StepTitle {{ font-size: 14px; font-weight: 600; color: #ffffff; }}
QLabel#StepStatus {{ font-size: 12px; color: #9aa0a9; }}
QLabel#StepStatus[tone="ok"] {{ color: #3ecf8e; }}
QLabel#StepStatus[tone="warn"], QLabel#StepStatus[tone="run"] {{ color: #f5a524; }}
QLabel#StepStatus[tone="error"] {{ color: #ff7a7a; }}
QFrame#SubBox {{ background: #16171c; border: 1px solid #2a2d34; border-radius: 8px; }}
QFrame#WarnBox {{ background: #2a2214; border: 1px solid #5a4318; border-radius: 8px; }}
QLabel#WarnText {{ color: #f8d58e; }}
QLabel#Chip {{ font-size: 12px; color: #9aa0a9; background: #16171c; border: 1px solid #2c2f36;
               border-radius: 12px; padding: 5px 12px; }}
QLabel#Chip[ok="true"] {{ color: #9be7c4; background: #12221b; border-color: #1f4a37; }}
QLabel#Avatar {{ border-radius: 18px; background: #3a1820; color: #ffb3c1; font-weight: 700; }}
QPushButton#Preset {{ padding: 7px 14px; }}
QPushButton#Preset:checked {{ border-color: {ACCENT}; }}

/* cài đặt */
QFrame#SettingRow {{ border: 1px solid transparent; border-radius: 10px; }}
QFrame#SettingRow[tone="warn"] {{ background: #231d12; border-color: #5a4318; }}
QLabel#StateIcon {{ border-radius: 11px; border: 1px solid #5d626b; font-size: 11px; font-weight: 700; }}
QLabel#StateIcon[tone="ok"] {{ background: #12221b; color: #3ecf8e; border-color: #1f4a37; }}
QLabel#StateIcon[tone="warn"] {{ background: #3d2f12; color: #f5a524; border-color: #5a4318; }}

QPushButton#Big {{ padding: 11px 22px; font-size: 14px; min-height: 22px; }}
QPushButton#Ghost, QPushButton#Link {{ background: transparent; border-color: transparent; color: #c9ccd1; }}
QPushButton#Ghost:hover {{ background: #22252b; }}
QPushButton#Ghost:checked {{ background: #22252b; color: #ffffff; }}
QPushButton#Danger {{ color: #ff8a9e; border-color: #5a2630; }}
QPushButton#Danger:hover {{ background: #3a1820; }}
QPushButton#Link {{ color: #7cb7ff; padding: 2px 4px; }}
QPushButton#Link:hover {{ color: #a8cfff; }}
QPushButton#HeaderChip {{ background: transparent; border-color: transparent; padding: 6px 12px; font-size: 12px;
                          color: #c9ccd1; }}
QPushButton#HeaderChip:hover {{ background: #22252b; }}
QPushButton#HeaderChip[tone="warn"] {{ color: #f5a524; }}
QFrame#SegGroup {{ background: #121317; border: 1px solid #2c2f36; border-radius: 8px; }}
QPushButton#Seg {{ background: transparent; border: none; border-radius: 6px; padding: 6px 14px; color: #9aa0a9; }}
QPushButton#Seg:hover {{ color: #e6e7ea; }}
QPushButton#Seg:checked {{ background: #343842; color: #ffffff; }}
QListWidget#VideoList {{ background: transparent; border: none; }}

QPushButton {{ background: #2a2d34; border: 1px solid #343842; border-radius: 6px; padding: 8px 16px; color: #e6e7ea; }}
QPushButton:hover {{ background: #343842; }}
QPushButton:pressed {{ background: #3d424d; }}
QPushButton:disabled {{ color: #5d626b; background: #22252b; border-color: #2a2d34; }}
QPushButton[accent="true"] {{ background: {ACCENT}; border-color: {ACCENT}; color: white; font-weight: 600; }}
QPushButton[accent="true"]:hover {{ background: #ff4a64; }}
QPushButton[accent="true"]:disabled {{ background: #5a2630; border-color: #5a2630; color: #b9a0a5; }}
QPushButton#IconButton {{ padding: 6px; min-width: 32px; min-height: 22px; }}
QCheckBox:disabled, QGroupBox:disabled {{ color: #5d626b; }}

QLineEdit, QPlainTextEdit, QSpinBox, QComboBox {{
    background: #121317; border: 1px solid #2c2f36; border-radius: 6px; padding: 7px 10px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox {{ padding-right: 26px; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url({_ASSETS}/arrow_down.svg); width: 10px; height: 6px; }}
QComboBox::down-arrow:disabled {{ image: none; }}
QSpinBox {{ padding-right: 24px; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 20px; border: none; border-left: 1px solid #2c2f36;
                                              background: transparent; }}
QSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; border-top-right-radius: 6px; }}
QSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; border-bottom-right-radius: 6px; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: #24262d; }}
QSpinBox::up-arrow {{ image: url({_ASSETS}/arrow_up.svg); width: 10px; height: 6px; }}
QSpinBox::down-arrow {{ image: url({_ASSETS}/arrow_down.svg); width: 10px; height: 6px; }}
QComboBox QAbstractItemView {{ background: #1e2026; border: 1px solid #343842; selection-background-color: #3a1820; }}

QListWidget, QTableWidget {{
    background: #121317; border: 1px solid #2c2f36; border-radius: 8px;
    alternate-background-color: #16171c; gridline-color: #24262c; outline: none;
}}
QListWidget::item {{ padding: 10px 10px; border-radius: 6px; margin: 2px; }}
QListWidget::item:selected, QTableWidget::item:selected {{ background: #3a1820; color: #ffffff; }}
QListWidget::item:hover {{ background: #1f2127; }}
QHeaderView::section {{ background: #1e2026; color: #8a8f98; border: none; border-bottom: 1px solid #2c2f36; padding: 8px 12px; }}
QTableCornerButton::section {{ background: #1e2026; border: none; }}
QTableWidget#SubTable {{ font-size: 14px; }}
QTableWidget#SubTable::item {{ padding: 8px 12px; }}
QTableWidget#SubTable QPlainTextEdit {{ font-size: 14px; border-radius: 4px; }}

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
