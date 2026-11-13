# Raining Md

A calm Markdown editor in the Raining Company palette, modelled on GNOME Apostrophe.
PySide6, with window chrome and installer drawn in the same style as the app.

## Run from source
    run.bat                      (creates .venv, installs deps, starts the app)

## Build the installer
    build.bat

Output: `dist_installer\rainingmd-installer.exe`, a single branded setup:
Welcome, Browse for a folder, options (desktop shortcut, .md association), progress, Finish.
It installs per user (no admin prompt), adds a Start menu shortcut and registers the app in
Windows Settings > Apps, where Uninstall opens the same-style uninstaller (`RainingMd.exe --uninstall`).

The installer takes a few seconds to open: it unpacks the embedded app on launch.

## Shortcuts
| Action | Keys |
|---|---|
| New / Open / Save / Save as | Ctrl+N / O / S / Shift+S |
| Bold / Italic / Strikethrough | Ctrl+B / I / Shift+X |
| Heading (H1 to H3 to none) | Ctrl+H |
| Quote / List / Code / Link | Ctrl+Shift+Q / L / C, Ctrl+K |
| Find | Ctrl+F |
| Cycle preview (editor, split, page) | Ctrl+Shift+P |
| Focus mode | Ctrl+Shift+F |
| Light / dark | Ctrl+Shift+T |
| Text size | Ctrl+= , Ctrl+- , Ctrl+0, Ctrl+wheel |
| Distraction-free window | F11 (Esc to leave) |

Palette: ink `#0D1311`, cream `#F8EFCC`, plus mixes of the two.
