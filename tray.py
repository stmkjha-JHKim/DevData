"""tray.py -- Windows system tray icon for the packaged .exe.

Only used when frozen (see main.py's `__main__` block) -- running from
source (`python main.py`) keeps the plain console + Ctrl+C flow, since a
developer already has a terminal to work from. The packaged .exe runs
with no console window at all (AtlasStudio-Folder.spec's console=False),
so without this there would be no visible sign the app is running and no
way to shut it down short of Task Manager.

Adapted from OraPulse's own tray.py (D:\\STMKJHA\\00.Git\\01.OraPulse\\
tray.py) -- same pystray wiring, with AtlasStudio's own name/menu text and
(via main.py's icon_path argument) its own favicon.ico, never OraPulse's.
"""

import pystray
from PIL import Image

import browser


def run(url: str, icon_path, title: str, server) -> None:
    """Blocks the calling thread in the tray icon's own event loop --
    pystray requires this to be the main thread on Windows -- until "종료"
    is clicked, at which point it stops uvicorn (via its cooperative
    should_exit flag, the same mechanism Ctrl+C uses) and then itself."""
    image = Image.open(icon_path)

    def on_open(icon, item):
        browser.open_app_window(url)

    def on_exit(icon, item):
        server.should_exit = True
        icon.stop()

    icon = pystray.Icon(
        "AtlasStudio",
        image,
        title,
        menu=pystray.Menu(
            pystray.MenuItem("창 열기", on_open, default=True),
            pystray.MenuItem("종료", on_exit),
        ),
    )
    icon.run()
