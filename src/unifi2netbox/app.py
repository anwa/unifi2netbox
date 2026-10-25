import argparse
import sys
from importlib.metadata import version
from pathlib import Path

from unifi2netbox.config import default_config_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UniFi inventory review for NetBox")
    parser.add_argument("--version", action="version", version=version("unifi2netbox"))
    parser.add_argument("--config", type=Path, default=default_config_path())
    arguments = parser.parse_args(argv)

    from PySide6.QtCore import QLocale, QThreadPool
    from PySide6.QtWidgets import QApplication

    from unifi2netbox.gui import MainWindow

    QLocale.setDefault(QLocale("en_GB"))
    app = QApplication([sys.argv[0]])
    app.setApplicationName("unifi2netbox")
    app.setApplicationVersion(version("unifi2netbox"))
    pool = QThreadPool(app)
    pool.setMaxThreadCount(2)
    window = MainWindow(arguments.config, pool)
    window.show()
    return app.exec()
