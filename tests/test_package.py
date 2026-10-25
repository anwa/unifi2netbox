import ctypes
import os
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import pytest

from unifi2netbox.config import NetBoxConfig, save_config


@pytest.mark.skipif(
    sys.platform != "win32" or not os.environ.get("UNIFI2NETBOX_EXE"),
    reason="Requires an explicitly selected native Windows build.",
)
def test_packaged_window_startup_and_shutdown(qtbot, tmp_path):
    from ctypes import wintypes

    executable = Path(os.environ["UNIFI2NETBOX_EXE"]).resolve(strict=True)
    config_path = tmp_path / "config.toml"
    save_config(config_path, NetBoxConfig())
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.PostMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    expected_title = f"unifi2netbox {version('unifi2netbox')}"
    windows = {}
    process = subprocess.Popen([str(executable), "--config", str(config_path)])

    @callback_type
    def find_window(handle, parameter):
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(process_id))
        if process_id.value == process.pid:
            text = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(handle, text, len(text))
            windows[text.value] = handle
        return True

    def started():
        if process.poll() is not None:
            raise RuntimeError("Packaged application exited before showing its window.")
        user32.EnumWindows(find_window, 0)
        return expected_title in windows and "Settings" in windows

    try:
        qtbot.waitUntil(started, timeout=60000)
        settings_handle = windows["Settings"]
        assert user32.PostMessageW(settings_handle, 0x0010, 0, 0)
        qtbot.waitUntil(lambda: not user32.IsWindow(settings_handle), timeout=5000)
        assert user32.PostMessageW(windows[expected_title], 0x0010, 0, 0)
        qtbot.waitUntil(lambda: process.poll() is not None, timeout=15000)
        assert process.returncode == 0
        assert load_empty(config_path)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


def load_empty(path):
    from unifi2netbox.config import load_config

    return load_config(path) == NetBoxConfig()
