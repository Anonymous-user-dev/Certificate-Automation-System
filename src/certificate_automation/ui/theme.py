"""Calm, high-contrast visual tokens for the operator workspace."""

from __future__ import annotations


TOKENS = {
    "canvas": "#F4F6FA",
    "surface": "#FFFFFF",
    "surface_alt": "#EEF2F8",
    "text": "#172033",
    "muted": "#5D687A",
    "border": "#D8DEE9",
    "accent": "#2457D6",
    "accent_hover": "#1948BD",
    "success": "#197044",
    "warning": "#9A5A00",
    "error": "#B42318",
    "focus": "#7AA2FF",
}


def application_stylesheet(scale: float = 1.0) -> str:
    primary_height = round(44 * scale)
    radius = round(10 * scale)
    padding = round(12 * scale)
    return f"""
        QWidget {{
            color: {TOKENS['text']};
            background: {TOKENS['canvas']};
            font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
            font-size: 10.5pt;
        }}
        QFrame[role="surface"], QWidget[role="surface"] {{
            background: {TOKENS['surface']};
            border: 1px solid {TOKENS['border']};
            border-radius: {radius}px;
        }}
        QLabel[role="title"] {{
            font-size: 21pt;
            font-weight: 700;
            background: transparent;
        }}
        QLabel[role="muted"] {{ color: {TOKENS['muted']}; background: transparent; }}
        QPushButton {{
            min-height: {primary_height - 8}px;
            padding: 0 {padding}px;
            border: 1px solid {TOKENS['border']};
            border-radius: {radius - 2}px;
            background: {TOKENS['surface']};
        }}
        QPushButton:hover {{ border-color: {TOKENS['accent']}; }}
        QPushButton[role="primary"] {{
            min-height: {primary_height}px;
            background: {TOKENS['accent']};
            border-color: {TOKENS['accent']};
            color: white;
            font-weight: 600;
        }}
        QPushButton[role="primary"]:hover {{ background: {TOKENS['accent_hover']}; }}
        QPushButton[stepState="current"] {{
            background: #E8EEFF;
            border-color: {TOKENS['accent']};
            color: {TOKENS['accent']};
            font-weight: 600;
        }}
        QPushButton[stepState="complete"] {{ color: {TOKENS['success']}; }}
        QLineEdit, QComboBox, QTableView, QListWidget {{
            background: {TOKENS['surface']};
            border: 1px solid {TOKENS['border']};
            border-radius: {radius - 3}px;
            padding: 6px;
        }}
        QPushButton:focus, QComboBox:focus, QLineEdit:focus, QTableView:focus {{
            border: 2px solid {TOKENS['focus']};
        }}
        QFrame[bannerState="error"] {{
            background: #FEF3F2;
            border: 1px solid #FDA29B;
            border-radius: {radius - 2}px;
        }}
        QLabel[state="error"] {{ color: {TOKENS['error']}; background: transparent; }}
    """
