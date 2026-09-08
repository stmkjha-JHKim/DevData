"""tray.py -- Windows system tray icon for the packaged .exe.

Only used when frozen (see main.py's `__main__` block) -- running from
source (`python main.py`) keeps the plain console + Ctrl+C flow, since a
developer already has a terminal to work from. The packaged .exe runs
with no console window at all (OraPulse.spec / OraPulse-Folder.spec's
console=False), so without this there would be no visible sign the app
is running and no way to shut it down short of Task Manager.
"""

import pystray
from PIL import Image

import browser


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

    icon = pystray.Icon(
        "OraPulse",
        image,
        title,
        menu=pystray.Menu(
            pystray.MenuItem("Open OraPulse", on_open, default=True),
            pystray.MenuItem("Exit", on_exit),
        ),
    )
    icon.run()
