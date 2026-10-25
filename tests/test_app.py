import subprocess
import sys

from unifi2netbox.config import NetBoxConfig, save_config


def test_main_initializes_english_locale_and_window(tmp_path):
    path = tmp_path / "config.toml"
    save_config(path, NetBoxConfig())
    script = """
import socket
import sys
from PySide6.QtCore import QLocale, QTimer
from PySide6.QtWidgets import QApplication
from unifi2netbox.app import main

def blocked(*args, **kwargs):
    raise AssertionError("Live network is disabled.")

socket.socket.connect = blocked
socket.socket.connect_ex = blocked
original_exec = QApplication.exec

def short_exec(self):
    QTimer.singleShot(100, self.quit)
    return original_exec()

QApplication.exec = short_exec
assert main(["--config", sys.argv[1]]) == 0
assert QLocale().name() == "en_GB"
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(path)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
