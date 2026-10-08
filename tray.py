"""tray.py -- Windows system tray icon for the packaged .exe.

Only used when frozen (see main.py's `__main__` block) -- running from
source (`python main.py`) keeps the plain console + Ctrl+C flow, since a
developer already has a terminal to work from. The packaged .exe runs
with no console window at all (OraPulse.spec / OraPulse-Folder.spec's
console=False), so without this there would be no visible sign the app
is running and no way to shut it down short of Task Manager.
"""

import pystray
from pystray._util import win32 as _pystray_win32
from PIL import Image

import browser

# Real Win32 WM_NULL (0x0000) -- a genuine no-op message, not one of
# pystray's own WM_USER-based custom message codes (see _Icon below for why
# this gets posted).
_WM_NULL = 0


class _Icon(pystray.Icon):
    """Works around a long-standing pystray issue on Windows: its own
    right-click handler (_win32.Icon._on_notify) calls TrackPopupMenuEx but
    never posts a follow-up message afterwards. Microsoft's own
    Shell_NotifyIcon documentation is explicit that a benign message (e.g.
    WM_NULL) must be posted to the icon's window right after
    TrackPopupMenu(Ex) returns, or the context menu will fail to reappear
    on a later right-click -- it shows once and then silently stops
    working, exactly the symptom this class exists to fix. Only on_notify
    is overridden (menu creation/display itself is still entirely
    pystray's own code); this just adds the one extra step pystray's
    Windows backend is missing. Windows-only by construction -- pystray.Icon
    *is* pystray._win32.Icon whenever this module is even imported (see
    main.py's `if getattr(sys, "frozen", False): import tray`, which only
    happens in the Windows-only packaged build)."""

    def _on_notify(self, wparam, lparam):
        super()._on_notify(wparam, lparam)
        _pystray_win32.PostMessage(self._hwnd, _WM_NULL, 0, 0)


def run(url: str, icon_path, title: str, server) -> None:
    """Blocks the calling thread in the tray icon's own event loop --
    pystray requires this to be the main thread on Windows -- until "Exit"
    is clicked, at which point it stops uvicorn (via its cooperative
    should_exit flag, the same mechanism Ctrl+C uses) and then itself."""
    image = Image.open(icon_path)

    def on_open(icon, item):
        browser.open_app_window(url)

    def on_exit(icon, item):
        server.should_exit = True
        icon.stop()

    icon = _Icon(
        "OraPulse",
        image,
        title,
        menu=pystray.Menu(
            pystray.MenuItem("Open OraPulse", on_open, default=True),
            pystray.MenuItem("Exit", on_exit),
        ),
    )
    icon.run()
