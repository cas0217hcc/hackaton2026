import os
import subprocess
import sys
from typing import Callable


class FolderPickerError(Exception):
    pass


# Runs in its own process: Tk needs a main thread, which the web server's worker threads are not.
PICKER = r'''
import sys
import tkinter as tk
from tkinter import filedialog
root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)  # otherwise the dialog can open behind the browser
print(filedialog.askdirectory(parent=root, initialdir=sys.argv[1] or None, mustexist=True, title="Choose a source folder") or "")
'''


def pick_folder(initial: str = "", runner: Callable = subprocess.run) -> str:
    """Open the OS folder picker on this machine; the chosen path, or "" if cancelled."""
    proc = runner([sys.executable, "-c", PICKER, initial if os.path.isdir(initial) else ""], capture_output=True, text=True)
    if proc.returncode != 0:
        raise FolderPickerError("Could not open the folder picker (needs Python with Tk). Type the path instead.")
    path = proc.stdout.strip()
    return os.path.normpath(path) if path else ""
