#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Raining Md Setup: installer and uninstaller in the same style as the editor.

Installer   : rainingmd-installer.exe (this file, frozen, with assets/payload.zip inside)
Uninstaller : "RainingMd.exe --uninstall" (registered in Windows' Apps & features)

Per-user install (no administrator rights needed unless the chosen folder requires them).
"""
from __future__ import annotations

import random
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, QThread, Signal
from PySide6.QtGui import QFontMetrics, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

# Reuse the editor's look (palette, buttons, dialogs) instead of copying it.
_m = sys.modules.get("__main__")
if _m is not None and hasattr(_m, "MdEdit"):
    ui = _m
else:
    import main as ui  # static import so PyInstaller bundles it into the frozen installer

APP = ui.APP_NAME
EXE_NAME = "RainingMd.exe"
PROG_ID = "RainingMd.md"
REG_UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\RainingMd"
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008

THEME = ui.DARK

EXTRA_QSS = """
QLabel#soft { color:$soft; }
QLabel#hint { color:$muted; }
QLabel#warn { color:$fg; }
"""


# --------------------------------------------------------------------------- #
# System work (registry, shortcuts, files)
# --------------------------------------------------------------------------- #
def _q(text) -> str:
    return str(text).replace("'", "''")


def _powershell(command: str, wait: bool = True):
    args = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command]
    if wait:
        subprocess.run(args, creationflags=CREATE_NO_WINDOW, capture_output=True, timeout=90)
    else:
        subprocess.Popen(args, creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW, close_fds=True)


def make_shortcut(folder: str, target: Path):
    """folder: 'Desktop' or 'Programs' (the current user's Start menu)."""
    _powershell(
        f"$d=[Environment]::GetFolderPath('{folder}'); "
        f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d '{APP}.lnk')); "
        f"$s.TargetPath='{_q(target)}'; $s.WorkingDirectory='{_q(target.parent)}'; "
        f"$s.IconLocation='{_q(target)},0'; $s.Description='{APP}'; $s.Save()"
    )


def remove_shortcuts():
    _powershell(
        "foreach($f in 'Desktop','Programs'){ "
        f"Remove-Item -LiteralPath (Join-Path ([Environment]::GetFolderPath($f)) '{APP}.lnk') -Force -ErrorAction SilentlyContinue }}"
    )


def write_registry(dest: Path, size_kb: int, assoc: bool):
    import winreg

    exe = dest / EXE_NAME
    hkcu = winreg.HKEY_CURRENT_USER
    with winreg.CreateKey(hkcu, REG_UNINSTALL) as k:
        values = {
            "DisplayName": APP,
            "DisplayVersion": ui.APP_VERSION,
            "Publisher": ui.ORG_NAME,
            "InstallLocation": str(dest),
            "DisplayIcon": f"{exe},0",
            "UninstallString": f'"{exe}" --uninstall',
        }
        for name, val in values.items():
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
        for name, val in {"NoModify": 1, "NoRepair": 1, "EstimatedSize": size_kb}.items():
            winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, val)
    if assoc:
        for ext in (".md", ".markdown"):
            with winreg.CreateKey(hkcu, rf"Software\Classes\{ext}\OpenWithProgids") as k:
                winreg.SetValueEx(k, PROG_ID, 0, winreg.REG_NONE, b"")
        with winreg.CreateKey(hkcu, rf"Software\Classes\{PROG_ID}") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "Markdown document")
        with winreg.CreateKey(hkcu, rf"Software\Classes\{PROG_ID}\DefaultIcon") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f"{exe},0")
        with winreg.CreateKey(hkcu, rf"Software\Classes\{PROG_ID}\shell\open\command") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f'"{exe}" "%1"')
    try:
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
    except Exception:
        pass


def _delete_tree(root, path: str):
    import winreg

    try:
        key = winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS)
    except OSError:
        return
    with key:
        while True:
            try:
                sub = winreg.EnumKey(key, 0)
            except OSError:
                break
            _delete_tree(root, path + "\\" + sub)
    try:
        winreg.DeleteKey(root, path)
    except OSError:
        pass


def remove_registry():
    import winreg

    hkcu = winreg.HKEY_CURRENT_USER
    _delete_tree(hkcu, REG_UNINSTALL)
    _delete_tree(hkcu, rf"Software\Classes\{PROG_ID}")
    for ext in (".md", ".markdown"):
        try:
            with winreg.OpenKey(hkcu, rf"Software\Classes\{ext}\OpenWithProgids", 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, PROG_ID)
        except OSError:
            pass


def installed_dir() -> Path | None:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_UNINSTALL) as k:
            return Path(winreg.QueryValueEx(k, "InstallLocation")[0])
    except Exception:
        return None


def default_dir() -> Path:
    prev = installed_dir()
    if prev:
        return prev
    import os

    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "Programs" / APP


def payload_size() -> int:
    try:
        with zipfile.ZipFile(ui.resource("payload.zip")) as z:
            return sum(i.file_size for i in z.infolist())
    except Exception:
        return 150 * 1024 * 1024


def fmt_size(n: float) -> str:
    return f"{n / 1024 ** 3:.1f} GB" if n >= 1024 ** 3 else f"{n / 1024 ** 2:.0f} MB"


class InstallWorker(QThread):
    progress = Signal(int, str)
    succeeded = Signal()
    failed = Signal(str)

    def __init__(self, dest: Path, desktop: bool, assoc: bool):
        super().__init__()
        self.dest, self.desktop, self.assoc = dest, desktop, assoc

    def run(self):
        try:
            self.dest.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(ui.resource("payload.zip")) as z:
                infos = z.infolist()
                total = sum(i.file_size for i in infos) or 1
                done = 0
                for info in infos:
                    z.extract(info, self.dest)
                    done += info.file_size
                    self.progress.emit(int(done * 90 / total), info.filename)
            exe = self.dest / EXE_NAME
            self.progress.emit(93, "Creating shortcuts")
            make_shortcut("Programs", exe)
            if self.desktop:
                make_shortcut("Desktop", exe)
            self.progress.emit(97, "Registering with Windows")
            write_registry(self.dest, int(sum(i.file_size for i in infos) / 1024), self.assoc)
            self.progress.emit(100, "Finished")
            self.succeeded.emit()
        except PermissionError as err:
            self.failed.emit(
                f"Windows wouldn\u2019t let Setup write to that folder ({err.filename or self.dest}). "
                f"If {APP} is open, close it and try again, or choose a folder in your user profile."
            )
        except Exception as err:  # noqa: BLE001
            self.failed.emit(str(err))


class UninstallWorker(QThread):
    progress = Signal(int, str)
    succeeded = Signal()
    failed = Signal(str)

    def run(self):
        try:
            self.progress.emit(25, "Removing shortcuts")
            remove_shortcuts()
            self.progress.emit(65, "Removing Windows registration")
            remove_registry()
            self.progress.emit(100, "Finished")
            self.succeeded.emit()
        except Exception as err:  # noqa: BLE001
            self.failed.emit(str(err))


# --------------------------------------------------------------------------- #
# Widgets
# --------------------------------------------------------------------------- #
class Check(QAbstractButton):
    def __init__(self, text: str, checked: bool = True):
        super().__init__()
        self.setText(text)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFont(ui.make_font(ui.UI_FONTS, 10.5))
        self.setFixedHeight(38)

    def sizeHint(self):
        return QSize(QFontMetrics(self.font()).horizontalAdvance(self.text()) + 40, 38)

    def paintEvent(self, _e):
        t = THEME
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(1, (self.height() - 22) / 2, 22, 22)
        on, hov = self.isChecked(), self.underMouse()
        p.setPen(QPen(t.fg if (on or hov) else t.muted, 1.6))
        p.setBrush(t.fg if on else Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(box, 6, 6)
        if on:
            p.setPen(QPen(t.bg, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            x, y = box.x(), box.y()
            p.drawPolyline(QPolygonF([QPointF(x + 5.5, y + 11.5), QPointF(x + 9.5, y + 15.5), QPointF(x + 16.5, y + 7)]))
        p.setPen(t.fg)
        p.setFont(self.font())
        p.drawText(QRectF(34, 0, self.width() - 34, self.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())


class ProgressBar(QWidget):
    def __init__(self):
        super().__init__()
        self.value = 0
        self.setFixedHeight(10)

    def set_value(self, v: int):
        self.value = max(0, min(100, v))
        self.update()

    def paintEvent(self, _e):
        t = THEME
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(t.panel2)
        p.drawRoundedRect(QRectF(self.rect()), 5, 5)
        w = self.width() * self.value / 100
        if w > 0:
            p.setBrush(t.fg)
            p.drawRoundedRect(QRectF(0, 0, max(w, 10), self.height()), 5, 5)


class Side(QWidget):
    """Left panel: the logo on a quiet field of rain."""

    def __init__(self):
        super().__init__()
        self.setFixedWidth(236)
        pm = QPixmap(str(ui.resource("logo.png")))
        self.logo = pm.scaledToWidth(240, Qt.TransformationMode.SmoothTransformation) if not pm.isNull() else pm
        self.logo.setDevicePixelRatio(2)

    def paintEvent(self, _e):
        t = THEME
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), t.panel)
        w, h = self.width(), self.height()
        band_top, band_bottom = 60, h - 60
        p.setPen(QPen(ui.mix(t.panel, t.fg, 0.16), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        rnd = random.Random(11)
        for _ in range(70):
            x, y, ln = rnd.randrange(10, w - 12), rnd.randrange(0, h), rnd.randrange(6, 15)
            if not (y + ln > band_top and y < band_bottom):
                p.drawLine(x, y, x, y + ln)
        if not self.logo.isNull():
            lw = self.logo.width() / 2
            lh = self.logo.height() / 2
            p.drawPixmap(int((w - lw) / 2), 78, self.logo)
            y = 78 + int(lh) + 26
        else:
            y = 200
        p.setPen(t.fg)
        p.setFont(ui.make_font(ui.DISPLAY_FONTS, 19))
        p.drawText(QRectF(0, y, w, 30), Qt.AlignmentFlag.AlignHCenter, APP)
        p.setPen(t.muted)
        p.setFont(ui.make_font(ui.UI_FONTS, 9.5))
        p.drawText(QRectF(0, y + 32, w, 20), Qt.AlignmentFlag.AlignHCenter, f"Version {ui.APP_VERSION}")
        p.setPen(t.line)
        p.drawLine(w - 1, 0, w - 1, h)


class SetupTitleBar(ui.Bar):
    def __init__(self, win: "Wizard", title: str):
        super().__init__("bottom", win)
        self.win = win
        self.setFixedHeight(52)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 8, 0)
        lay.setSpacing(0)
        logo = QLabel()
        pm = QPixmap(str(ui.resource("logo.png")))
        if not pm.isNull():
            pm = pm.scaledToHeight(56, Qt.TransformationMode.SmoothTransformation)
            pm.setDevicePixelRatio(2)
            logo.setPixmap(pm)
        logo.setFixedSize(30, 30)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label = QLabel(title)
        label.setFont(ui.make_font(ui.DISPLAY_FONTS, 12.5))
        self.b_min = ui.IconButton("min", "Minimise", (42, 34))
        self.b_close = ui.IconButton("close", "Close", (42, 34))
        lay.addWidget(logo)
        lay.addSpacing(12)
        lay.addWidget(label)
        lay.addStretch()
        lay.addWidget(self.b_min)
        lay.addWidget(self.b_close)
        self.b_min.clicked.connect(lambda _=False: win.showMinimized())
        self.b_close.clicked.connect(lambda _=False: win.request_close())

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.win.windowHandle():
            self.win.windowHandle().startSystemMove()


# --------------------------------------------------------------------------- #
# The wizard
# --------------------------------------------------------------------------- #
class Wizard(QWidget):
    def __init__(self, uninstall: bool = False):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.uninstall = uninstall
        self.busy = False
        self._done = False
        self._path_ok = True
        self.worker = None
        self.required = 0 if uninstall else payload_size()
        self.dest = (installed_dir() or default_dir()) if uninstall else default_dir()
        title = f"{APP} Uninstall" if uninstall else f"{APP} Setup"
        self.setWindowTitle(title)
        self.setWindowIcon(QIcon(str(ui.resource("icon.png"))))
        self.setFixedSize(800, 520)

        self.titlebar = SetupTitleBar(self, title)
        self.stack = QStackedWidget()
        self.keys: list[str] = []
        self._build_pages()

        self.footer = ui.Bar("top")
        self.footer.setFixedHeight(68)
        fl = QHBoxLayout(self.footer)
        fl.setContentsMargins(24, 0, 24, 0)
        fl.setSpacing(10)
        self.btn_cancel = self._button("Cancel", "ghost")
        self.btn_back = self._button("Back", "ghost")
        self.btn_next = self._button("Next", "primary")
        fl.addStretch()
        for b in (self.btn_cancel, self.btn_back, self.btn_next):
            fl.addWidget(b)
        self.btn_cancel.clicked.connect(lambda _=False: self.request_close())
        self.btn_back.clicked.connect(lambda _=False: self.go(self.idx - 1))
        self.btn_next.clicked.connect(lambda _=False: self.on_next())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(Side())
        body.addWidget(self.stack, 1)
        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)
        root.addWidget(self.titlebar)
        root.addLayout(body, 1)
        root.addWidget(self.footer)

        for w in self.findChildren(ui.Bar):
            w.theme = THEME
        for b in self.findChildren(ui.IconButton):
            b.theme = THEME
        self.idx = 0
        self.go(0)

    # ---- construction ----
    def _button(self, text: str, kind: str) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName(kind)
        b.setMinimumWidth(110)
        b.setFixedHeight(40)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return b

    def _page(self, key: str, title: str, text: str | None = None):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(44, 40, 44, 16)
        lay.setSpacing(0)
        head = QLabel(title)
        head.setFont(ui.make_font(ui.DISPLAY_FONTS, 25))
        lay.addWidget(head)
        lay.addSpacing(14)
        if text:
            body = QLabel(text)
            body.setObjectName("soft")
            body.setWordWrap(True)
            body.setFont(ui.make_font(ui.UI_FONTS, 10.5))
            lay.addWidget(body)
        self.keys.append(key)
        self.stack.addWidget(w)
        return w, lay

    def _build_pages(self):
        if self.uninstall:
            _, lay = self._page("confirm", f"Remove {APP}?", "This removes the app and its shortcuts from your computer. Your documents are not touched.")
            lay.addSpacing(22)
            lay.addWidget(self._hint("Installed in"))
            self.lbl_where = QLabel(str(self.dest))
            self.lbl_where.setWordWrap(True)
            self.lbl_where.setFont(ui.make_font(ui.UI_FONTS, 10.5))
            lay.addWidget(self.lbl_where)
            lay.addStretch()
        else:
            _, lay = self._page(
                "welcome",
                f"Welcome to {APP}",
                "A calm place to write Markdown: one quiet column of text, a live preview when you want it, "
                "and a focus mode that dims everything but the paragraph you\u2019re on.\n\n"
                "Setup takes less than a minute. Choose Next to pick where to install it.",
            )
            lay.addStretch()

            _, lay = self._page("location", "Choose where to install", f"{APP} will be installed in the folder below. To use a different folder, choose Browse.")
            lay.addSpacing(26)
            row = QHBoxLayout()
            row.setSpacing(8)
            self.path_edit = QLineEdit(str(self.dest))
            self.path_edit.setFixedHeight(40)
            self.path_edit.setFont(ui.make_font(ui.UI_FONTS, 10.5))
            self.path_edit.textChanged.connect(self._path_changed)
            browse = self._button("Browse\u2026", "ghost")
            browse.clicked.connect(lambda _=False: self.browse())
            row.addWidget(self.path_edit, 1)
            row.addWidget(browse)
            lay.addLayout(row)
            lay.addSpacing(14)
            self.lbl_space = QLabel("")
            self.lbl_space.setObjectName("hint")
            self.lbl_space.setWordWrap(True)
            lay.addWidget(self.lbl_space)
            lay.addStretch()
            self._path_changed(self.path_edit.text())

            _, lay = self._page("options", "Choose your options")
            lay.addSpacing(12)
            self.chk_desktop = Check("Add a shortcut to the desktop", True)
            self.chk_assoc = Check("Open Markdown (.md) files with Raining Md", True)
            lay.addWidget(self.chk_desktop)
            lay.addWidget(self.chk_assoc)
            lay.addSpacing(26)
            lay.addWidget(self._hint("Ready to install in"))
            self.lbl_summary = QLabel("")
            self.lbl_summary.setWordWrap(True)
            self.lbl_summary.setFont(ui.make_font(ui.UI_FONTS, 10.5))
            lay.addWidget(self.lbl_summary)
            lay.addStretch()

        _, lay = self._page("progress", "Removing\u2026" if self.uninstall else "Installing\u2026")
        lay.addSpacing(22)
        self.bar = ProgressBar()
        lay.addWidget(self.bar)
        lay.addSpacing(14)
        self.lbl_status = QLabel("Starting")
        self.lbl_status.setObjectName("hint")
        lay.addWidget(self.lbl_status)
        lay.addStretch()

        if self.uninstall:
            _, lay = self._page("finish", f"{APP} has been removed", "Thanks for writing with it. Any leftover files are cleared away as soon as you choose Finish.")
            lay.addStretch()
        else:
            _, lay = self._page("finish", "You\u2019re all set", f"{APP} is installed. You\u2019ll find it in the Start menu.")
            lay.addSpacing(22)
            self.chk_launch = Check(f"Launch {APP}", True)
            lay.addWidget(self.chk_launch)
            lay.addStretch()

    def _hint(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setObjectName("hint")
        l.setFont(ui.make_font(ui.UI_FONTS, 9.5))
        return l

    # ---- navigation ----
    def go(self, i: int):
        self.idx = max(0, min(len(self.keys) - 1, i))
        self.stack.setCurrentIndex(self.idx)
        key = self.keys[self.idx]
        if key == "options":
            self.lbl_summary.setText(self.path_edit.text().strip())
        labels = {"options": "Install", "confirm": "Uninstall", "finish": "Finish"}
        self.btn_next.setText(labels.get(key, "Next"))
        self.btn_next.setVisible(key != "progress")
        self.btn_back.setVisible(key in ("location", "options"))
        self.btn_cancel.setVisible(key not in ("progress", "finish"))
        self.btn_next.setEnabled(self._path_ok if key == "location" else True)

    def on_next(self):
        key = self.keys[self.idx]
        if key in ("welcome", "location"):
            self.go(self.idx + 1)
        elif key == "options":
            self.start_install()
        elif key == "confirm":
            self.start_uninstall()
        elif key == "finish":
            if not self.uninstall and self.chk_launch.isChecked():
                subprocess.Popen([str(self.dest / EXE_NAME)], cwd=str(self.dest), creationflags=DETACHED_PROCESS, close_fds=True)
            self.close()

    # ---- location page ----
    def browse(self):
        start = self.path_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Choose install folder", start)
        if chosen:
            p = Path(chosen)
            if p.name.lower() != APP.lower():
                p = p / APP
            self.path_edit.setText(str(p))

    def _path_changed(self, text: str):
        text = text.strip().strip('"')
        ok, msg = True, ""
        if not text:
            ok, msg = False, "Choose a folder to install into."
        else:
            p = Path(text)
            if not p.is_absolute():
                ok, msg = False, "Enter a full path, such as C:\\Users\\you\\Programs\\Raining Md."
            else:
                anchor = p
                while not anchor.exists() and anchor != anchor.parent:
                    anchor = anchor.parent
                try:
                    free = shutil.disk_usage(anchor).free
                except OSError:
                    free = None
                if free is not None and free < self.required * 1.1:
                    ok, msg = False, f"Not enough free space: {fmt_size(self.required)} needed, {fmt_size(free)} available."
                else:
                    avail = f" {fmt_size(free)} is available." if free is not None else ""
                    msg = f"{fmt_size(self.required)} of disk space is needed.{avail} The folder is created if it doesn\u2019t exist."
        self._path_ok = ok
        self.lbl_space.setText(msg)
        idx = getattr(self, "idx", None)
        if idx is not None and self.keys[idx] == "location":
            self.btn_next.setEnabled(ok)

    # ---- running ----
    def _start(self, worker, progress_key: str):
        self.busy = True
        self.worker = worker
        worker.progress.connect(self._progress)
        worker.succeeded.connect(self._succeeded)
        worker.failed.connect(self._failed)
        self.go(self.keys.index(progress_key))
        worker.start()

    def start_install(self):
        self.dest = Path(self.path_edit.text().strip().strip('"'))
        self._start(InstallWorker(self.dest, self.chk_desktop.isChecked(), self.chk_assoc.isChecked()), "progress")

    def start_uninstall(self):
        self._start(UninstallWorker(), "progress")

    def _progress(self, value: int, text: str):
        self.bar.set_value(value)
        self.lbl_status.setText(text)

    def _succeeded(self):
        self.busy = False
        self._done = True
        self.go(self.keys.index("finish"))

    def _failed(self, message: str):
        self.busy = False
        ui.ThemedDialog(self, THEME, "Something went wrong", message, [("Close", "cancel", True)]).ask()
        self.go(self.keys.index("confirm" if self.uninstall else "options"))

    # ---- closing ----
    def request_close(self):
        if self.busy:
            return
        if self.keys[self.idx] == "finish":
            self.close()
            return
        r = ui.ThemedDialog(
            self, THEME, "Quit Setup?", f"{APP} hasn\u2019t been {'removed' if self.uninstall else 'installed'} yet.",
            [("Keep going", "cancel", False), ("Quit", "quit", True)],
        ).ask()
        if r == "quit":
            self.close()

    def closeEvent(self, e):
        if self.busy:
            e.ignore()
            return
        if self.uninstall and self._done:
            self._purge_folder()
        e.accept()

    def _purge_folder(self):
        """Delete the install folder once this process (which lives inside it) has exited."""
        d = self.dest
        if not (d / EXE_NAME).exists():
            return
        q = _q(d)
        _powershell(
            f"for($i=0;$i -lt 30;$i++){{ Start-Sleep -Seconds 1; "
            f"Remove-Item -LiteralPath '{q}' -Recurse -Force -ErrorAction SilentlyContinue; "
            f"if(-not (Test-Path -LiteralPath '{q}')){{ break }} }}",
            wait=False,
        )

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), THEME.bg)
        p.setPen(THEME.line)
        p.drawRect(0, 0, self.width() - 1, self.height() - 1)

    def showEvent(self, e):
        super().showEvent(e)
        if sys.platform == "win32":
            try:
                import ctypes

                pref = ctypes.c_int(2)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(int(self.winId()), 33, ctypes.byref(pref), ctypes.sizeof(pref))
            except Exception:
                pass


def run(uninstall: bool = False) -> int:
    global THEME
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("RainingCompany.RainingMd.Setup")
        except Exception:
            pass
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(ui.make_font(ui.UI_FONTS, 10))
    try:
        from PySide6.QtCore import QSettings

        if QSettings(ui.ORG_NAME, ui.APP_NAME).value("theme", "dark") == "light":
            THEME = ui.LIGHT
    except Exception:
        pass
    tokens = ui.theme_tokens(THEME)
    from string import Template

    app.setStyleSheet(ui.QSS.substitute(tokens) + Template(EXTRA_QSS).substitute(tokens))
    win = Wizard(uninstall)
    win.show()
    screen = app.primaryScreen().availableGeometry()
    win.move(screen.center() - QPoint(win.width() // 2, win.height() // 2))
    return app.exec()


if __name__ == "__main__":
    sys.exit(run(uninstall="--uninstall" in sys.argv))
