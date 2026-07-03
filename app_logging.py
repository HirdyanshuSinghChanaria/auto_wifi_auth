import logging
import logging.handlers
import os
import sys

from storage import get_data_dir

# Lives next to wifi_map.json so users can find it when reporting problems.
LOG_FILE = os.path.join(get_data_dir(), "wifi_autologin.log")


def setup_logging():
    """
    Configures root logging once: a rotating file in the app data dir, plus
    the console when one exists. In a windowed PyInstaller build (console=False)
    stderr is None, so the file is the only place diagnostics survive.
    """
    root = logging.getLogger()
    if root.handlers:
        return  # already configured

    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    try:
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=512 * 1024, backupCount=2, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError:
        pass  # e.g. read-only filesystem — console handler below may still work

    if sys.stderr is not None:
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        root.addHandler(console)
