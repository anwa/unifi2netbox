"""The in-app manual: a table of contents on the left, the page on the right.

Pages are the Markdown files of the ``manual`` folder (see ``manual.py``).
``QTextBrowser`` renders them with their images; links between pages move
the selection in the tree, external links open in the browser.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QImage, QTextDocument
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from unifi2netbox.manual import ManualEntry, build_toc, manual_root

PATH_ROLE = Qt.ItemDataRole.UserRole + 1
_IMAGE_MARGIN = 48


class ManualBrowser(QTextBrowser):
    """Scales screenshots down to the page width; reloads after resizing."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(150)
        self._resize_timer.timeout.connect(self._rescale)
        self._width = 0
        self.setViewportMargins(18, 10, 12, 10)

    def loadResource(self, kind: int, name: QUrl):  # noqa: N802 - Qt override
        if (
            kind == QTextDocument.ResourceType.ImageResource.value
            and name.isLocalFile()
        ):
            image = QImage(name.toLocalFile())
            limit = max(200, self.viewport().width() - _IMAGE_MARGIN)
            if not image.isNull() and image.width() > limit:
                image = image.scaledToWidth(
                    limit, Qt.TransformationMode.SmoothTransformation
                )
            return image
        return super().loadResource(kind, name)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        if abs(self.viewport().width() - self._width) > 24:
            self._resize_timer.start()

    def _rescale(self) -> None:
        self._width = self.viewport().width()
        if self.source().isValid():
            position = self.verticalScrollBar().value()
            self.document().clear()
            self.reload()
            self.verticalScrollBar().setValue(position)


class ManualWindow(QDialog):
    """Non-modal manual window; reuse one instance and call ``show_page``."""

    def __init__(self, parent: QWidget | None = None, root: Path | None = None):
        super().__init__(parent)
        self.setObjectName("manualWindow")
        self.setWindowTitle("unifi2netbox manual")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.resize(1100, 760)
        self.root = root if root is not None else manual_root()
        if self.root is not None and not (self.root / "index.md").is_file():
            self.root = None
        self.items: dict[Path, QTreeWidgetItem] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        bar = QHBoxLayout()
        bar.setContentsMargins(12, 8, 12, 8)
        self.back_button = QPushButton("Back")
        self.back_button.setObjectName("manualBack")
        self.back_button.setEnabled(False)
        self.forward_button = QPushButton("Forward")
        self.forward_button.setObjectName("manualForward")
        self.forward_button.setEnabled(False)
        self.home_button = QPushButton("Overview")
        self.home_button.setObjectName("manualHome")
        for button in (self.back_button, self.forward_button, self.home_button):
            button.setProperty("variant", "ghost")
            bar.addWidget(button)
        bar.addStretch()
        layout.addLayout(bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setObjectName("manualTree")
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(220)
        self.browser = ManualBrowser()
        self.browser.setObjectName("manualPage")
        self.browser.setOpenExternalLinks(True)
        self.browser.setOpenLinks(True)
        splitter.addWidget(self.tree)
        splitter.addWidget(self.browser)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 820])
        layout.addWidget(splitter, 1)

        self.back_button.clicked.connect(self.browser.backward)
        self.forward_button.clicked.connect(self.browser.forward)
        self.home_button.clicked.connect(lambda: self.show_page())
        self.browser.backwardAvailable.connect(self.back_button.setEnabled)
        self.browser.forwardAvailable.connect(self.forward_button.setEnabled)
        self.browser.sourceChanged.connect(self._sync_tree)
        self.tree.currentItemChanged.connect(self._open_item)

        if self.root is None:
            self.tree.setEnabled(False)
            self.home_button.setEnabled(False)
            self.browser.setPlainText("The manual is not installed with this build.")
            return
        self._add(build_toc(self.root), None)
        self.tree.expandAll()
        self.show_page()

    def _add(self, entry: ManualEntry, parent: QTreeWidgetItem | None):
        item = QTreeWidgetItem([entry.title])
        item.setData(0, PATH_ROLE, str(entry.path))
        item.setToolTip(0, entry.title)
        if parent is None:
            self.tree.addTopLevelItem(item)
        else:
            parent.addChild(item)
        self.items[entry.path.resolve()] = item
        for child in entry.children:
            self._add(child, item)
        return item

    def show_page(self, relative: str = "") -> None:
        """Open a page relative to the manual root; empty for the overview."""
        if self.root is None:
            return
        path = (self.root / (relative or "index.md")).resolve()
        self.browser.setSource(QUrl.fromLocalFile(str(path)))

    def current_page(self) -> Path | None:
        url = self.browser.source()
        return Path(url.toLocalFile()).resolve() if url.isLocalFile() else None

    def _open_item(self, item: QTreeWidgetItem | None, _previous=None) -> None:
        if item is None:
            return
        path = Path(item.data(0, PATH_ROLE)).resolve()
        if path != self.current_page():
            self.browser.setSource(QUrl.fromLocalFile(str(path)))

    def _sync_tree(self, url: QUrl) -> None:
        if not url.isLocalFile():
            return
        item = self.items.get(Path(url.toLocalFile()).resolve())
        if item is not None and item is not self.tree.currentItem():
            self.tree.blockSignals(True)
            self.tree.setCurrentItem(item)
            self.tree.blockSignals(False)
