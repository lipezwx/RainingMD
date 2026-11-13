#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Raining Md - a calm Markdown editor in the Raining Company palette.

Design follows GNOME's Apostrophe: one centred column of text, no clutter,
live preview on demand, a focus mode, and statistics that stay out of the way.
The window chrome (title bar, buttons, resize edges) is drawn by the app itself
so it shares the exact same look as the rest of the UI.

Requires: PySide6 >= 6.12, Markdown >= 3.6
"""
from __future__ import annotations

import html as htmllib
import re
import sys
from pathlib import Path
from string import Template

import markdown as mdlib
from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, QSettings, QSize, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontMetricsF,
    QIcon,
    QKeySequence,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QPolygonF,
    QShortcut,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextOption,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSizeGrip,
    QSplitter,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

APP_NAME = "Raining Md"
ORG_NAME = "Raining Company"
APP_VERSION = "1.0.0"

# --------------------------------------------------------------------------- #
# Palette: sampled from the Raining Company logo. Everything else is a mix of
# these two colours, so the UI can never drift off-brand.
# --------------------------------------------------------------------------- #
INK = QColor("#0D1311")
CREAM = QColor("#F8EFCC")


def mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
    )


class Theme:
    def __init__(self, name: str, bg: QColor, fg: QColor):
        self.name = name
        self.bg, self.fg = bg, fg
        self.panel = mix(bg, fg, 0.05)
        self.panel2 = mix(bg, fg, 0.09)
        self.hover = mix(bg, fg, 0.10)
        self.press = mix(bg, fg, 0.17)
        self.line = mix(bg, fg, 0.15)
        self.dim = mix(bg, fg, 0.30)    # unfocused text in focus mode
        self.muted = mix(bg, fg, 0.50)  # markup characters, hints
        self.soft = mix(bg, fg, 0.74)   # idle icons, secondary text


DARK = Theme("dark", INK, CREAM)
LIGHT = Theme("light", CREAM, INK)

UI_FONTS = ["Segoe UI Variable Text", "Segoe UI", "Inter", "Helvetica Neue", "Arial"]
DISPLAY_FONTS = ["Bahnschrift SemiBold Condensed", "Bahnschrift", "Segoe UI Semibold", "Arial Narrow"]
MONO_FONTS = ["Cascadia Mono", "Cascadia Code", "Consolas", "SF Mono", "DejaVu Sans Mono", "Courier New"]


def make_font(families, size=10.0, weight=None, italic=False) -> QFont:
    f = QFont()
    f.setFamilies(list(families))
    f.setPointSizeF(size)
    if weight is not None:
        f.setWeight(weight)
    f.setItalic(italic)
    return f


def css_families(families) -> str:
    return ",".join(f"'{x}'" for x in families)


def resource(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "assets" / name


WELCOME = """# Welcome to Raining Md

A calm place to write Markdown. Nothing here but you and the words.

## Things worth knowing

- **Bold**, *italic* and ~~strikethrough~~ work with `Ctrl+B`, `Ctrl+I` and `Ctrl+Shift+X`.
- `Ctrl+Shift+F` turns on focus mode: only the paragraph you are writing stays lit.
- `Ctrl+Shift+P` cycles the live preview: editor, split, preview.
- `F11` hides everything but the page.
- Lists and quotes continue when you press Enter.

> Rain is just the sky taking notes.

Open a file with `Ctrl+O`, or start typing.
"""

# --------------------------------------------------------------------------- #
# Stylesheets
# --------------------------------------------------------------------------- #
QSS = Template(
    """
QToolTip { background:$panel; color:$fg; border:1px solid $line; padding:5px 9px; }
QLabel { color:$fg; background:transparent; }
QLabel#stat { color:$muted; }
QPlainTextEdit, QTextBrowser { background:$bg; color:$fg; border:none;
    selection-background-color:$fg; selection-color:$bg; }
QLineEdit { background:$panel; color:$fg; border:1px solid $line; border-radius:8px;
    padding:6px 11px; selection-background-color:$fg; selection-color:$bg; }
QLineEdit:focus { border:1px solid $muted; }
QSplitter::handle { background:$line; }
QScrollBar:vertical { background:transparent; width:14px; margin:0; }
QScrollBar::handle:vertical { background:$line; border-radius:3px; min-height:40px; margin:2px 4px; }
QScrollBar::handle:vertical:hover { background:$muted; }
QScrollBar:horizontal { background:transparent; height:14px; margin:0; }
QScrollBar::handle:horizontal { background:$line; border-radius:3px; min-width:40px; margin:4px 2px; }
QScrollBar::handle:horizontal:hover { background:$muted; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0; }
QScrollBar::add-page, QScrollBar::sub-page { background:transparent; }
QMenu { background:$panel; color:$fg; border:1px solid $line; padding:6px; }
QMenu::item { padding:8px 36px 8px 16px; border-radius:6px; margin:1px 0; }
QMenu::item:selected { background:$fg; color:$bg; }
QMenu::separator { height:1px; background:$line; margin:6px 8px; }
QPushButton { font-size:10pt; border-radius:8px; padding:8px 18px; }
QPushButton#primary { background:$fg; color:$bg; border:1px solid $fg; font-weight:600; }
QPushButton#primary:hover { background:$soft; border-color:$soft; }
QPushButton#ghost { background:transparent; color:$fg; border:1px solid $line; }
QPushButton#ghost:hover { background:$hover; }
"""
)

PREVIEW_CSS = Template(
    """
body { color:$fg; font-family:$ui; font-size:${body}pt; }
p { margin:0 0 14px 0; line-height:168%; }
h1,h2,h3,h4,h5,h6 { font-family:$display; font-weight:600; color:$fg; }
h1 { font-size:${h1}pt; margin:6px 0 16px 0; }
h2 { font-size:${h2}pt; margin:30px 0 10px 0; }
h3 { font-size:${h3}pt; margin:22px 0 8px 0; }
h4,h5,h6 { font-size:${body}pt; margin:18px 0 6px 0; }
a { color:$fg; text-decoration:underline; }
code { font-family:$mono; background-color:$panel2; color:$fg; }
pre { font-family:$mono; background-color:$panel; color:$fg; margin:6px 0 18px 0; }
blockquote { color:$soft; margin:8px 0 16px 20px; }
li { margin-bottom:5px; line-height:160%; }
table { border-color:$line; border-style:solid; }
th { background-color:$panel; font-weight:600; }
"""
)

EXPORT_CSS = Template(
    """
body{margin:0;background:$bg;color:$fg;font:17px/1.7 'Segoe UI',system-ui,sans-serif}
main{max-width:720px;margin:0 auto;padding:64px 24px 96px}
h1,h2,h3{font-family:Bahnschrift,'Segoe UI',sans-serif;line-height:1.15;font-weight:600}
h1{font-size:2.4em;margin:0 0 .6em} h2{margin:1.8em 0 .5em} h3{margin:1.5em 0 .4em}
a{color:$fg}
code,pre{background:$panel2;font-family:'Cascadia Mono',Consolas,monospace;border-radius:6px;font-size:.9em}
code{padding:.1em .35em} pre{padding:16px;overflow:auto} pre code{padding:0;background:none}
blockquote{margin:1.2em 0;padding-left:18px;border-left:3px solid $fg;color:$soft}
table{border-collapse:collapse} td,th{border:1px solid $line;padding:8px 12px}
hr{border:0;border-top:1px solid $line;margin:2em 0}
img{max-width:100%}
"""
)


def theme_tokens(t: Theme) -> dict:
    return {k: getattr(t, k).name() for k in ("bg", "fg", "panel", "panel2", "hover", "press", "line", "dim", "muted", "soft")}


# --------------------------------------------------------------------------- #
# Small building blocks
# --------------------------------------------------------------------------- #
class Bar(QWidget):
    """A strip with a hairline on one edge."""

    def __init__(self, edge: str, parent=None):
        super().__init__(parent)
        self.edge = edge
        self.theme = DARK

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setPen(self.theme.line)
        y = self.height() - 1 if self.edge == "bottom" else 0
        p.drawLine(0, y, self.width(), y)


class IconButton(QAbstractButton):
    """Flat vector button. Glyphs are drawn in code, so they follow the theme."""

    TEXT_STYLES = {"bold": "B", "italic": "I", "strike": "S", "heading": "H", "quote": "\u201c", "code": "</>", "list": "\u2261", "link": "\u2197"}

    def __init__(self, kind: str, tip: str = "", size=(34, 34), checkable=False, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.mode = 0
        self.theme = DARK
        self.setToolTip(tip)
        self.setCheckable(checkable)
        self.setFixedSize(*size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def paintEvent(self, _e):
        t = self.theme
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        hovered, pressed, on = self.underMouse(), self.isDown(), self.isChecked()
        fill, ink = None, t.soft
        if on:
            fill, ink = t.fg, t.bg
        elif pressed:
            fill, ink = t.press, t.fg
        elif hovered:
            fill, ink = t.hover, t.fg
        if self.kind == "close" and hovered:
            fill, ink = t.fg, t.bg
        if fill is not None:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(2, 2, -2, -2), 8, 8)
        if self.kind in self.TEXT_STYLES:
            self._draw_text(p, ink)
        else:
            p.translate((self.width() - 20) / 2, (self.height() - 20) / 2)
            self._draw_glyph(p, ink)

    def _draw_text(self, p: QPainter, ink: QColor):
        f = make_font(UI_FONTS, 10.5, QFont.Weight.Bold if self.kind == "bold" else QFont.Weight.DemiBold)
        f.setItalic(self.kind == "italic")
        f.setStrikeOut(self.kind == "strike")
        if self.kind == "code":
            f = make_font(MONO_FONTS, 9.5, QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(ink)
        p.drawText(QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, self.TEXT_STYLES[self.kind])

    def _draw_glyph(self, p: QPainter, ink: QColor):
        k, P = self.kind, QPointF
        p.setPen(QPen(ink, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        if k == "new":
            p.drawLine(P(10, 4.5), P(10, 15.5))
            p.drawLine(P(4.5, 10), P(15.5, 10))
        elif k == "open":
            p.drawPolygon(QPolygonF([P(3, 6), P(8, 6), P(10, 8), P(17, 8), P(17, 15), P(3, 15)]))
        elif k == "save":
            p.drawRoundedRect(QRectF(4, 4, 12, 12), 2, 2)
            p.drawPolyline(QPolygonF([P(7, 4), P(7, 8), P(13, 8), P(13, 4)]))
            p.drawRect(QRectF(7, 12, 6, 4))
        elif k == "view":
            p.drawRoundedRect(QRectF(3, 4.5, 14, 11), 2.5, 2.5)
            if self.mode == 0:
                p.drawLine(P(6.5, 8.5), P(13.5, 8.5))
                p.drawLine(P(6.5, 11.5), P(11, 11.5))
            elif self.mode == 1:
                p.drawLine(P(10, 4.5), P(10, 15.5))
                p.drawLine(P(5.5, 8.5), P(8, 8.5))
                p.drawLine(P(5.5, 11.5), P(8, 11.5))
                p.setBrush(ink)
                p.drawRect(QRectF(11.8, 7.5, 3.4, 5))
            else:
                p.setBrush(ink)
                p.drawRect(QRectF(6.5, 7.5, 7, 5))
        elif k == "focus":
            p.drawEllipse(P(10, 10), 6.5, 6.5)
            p.setBrush(ink)
            p.drawEllipse(P(10, 10), 1.9, 1.9)
        elif k == "theme":
            p.drawEllipse(P(10, 10), 6.5, 6.5)
            p.setBrush(ink)
            p.drawPie(QRectF(3.5, 3.5, 13, 13), 90 * 16, -180 * 16)
        elif k == "menu":
            for y in (6, 10, 14):
                p.drawLine(P(4, y), P(16, y))
        elif k == "min":
            p.drawLine(P(5, 10), P(15, 10))
        elif k == "max":
            p.drawRoundedRect(QRectF(5, 5, 10, 10), 1.5, 1.5)
        elif k == "restore":
            p.drawRoundedRect(QRectF(4.5, 8, 8, 8), 1.5, 1.5)
            p.drawPolyline(QPolygonF([P(8, 8), P(8, 5), P(15.5, 5), P(15.5, 12.5), P(12.5, 12.5)]))
        elif k == "close":
            p.drawLine(P(5, 5), P(15, 15))
            p.drawLine(P(15, 5), P(5, 15))
        elif k == "up":
            p.drawPolyline(QPolygonF([P(5.5, 12), P(10, 7.5), P(14.5, 12)]))
        elif k == "down":
            p.drawPolyline(QPolygonF([P(5.5, 8), P(10, 12.5), P(14.5, 8)]))


class ThemedDialog(QDialog):
    """Frameless message dialog in the app's own style."""

    def __init__(self, parent, theme: Theme, title: str, text: str, buttons):
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.theme, self.key = theme, "cancel"
        self.setModal(True)
        self.setFixedWidth(440)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 26, 28, 22)
        lay.setSpacing(0)
        head = QLabel(title)
        head.setFont(make_font(DISPLAY_FONTS, 17))
        body = QLabel(text)
        body.setWordWrap(True)
        body.setFont(make_font(UI_FONTS, 10.5))
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch()
        for label, key, primary in buttons:
            b = QPushButton(label)
            b.setObjectName("primary" if primary else "ghost")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setDefault(primary)
            b.clicked.connect(lambda _=False, k=key: self._done(k))
            row.addWidget(b)
        lay.addWidget(head)
        lay.addSpacing(10)
        lay.addWidget(body)
        lay.addSpacing(26)
        lay.addLayout(row)
        self.adjustSize()

    def _done(self, key: str):
        self.key = key
        self.accept()

    def showEvent(self, e):
        super().showEvent(e)
        p = self.parentWidget()
        if p:
            self.move(p.frameGeometry().center() - QPoint(self.width() // 2, self.height() // 2))

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), self.theme.panel)
        p.setPen(self.theme.line)
        p.drawRect(0, 0, self.width() - 1, self.height() - 1)

    def ask(self) -> str:
        self.exec()
        return self.key


# --------------------------------------------------------------------------- #
# Markdown syntax colouring
# --------------------------------------------------------------------------- #
class MdHighlighter(QSyntaxHighlighter):
    RE_FENCE = re.compile(r"^\s*(```|~~~)")
    RE_HEAD = re.compile(r"^(#{1,6})(\s+)(.*)$")
    RE_QUOTE = re.compile(r"^\s*(>\s?)+")
    RE_LIST = re.compile(r"^\s*([-*+]|\d+[.)])\s+(\[[ xX]\]\s+)?")
    RE_HR = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
    RE_BOLD = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
    RE_ITAL_A = re.compile(r"(?<![*\w])\*(?=[^\s*])([^*\n]+?)(?<=[^\s*])\*(?!\*)")
    RE_ITAL_U = re.compile(r"(?<![_\w])_(?=[^\s_])([^_\n]+?)(?<=[^\s_])_(?![_\w])")
    RE_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
    RE_LINK = re.compile(r"!?\[([^\]\n]*)\]\(([^)\n]*)\)")
    RE_URL = re.compile(r"https?://[^\s)>\]]+")
    RE_CODE = re.compile(r"`[^`\n]+`")

    def __init__(self, doc):
        super().__init__(doc)
        self.set_theme(DARK)

    def set_theme(self, t: Theme):
        def fmt(color=None, bold=False, italic=False, strike=False, underline=False, bg=None):
            f = QTextCharFormat()
            if color is not None:
                f.setForeground(color)
            if bg is not None:
                f.setBackground(bg)
            if bold:
                f.setFontWeight(700)
            f.setFontItalic(italic)
            f.setFontStrikeOut(strike)
            f.setFontUnderline(underline)
            return f

        self.f_marker = fmt(t.muted)
        self.f_head = fmt(t.fg, bold=True)
        self.f_bold = fmt(t.fg, bold=True)
        self.f_ital = fmt(t.fg, italic=True)
        self.f_strike = fmt(t.muted, strike=True)
        self.f_link = fmt(t.fg, underline=True)
        self.f_url = fmt(t.muted)
        self.f_quote = fmt(t.soft, italic=True)
        self.f_list = fmt(t.muted, bold=True)
        self.f_code = fmt(t.fg, bg=t.panel2)
        self.f_fence = fmt(t.soft, bg=t.panel)
        self.rehighlight()

    def highlightBlock(self, text: str):
        astral = any(ord(c) > 0xFFFF for c in text)

        def u16(i: int) -> int:  # python index -> UTF-16 index
            return i + sum(1 for c in text[:i] if ord(c) > 0xFFFF) if astral else i

        def put(s: int, e: int, f: QTextCharFormat):
            self.setFormat(u16(s), u16(e) - u16(s), f)

        in_code = self.previousBlockState() == 1
        if self.RE_FENCE.match(text):
            self.setCurrentBlockState(0 if in_code else 1)
            put(0, len(text), self.f_fence)
            return
        if in_code:
            self.setCurrentBlockState(1)
            put(0, len(text), self.f_fence)
            return
        self.setCurrentBlockState(0)

        m = self.RE_HEAD.match(text)
        if m:
            put(m.end(2), len(text), self.f_head)
            put(0, m.end(1), self.f_marker)
            return
        if self.RE_HR.match(text):
            put(0, len(text), self.f_marker)
            return
        m = self.RE_QUOTE.match(text)
        if m:
            put(0, len(text), self.f_quote)
            put(0, m.end(), self.f_marker)
        m = self.RE_LIST.match(text)
        if m:
            put(0, m.end(), self.f_list)

        for m in self.RE_BOLD.finditer(text):
            put(m.start(), m.end(), self.f_bold)
            put(m.start(), m.start() + 2, self.f_marker)
            put(m.end() - 2, m.end(), self.f_marker)
        for rx in (self.RE_ITAL_A, self.RE_ITAL_U):
            for m in rx.finditer(text):
                put(m.start(), m.end(), self.f_ital)
                put(m.start(), m.start() + 1, self.f_marker)
                put(m.end() - 1, m.end(), self.f_marker)
        for m in self.RE_STRIKE.finditer(text):
            put(m.start(), m.end(), self.f_strike)
        for m in self.RE_URL.finditer(text):
            put(m.start(), m.end(), self.f_url)
        for m in self.RE_LINK.finditer(text):
            put(m.start(), m.end(), self.f_url)
            put(m.start(1), m.end(1), self.f_link)
        for m in self.RE_CODE.finditer(text):
            put(m.start(), m.end(), self.f_code)


# --------------------------------------------------------------------------- #
# Editor
# --------------------------------------------------------------------------- #
LIST_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])(\s+)(\[[ xX]\]\s+)?")
QUOTE_RE = re.compile(r"^(\s*>\s?)+")
PARA = "\u2029"


class MdEdit(QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self.theme = DARK
        self.focus_mode = False
        self.font_pt = 13.5
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.setCursorWidth(2)
        self.setPlaceholderText("Start writing\u2026")
        self.highlighter = MdHighlighter(self.document())
        self.cursorPositionChanged.connect(self._on_cursor)
        self.textChanged.connect(self.update_extras)
        self.set_font_pt(self.font_pt)

    # ---- appearance ----
    def set_font_pt(self, pt: float):
        self.font_pt = pt
        f = make_font(MONO_FONTS, pt)
        self.setFont(f)
        self.setTabStopDistance(4 * QFontMetricsF(f).horizontalAdvance(" "))
        self._relayout()

    def apply_theme(self, t: Theme):
        self.theme = t
        pal = self.palette()
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
            pal.setColor(group, QPalette.ColorRole.Base, t.bg)
            pal.setColor(group, QPalette.ColorRole.Text, t.fg)
            pal.setColor(group, QPalette.ColorRole.Highlight, t.fg)
            pal.setColor(group, QPalette.ColorRole.HighlightedText, t.bg)
            pal.setColor(group, QPalette.ColorRole.PlaceholderText, t.muted)
        self.setPalette(pal)
        self.highlighter.set_theme(t)
        self.update_extras()

    def _relayout(self):
        col = QFontMetricsF(self.font()).horizontalAdvance("0") * 78
        side = max(28, int((self.width() - col) / 2))
        self.setViewportMargins(side, 40, side, 40)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._relayout()

    # ---- focus mode and typewriter scrolling ----
    def set_focus_mode(self, on: bool):
        self.focus_mode = on
        self.setCenterOnScroll(on)
        self.update_extras()
        if on:
            QTimer.singleShot(0, self._center_cursor)

    def _on_cursor(self):
        self.update_extras()
        if self.focus_mode:
            QTimer.singleShot(0, self._center_cursor)

    def _center_cursor(self):
        r = self.cursorRect()
        sb = self.verticalScrollBar()
        sb.setValue(sb.value() + r.center().y() - self.viewport().height() // 2)

    def update_extras(self):
        sels = []
        if self.focus_mode:
            doc = self.document()
            blk = self.textCursor().block()
            fmt = QTextCharFormat()
            fmt.setForeground(self.theme.dim)
            end_doc = max(0, doc.characterCount() - 1)
            start = blk.position()
            after = min(end_doc, blk.position() + blk.length())
            if start > 0:
                s = QTextEdit.ExtraSelection()
                c = QTextCursor(doc)
                c.setPosition(0)
                c.setPosition(start, QTextCursor.MoveMode.KeepAnchor)
                s.cursor, s.format = c, fmt
                sels.append(s)
            if after < end_doc:
                s = QTextEdit.ExtraSelection()
                c = QTextCursor(doc)
                c.setPosition(after)
                c.setPosition(end_doc, QTextCursor.MoveMode.KeepAnchor)
                s.cursor, s.format = c, fmt
                sels.append(s)
        self.setExtraSelections(sels)

    # ---- input ----
    def wheelEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            step = 1 if e.angleDelta().y() > 0 else -1
            win = self.window()
            if hasattr(win, "zoom"):
                win.zoom(step)
            e.accept()
            return
        super().wheelEvent(e)

    def keyPressEvent(self, e):
        key, mods = e.key(), e.modifiers()
        plain = not (mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.AltModifier))
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and plain and self._smart_enter():
            return
        if key == Qt.Key.Key_Tab and plain and not self.textCursor().hasSelection():
            self.insertPlainText("    ")
            return
        super().keyPressEvent(e)

    def _smart_enter(self) -> bool:
        c = self.textCursor()
        if c.hasSelection():
            return False
        line, col = c.block().text(), c.positionInBlock()
        if col != len(line):
            return False
        m = LIST_RE.match(line)
        if m:
            if not line[m.end():].strip():
                c.select(QTextCursor.SelectionType.LineUnderCursor)
                c.removeSelectedText()
                self.setTextCursor(c)
                return True
            marker = m.group(2)
            if marker[:-1].isdigit():
                marker = f"{int(marker[:-1]) + 1}{marker[-1]}"
            task = "[ ] " if m.group(4) else ""
            c.insertText("\n" + m.group(1) + marker + m.group(3) + task)
            self.setTextCursor(c)
            self.ensureCursorVisible()
            return True
        q = QUOTE_RE.match(line)
        if q:
            if not line[q.end():].strip():
                c.select(QTextCursor.SelectionType.LineUnderCursor)
                c.removeSelectedText()
            else:
                c.insertText("\n" + q.group(0))
            self.setTextCursor(c)
            self.ensureCursorVisible()
            return True
        return False

    # ---- formatting commands ----
    def wrap(self, left: str, right: str | None = None):
        right = left if right is None else right
        c = self.textCursor()
        c.beginEditBlock()
        if c.hasSelection():
            s, e = c.selectionStart(), c.selectionEnd()
            text = self.toPlainText()
            if text[max(0, s - len(left)):s] == left and text[e:e + len(right)] == right:
                c.setPosition(e)
                c.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, len(right))
                c.removeSelectedText()
                c.setPosition(s)
                c.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor, len(left))
                c.removeSelectedText()
                c.setPosition(s - len(left))
                c.setPosition(e - len(left), QTextCursor.MoveMode.KeepAnchor)
            else:
                sel = c.selectedText()
                c.insertText(left + sel + right)
                c.setPosition(s + len(left))
                c.setPosition(s + len(left) + len(sel), QTextCursor.MoveMode.KeepAnchor)
        else:
            c.insertText(left + right)
            c.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.MoveAnchor, len(right))
        c.endEditBlock()
        self.setTextCursor(c)
        self.setFocus()

    def toggle_prefix(self, prefix: str):
        c = self.textCursor()
        doc = self.document()
        blk = doc.findBlock(c.selectionStart())
        last = doc.findBlock(c.selectionEnd()).blockNumber()
        blocks = []
        while blk.isValid() and blk.blockNumber() <= last:
            blocks.append(blk)
            blk = blk.next()
        remove = all(b.text().startswith(prefix) for b in blocks)
        c.beginEditBlock()
        for b in blocks:
            cur = QTextCursor(b)
            if remove:
                cur.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, len(prefix))
                cur.removeSelectedText()
            else:
                cur.insertText(prefix)
        c.endEditBlock()
        self.setFocus()

    def cycle_heading(self):
        c = self.textCursor()
        blk = c.block()
        m = re.match(r"^(#{1,6})\s+", blk.text())
        cur = QTextCursor(blk)
        c.beginEditBlock()
        if m:
            n = len(m.group(1))
            cur.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, m.end())
            cur.insertText("" if n >= 3 else "#" * (n + 1) + " ")
        else:
            cur.insertText("# ")
        c.endEditBlock()
        self.setFocus()

    def insert_code(self):
        sel = self.textCursor().selectedText()
        if PARA in sel:
            self.textCursor().insertText("```\n" + sel.replace(PARA, "\n") + "\n```")
        else:
            self.wrap("`")

    def insert_link(self):
        c = self.textCursor()
        sel = c.selectedText()
        c.insertText(f"[{sel}](url)")
        end = c.position()
        c.setPosition(end - 4)
        c.setPosition(end - 1, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(c)
        self.setFocus()


# --------------------------------------------------------------------------- #
# Preview
# --------------------------------------------------------------------------- #
def md_to_html(text: str) -> str:
    out = mdlib.markdown(text, extensions=["fenced_code", "tables", "sane_lists", "footnotes"], output_format="html")
    out = re.sub(r"(?<!~)~~(?=\S)(.+?)(?<=\S)~~(?!~)", r"<s>\1</s>", out)
    out = out.replace("<li>[ ] ", "<li>\u2610 ").replace("<li>[x] ", "<li>\u2611 ").replace("<li>[X] ", "<li>\u2611 ")
    out = out.replace("<table>", '<table border="1" cellspacing="0" cellpadding="7" width="100%">')
    return out


class Preview(QTextBrowser):
    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setOpenExternalLinks(True)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        side = max(28, (self.width() - 720) // 2)
        self.setViewportMargins(side, 40, side, 40)

    def show_markdown(self, text: str, t: Theme, base_pt: float):
        tokens = theme_tokens(t)
        tokens.update(
            ui=css_families(UI_FONTS), display=css_families(DISPLAY_FONTS), mono=css_families(MONO_FONTS),
            body=f"{base_pt:.1f}", h1=f"{base_pt * 2.5:.1f}", h2=f"{base_pt * 1.75:.1f}", h3=f"{base_pt * 1.3:.1f}",
        )
        css = PREVIEW_CSS.substitute(tokens)
        self.setHtml(f"<html><head><style>{css}</style></head><body>{md_to_html(text)}</body></html>")


# --------------------------------------------------------------------------- #
# Find bar
# --------------------------------------------------------------------------- #
class FindBar(Bar):
    def __init__(self, editor: MdEdit):
        super().__init__("top")
        self.editor = editor
        self.setFixedHeight(50)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 12, 0)
        lay.setSpacing(6)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Find in document")
        self.edit.setMaximumWidth(360)
        self.info = QLabel("")
        self.info.setObjectName("stat")
        self.b_prev = IconButton("up", "Previous match", (30, 30))
        self.b_next = IconButton("down", "Next match (Enter)", (30, 30))
        self.b_close = IconButton("close", "Close (Esc)", (30, 30))
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.b_prev)
        lay.addWidget(self.b_next)
        lay.addSpacing(8)
        lay.addWidget(self.info)
        lay.addStretch(2)
        lay.addWidget(self.b_close)
        self.edit.returnPressed.connect(lambda: self._go(False))
        self.edit.textChanged.connect(self._changed)
        self.b_next.clicked.connect(lambda _=False: self._go(False))
        self.b_prev.clicked.connect(lambda _=False: self._go(True))
        self.b_close.clicked.connect(lambda _=False: self.close_bar())

    def open_bar(self):
        sel = self.editor.textCursor().selectedText()
        if sel and PARA not in sel:
            self.edit.setText(sel)
        self.show()
        self.edit.setFocus()
        self.edit.selectAll()

    def close_bar(self):
        self.hide()
        self.editor.setFocus()

    def _changed(self, text: str):
        if not text:
            self.info.setText("")
            return
        n = self.editor.toPlainText().lower().count(text.lower())
        self.info.setText(f"{n} found" if n else "No results")
        c = self.editor.textCursor()
        c.setPosition(c.selectionStart())
        self.editor.setTextCursor(c)
        self._go(False)

    def _go(self, backward: bool):
        text = self.edit.text()
        if not text:
            return
        back = QTextDocument.FindFlag.FindBackward

        def attempt() -> bool:
            return self.editor.find(text, back) if backward else self.editor.find(text)

        if not attempt():
            c = self.editor.textCursor()
            c.movePosition(QTextCursor.MoveOperation.End if backward else QTextCursor.MoveOperation.Start)
            self.editor.setTextCursor(c)
            attempt()


# --------------------------------------------------------------------------- #
# Title bar (the window chrome, in the same style as everything else)
# --------------------------------------------------------------------------- #
class TitleBar(Bar):
    def __init__(self, win: "MainWindow"):
        super().__init__("bottom", win)
        self.win = win
        self.setFixedHeight(52)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 8, 0)
        lay.setSpacing(0)

        left = QWidget()
        ll = QHBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(2)
        self.logo = QLabel()
        pm = QPixmap(str(resource("logo.png")))
        if not pm.isNull():
            pm = pm.scaledToHeight(56, Qt.TransformationMode.SmoothTransformation)
            pm.setDevicePixelRatio(2)
            self.logo.setPixmap(pm)
        self.logo.setFixedSize(30, 30)
        self.logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.b_new = IconButton("new", "New  (Ctrl+N)")
        self.b_open = IconButton("open", "Open  (Ctrl+O)")
        self.b_save = IconButton("save", "Save  (Ctrl+S)")
        ll.addWidget(self.logo)
        ll.addSpacing(12)
        for b in (self.b_new, self.b_open, self.b_save):
            ll.addWidget(b)
        ll.addStretch()

        self.title = QLabel("Untitled")
        self.title.setFont(make_font(DISPLAY_FONTS, 12.5))
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        right = QWidget()
        rl = QHBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(2)
        rl.addStretch()
        self.b_view = IconButton("view", "Preview: editor only  (Ctrl+Shift+P)")
        self.b_focus = IconButton("focus", "Focus mode  (Ctrl+Shift+F)", checkable=True)
        self.b_theme = IconButton("theme", "Switch light / dark  (Ctrl+Shift+T)")
        self.b_menu = IconButton("menu", "Menu")
        for b in (self.b_view, self.b_focus, self.b_theme, self.b_menu):
            rl.addWidget(b)
        rl.addSpacing(10)
        wsize = (42, 34)
        self.b_min = IconButton("min", "Minimise", wsize)
        self.b_max = IconButton("max", "Maximise", wsize)
        self.b_close = IconButton("close", "Close", wsize)
        for b in (self.b_min, self.b_max, self.b_close):
            rl.addWidget(b)

        lay.addWidget(left, 1)
        lay.addWidget(self.title, 0)
        lay.addWidget(right, 1)

        self.b_min.clicked.connect(lambda _=False: win.showMinimized())
        self.b_max.clicked.connect(lambda _=False: win.toggle_max())
        self.b_close.clicked.connect(lambda _=False: win.close())

    def set_title(self, name: str, dirty: bool):
        self.title.setText(name + ("  \u25cf" if dirty else ""))

    # Non-Windows fallback; on Windows the native caption hit-test handles this.
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.win.windowHandle():
            self.win.windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.win.toggle_max()


# --------------------------------------------------------------------------- #
# Main window
# --------------------------------------------------------------------------- #
VIEW_TIPS = ["Preview: editor only", "Preview: split view", "Preview: full page"]
MD_FILTER = "Markdown (*.md *.markdown *.mdown);;Text (*.txt);;All files (*)"


class MainWindow(QWidget):
    def __init__(self, path: str | None = None):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(str(resource("icon.png"))))
        self.setMinimumSize(560, 420)
        self.resize(1120, 780)
        self.setAcceptDrops(True)

        self.settings = QSettings(ORG_NAME, APP_NAME)
        self.path: Path | None = None
        self.view_mode = 0
        self._was_max = False
        self.theme = LIGHT if self.settings.value("theme", "dark") == "light" else DARK
        try:
            pt = float(self.settings.value("font_pt", 13.5))
        except (TypeError, ValueError):
            pt = 13.5

        self.titlebar = TitleBar(self)
        self.editor = MdEdit()
        self.preview = Preview()
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(1)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.editor)
        self.splitter.addWidget(self.preview)
        self.findbar = FindBar(self.editor)
        self.findbar.hide()
        self.footer = self._build_footer()

        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)
        root.addWidget(self.titlebar)
        root.addWidget(self.splitter, 1)
        root.addWidget(self.findbar)
        root.addWidget(self.footer)

        self._build_actions()
        self.pv_timer = QTimer(self, singleShot=True, interval=160)
        self.pv_timer.timeout.connect(self.refresh_preview)
        self.st_timer = QTimer(self, singleShot=True, interval=90)
        self.st_timer.timeout.connect(self.update_stats)

        self.editor.textChanged.connect(self.pv_timer.start)
        self.editor.textChanged.connect(self.st_timer.start)
        self.editor.cursorPositionChanged.connect(self.st_timer.start)
        self.editor.selectionChanged.connect(self.st_timer.start)
        self.editor.verticalScrollBar().valueChanged.connect(self._sync_scroll)
        self.editor.document().modificationChanged.connect(self._update_title)

        tb = self.titlebar
        tb.b_new.clicked.connect(lambda _=False: self.new_file())
        tb.b_open.clicked.connect(lambda _=False: self.open_dialog())
        tb.b_save.clicked.connect(lambda _=False: self.save())
        tb.b_view.clicked.connect(lambda _=False: self.cycle_view())
        tb.b_focus.clicked.connect(lambda checked=False: self.set_focus_mode(checked))
        tb.b_theme.clicked.connect(lambda _=False: self.toggle_theme())
        tb.b_menu.clicked.connect(lambda _=False: self.show_menu())

        QShortcut(QKeySequence("Escape"), self, activated=self._escape)

        self.editor.set_font_pt(pt)
        self.apply_theme(self.theme)
        self.set_view(0)

        geo = self.settings.value("geometry")
        if geo is not None:
            try:
                self.restoreGeometry(geo)
            except TypeError:
                pass

        if path and Path(path).is_file():
            self.open_path(Path(path))
        else:
            self.editor.setPlainText(WELCOME)
            self.editor.document().setModified(False)
            self.editor.document().clearUndoRedoStacks()
        self._update_title()
        self.update_stats()

    # ---- construction helpers ----
    def _build_footer(self) -> Bar:
        bar = Bar("top")
        bar.setFixedHeight(40)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 0, 8, 0)
        lay.setSpacing(0)
        self.fmt_buttons = []
        spec = [
            ("bold", "Bold  (Ctrl+B)", lambda: self.editor.wrap("**")),
            ("italic", "Italic  (Ctrl+I)", lambda: self.editor.wrap("*")),
            ("strike", "Strikethrough  (Ctrl+Shift+X)", lambda: self.editor.wrap("~~")),
            ("heading", "Heading, cycles H1 to H3  (Ctrl+H)", self.editor.cycle_heading),
            ("quote", "Quote  (Ctrl+Shift+Q)", lambda: self.editor.toggle_prefix("> ")),
            ("list", "List  (Ctrl+Shift+L)", lambda: self.editor.toggle_prefix("- ")),
            ("code", "Code  (Ctrl+Shift+C)", self.editor.insert_code),
            ("link", "Link  (Ctrl+K)", self.editor.insert_link),
        ]
        for kind, tip, fn in spec:
            b = IconButton(kind, tip, (32, 30))
            b.clicked.connect(lambda _=False, f=fn: f())
            lay.addWidget(b)
        lay.addStretch()
        self.lbl_words = QLabel("")
        self.lbl_words.setObjectName("stat")
        self.lbl_pos = QLabel("")
        self.lbl_pos.setObjectName("stat")
        for l in (self.lbl_words, self.lbl_pos):
            l.setFont(make_font(UI_FONTS, 9.5))
        lay.addWidget(self.lbl_words)
        lay.addSpacing(22)
        lay.addWidget(self.lbl_pos)
        lay.addSpacing(8)
        if sys.platform != "win32":
            lay.addWidget(QSizeGrip(bar))
        return bar

    def _act(self, text, fn, key=None) -> QAction:
        a = QAction(text, self)
        if key:
            a.setShortcut(QKeySequence(key))
        a.triggered.connect(lambda _=False, f=fn: f())
        self.addAction(a)
        return a

    def _build_actions(self):
        e = self.editor
        self.a_new = self._act("New", self.new_file, "Ctrl+N")
        self.a_open = self._act("Open\u2026", self.open_dialog, "Ctrl+O")
        self.a_save = self._act("Save", self.save, "Ctrl+S")
        self.a_saveas = self._act("Save as\u2026", self.save_as, "Ctrl+Shift+S")
        self.a_export = self._act("Export as HTML\u2026", self.export_html, "Ctrl+Shift+E")
        self.a_find = self._act("Find\u2026", self.findbar.open_bar, "Ctrl+F")
        self.a_zin = self._act("Larger text", lambda: self.zoom(1), "Ctrl+=")
        self.a_zout = self._act("Smaller text", lambda: self.zoom(-1), "Ctrl+-")
        self.a_zreset = self._act("Reset text size", lambda: self.zoom(0), "Ctrl+0")
        self.a_focus = self._act("Focus mode", lambda: self.set_focus_mode(not e.focus_mode), "Ctrl+Shift+F")
        self.a_view = self._act("Cycle preview", self.cycle_view, "Ctrl+Shift+P")
        self.a_theme = self._act("Switch light / dark", self.toggle_theme, "Ctrl+Shift+T")
        self.a_zen = self._act("Distraction-free window", self.toggle_zen, "F11")
        self.a_about = self._act("About Raining Md", self.about)
        self.a_quit = self._act("Quit", self.close, "Ctrl+Q")
        # Formatting shortcuts (buttons live in the footer)
        self._act("Bold", lambda: e.wrap("**"), "Ctrl+B")
        self._act("Italic", lambda: e.wrap("*"), "Ctrl+I")
        self._act("Strikethrough", lambda: e.wrap("~~"), "Ctrl+Shift+X")
        self._act("Heading", e.cycle_heading, "Ctrl+H")
        self._act("Quote", lambda: e.toggle_prefix("> "), "Ctrl+Shift+Q")
        self._act("List", lambda: e.toggle_prefix("- "), "Ctrl+Shift+L")
        self._act("Code", e.insert_code, "Ctrl+Shift+C")
        self._act("Link", e.insert_link, "Ctrl+K")

    def show_menu(self):
        m = QMenu(self)
        for a in (self.a_new, self.a_open, self.a_save, self.a_saveas, self.a_export):
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.a_find)
        m.addSeparator()
        for a in (self.a_zin, self.a_zout, self.a_zreset):
            m.addAction(a)
        m.addSeparator()
        for a in (self.a_focus, self.a_view, self.a_theme, self.a_zen):
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.a_about)
        m.addAction(self.a_quit)
        btn = self.titlebar.b_menu
        pos = btn.mapToGlobal(QPoint(btn.width() - m.sizeHint().width(), btn.height() + 4))
        m.exec(pos)

    # ---- theme and view ----
    def apply_theme(self, t: Theme):
        self.theme = t
        QApplication.instance().setStyleSheet(QSS.substitute(theme_tokens(t)))
        for w in self.findChildren(Bar):
            w.theme = t
            w.update()
        for b in self.findChildren(IconButton):
            b.theme = t
            b.update()
        self.editor.apply_theme(t)
        self.refresh_preview()
        self.update()
        self.settings.setValue("theme", t.name)

    def toggle_theme(self):
        self.apply_theme(LIGHT if self.theme is DARK else DARK)

    def set_view(self, mode: int):
        self.view_mode = mode
        self.editor.setVisible(mode != 2)
        self.preview.setVisible(mode != 0)
        if mode == 1:
            self.splitter.setSizes([1, 1])
        b = self.titlebar.b_view
        b.mode = mode
        b.setToolTip(VIEW_TIPS[mode] + "  (Ctrl+Shift+P)")
        b.setChecked(False)
        b.update()
        self.refresh_preview()
        QTimer.singleShot(0, self._sync_scroll)
        if mode != 2:
            self.editor.setFocus()

    def cycle_view(self):
        self.set_view((self.view_mode + 1) % 3)

    def set_focus_mode(self, on: bool):
        self.editor.set_focus_mode(on)
        self.titlebar.b_focus.setChecked(on)
        self.editor.setFocus()

    def refresh_preview(self):
        if self.view_mode == 0:
            return
        self.preview.show_markdown(self.editor.toPlainText(), self.theme, max(9.0, self.editor.font_pt - 1.5))
        QTimer.singleShot(0, self._sync_scroll)

    def _sync_scroll(self, *_):
        if self.view_mode != 1:
            return
        es, ps = self.editor.verticalScrollBar(), self.preview.verticalScrollBar()
        ps.setValue(0 if es.maximum() <= 0 else round(ps.maximum() * es.value() / es.maximum()))

    def zoom(self, step: int):
        pt = 13.5 if step == 0 else min(28.0, max(9.0, self.editor.font_pt + step))
        self.editor.set_font_pt(pt)
        self.settings.setValue("font_pt", pt)
        self.refresh_preview()

    def toggle_zen(self):
        if self.isFullScreen():
            self.titlebar.show()
            self.footer.show()
            self.showMaximized() if self._was_max else self.showNormal()
        else:
            self._was_max = self.isMaximized()
            self.titlebar.hide()
            self.footer.hide()
            self.showFullScreen()
        self.editor.setFocus()

    def toggle_max(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def _escape(self):
        if self.findbar.isVisible():
            self.findbar.close_bar()
        elif self.isFullScreen():
            self.toggle_zen()

    # ---- statistics and title ----
    def update_stats(self):
        c = self.editor.textCursor()
        sel = c.selectedText()
        text = sel if sel else self.editor.toPlainText()
        words = len(re.findall(r"[\w'\u2019-]+", text))
        chars = len(text)
        mins = 0 if words == 0 else max(1, round(words / 230))
        label = f"{words:,} words" + (" selected" if sel else "")
        label += f"     {chars:,} characters"
        if mins and not sel:
            label += f"     {mins} min read"
        self.lbl_words.setText(label)
        self.lbl_pos.setText(f"Line {c.blockNumber() + 1}, column {c.positionInBlock() + 1}")

    def _update_title(self, *_):
        name = self.path.name if self.path else "Untitled"
        dirty = self.editor.document().isModified()
        self.titlebar.set_title(name, dirty)
        self.setWindowTitle(f"{name}{'*' if dirty else ''} \u2013 {APP_NAME}")

    # ---- files ----
    def _confirm(self, title, text, buttons) -> str:
        return ThemedDialog(self, self.theme, title, text, buttons).ask()

    def maybe_save(self) -> bool:
        if not self.editor.document().isModified():
            return True
        name = self.path.name if self.path else "Untitled"
        r = self._confirm(
            "Save changes?",
            f"\u201c{name}\u201d has changes that haven\u2019t been saved.",
            [("Cancel", "cancel", False), ("Discard", "discard", False), ("Save", "save", True)],
        )
        if r == "save":
            return self.save()
        return r == "discard"

    def new_file(self):
        if not self.maybe_save():
            return
        self.path = None
        self.editor.clear()
        self.editor.document().setModified(False)
        self.editor.document().clearUndoRedoStacks()
        self._update_title()

    def open_dialog(self):
        if not self.maybe_save():
            return
        start = str(self.path.parent) if self.path else str(Path.home())
        name, _ = QFileDialog.getOpenFileName(self, "Open Markdown file", start, MD_FILTER)
        if name:
            self.open_path(Path(name))

    def open_path(self, p: Path):
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as err:
            self._confirm("Couldn\u2019t open the file", f"{p.name}: {err.strerror or err}", [("Close", "cancel", True)])
            return
        self.path = p
        self.editor.setPlainText(text)
        self.editor.document().setModified(False)
        self.editor.document().clearUndoRedoStacks()
        c = self.editor.textCursor()
        c.movePosition(QTextCursor.MoveOperation.Start)
        self.editor.setTextCursor(c)
        self._update_title()

    def save(self) -> bool:
        if self.path is None:
            return self.save_as()
        return self._write(self.path)

    def save_as(self) -> bool:
        start = str(self.path) if self.path else str(Path.home() / "Untitled.md")
        name, _ = QFileDialog.getSaveFileName(self, "Save Markdown file", start, MD_FILTER)
        if not name:
            return False
        p = Path(name)
        if not p.suffix:
            p = p.with_suffix(".md")
        return self._write(p)

    def _write(self, p: Path) -> bool:
        try:
            p.write_text(self.editor.toPlainText(), encoding="utf-8", newline="\n")
        except OSError as err:
            self._confirm("Couldn\u2019t save the file", f"{p.name}: {err.strerror or err}", [("Close", "cancel", True)])
            return False
        self.path = p
        self.editor.document().setModified(False)
        self._update_title()
        return True

    def export_html(self):
        stem = self.path.stem if self.path else "Untitled"
        start = str((self.path.parent if self.path else Path.home()) / f"{stem}.html")
        name, _ = QFileDialog.getSaveFileName(self, "Export as HTML", start, "HTML (*.html)")
        if not name:
            return
        css = EXPORT_CSS.substitute(theme_tokens(self.theme))
        page = (
            f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{htmllib.escape(stem)}</title><style>{css}</style></head>"
            f"<body><main>{md_to_html(self.editor.toPlainText())}</main></body></html>"
        )
        try:
            Path(name).write_text(page, encoding="utf-8")
        except OSError as err:
            self._confirm("Couldn\u2019t export", str(err.strerror or err), [("Close", "cancel", True)])

    def about(self):
        self._confirm(
            f"{APP_NAME} {APP_VERSION}",
            "A calm place to write Markdown.\n\nBuilt with PySide6 for the Raining Company. "
            "The interface follows the design of GNOME Apostrophe.",
            [("Close", "cancel", True)],
        )

    # ---- drag and drop ----
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            if url.isLocalFile() and Path(url.toLocalFile()).is_file():
                if self.maybe_save():
                    self.open_path(Path(url.toLocalFile()))
                break

    # ---- window plumbing ----
    def closeEvent(self, e):
        if not self.maybe_save():
            e.ignore()
            return
        self.settings.setValue("geometry", self.saveGeometry())
        e.accept()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), self.theme.bg)
        if not (self.isMaximized() or self.isFullScreen()):
            p.setPen(self.theme.line)
            p.drawRect(0, 0, self.width() - 1, self.height() - 1)

    def changeEvent(self, e):
        if e.type() == QEvent.Type.WindowStateChange:
            flat = self.isMaximized() or self.isFullScreen()
            m = 0 if flat else 1
            self.layout().setContentsMargins(m, m, m, m)
            self.titlebar.b_max.kind = "restore" if self.isMaximized() else "max"
            self.titlebar.b_max.setToolTip("Restore" if self.isMaximized() else "Maximise")
            self.titlebar.b_max.update()
        super().changeEvent(e)

    def showEvent(self, e):
        super().showEvent(e)
        if sys.platform == "win32":
            try:  # Windows 11: round the corners of the frameless window
                import ctypes
                pref = ctypes.c_int(2)  # DWMWCP_ROUND
                ctypes.windll.dwmapi.DwmSetWindowAttribute(int(self.winId()), 33, ctypes.byref(pref), ctypes.sizeof(pref))
            except Exception:
                pass
        self.editor.setFocus()

    def nativeEvent(self, event_type, message):
        """Windows: native resize edges and a real caption area (Aero Snap, shake, drag-to-maximise)."""
        if sys.platform == "win32" and bytes(event_type) == b"windows_generic_MSG":
            import ctypes
            import ctypes.wintypes as wt

            msg = wt.MSG.from_address(int(message))
            if msg.message == 0x0084:  # WM_NCHITTEST
                x = ctypes.c_short(msg.lParam & 0xFFFF).value
                y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                dpr = self.devicePixelRatioF()
                pt = self.mapFromGlobal(QPoint(round(x / dpr), round(y / dpr)))
                w, h, b = self.width(), self.height(), 7
                if not (self.isMaximized() or self.isFullScreen()):
                    left, right, top, bottom = pt.x() < b, pt.x() >= w - b, pt.y() < b, pt.y() >= h - b
                    if top and left:
                        return True, 13
                    if top and right:
                        return True, 14
                    if bottom and left:
                        return True, 16
                    if bottom and right:
                        return True, 17
                    if left:
                        return True, 10
                    if right:
                        return True, 11
                    if top:
                        return True, 12
                    if bottom:
                        return True, 15
                if self.titlebar.isVisible() and 0 <= pt.y() < self.titlebar.height() + 1:
                    child = self.childAt(pt)
                    if not isinstance(child, QAbstractButton):
                        return True, 2  # HTCAPTION
        return super().nativeEvent(event_type, message)


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("RainingCompany.RainingMd")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setStyle("Fusion")
    app.setFont(make_font(UI_FONTS, 10))
    if "--uninstall" in sys.argv:  # registered in Windows Apps & features
        import installer

        sys.exit(installer.run(uninstall=True))
    path = next((a for a in sys.argv[1:] if Path(a).is_file()), None)
    win = MainWindow(path)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
