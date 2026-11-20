"""The in-app manual: a table of contents on the left, the page on the right.

Pages are the Markdown files of the ``manual`` folder (see ``manual.py``).
``QTextBrowser`` renders them with their images; links between pages move
the selection in the tree, external links open in the browser.

The search field (Ctrl+F) searches all pages; the results replace the tree
while a query is entered. Opening a result marks every occurrence of the
words on the page and jumps to the first; F3 and Shift+F3 move between them,
Escape ends the search.
"""

from __future__ import annotations

import re
from html import escape
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import (
    QColor,
    QImage,
    QKeySequence,
    QShortcut,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTextBrowser,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from unifi2netbox import theme
from unifi2netbox.manual import (
    ManualEntry,
    build_toc,
    manual_root,
    search_manual,
    search_terms,
)

PATH_ROLE = Qt.ItemDataRole.UserRole + 1


def _marked(text: str, terms) -> str:
    """HTML of ``text`` with the search words in bold."""
    html = escape(text)
    for term in sorted(terms, key=len, reverse=True):
        html = re.sub(
            re.escape(escape(term)),
            lambda m: f"<b>{m.group(0)}</b>",
            html,
            flags=re.IGNORECASE,
        )
    return html


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
        self.search = QLineEdit()
        self.search.setObjectName("manualSearch")
        self.search.setPlaceholderText("Search the manual (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(260)
        bar.addWidget(self.search)
        layout.addLayout(bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setObjectName("manualTree")
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(220)
        self.results = QListWidget()
        self.results.setObjectName("manualResults")
        self.results.setWordWrap(True)
        self.results_label = QLabel("")
        self.results_label.setObjectName("manualResultCount")
        self.results_label.setProperty("role", "secondary")
        results_page = QWidget()
        results_layout = QVBoxLayout(results_page)
        results_layout.setContentsMargins(0, 0, 0, 0)
        results_layout.addWidget(self.results_label)
        results_layout.addWidget(self.results, 1)
        self.left = QStackedWidget()
        self.left.addWidget(self.tree)
        self.left.addWidget(results_page)
        self.browser = ManualBrowser()
        self.browser.setObjectName("manualPage")
        self.browser.setOpenExternalLinks(True)
        self.browser.setOpenLinks(True)
        splitter.addWidget(self.left)
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
        self.terms: tuple[str, ...] = ()
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self.run_search)
        self.search.textChanged.connect(lambda _t: self._search_timer.start())
        self.search.returnPressed.connect(self.open_first_result)
        self.results.itemActivated.connect(self._open_result)
        self.results.itemClicked.connect(self._open_result)
        self.browser.sourceChanged.connect(lambda _u: self._highlight())
        QShortcut(QKeySequence.StandardKey.Find, self, activated=self.focus_search)
        QShortcut(QKeySequence.StandardKey.FindNext, self, activated=self.find_next)
        QShortcut(
            QKeySequence.StandardKey.FindPrevious,
            self,
            activated=lambda: self.find_next(backward=True),
        )
        QShortcut(
            QKeySequence(Qt.Key.Key_Escape), self.search, activated=self.end_search
        )

        if self.root is None:
            self.tree.setEnabled(False)
            self.home_button.setEnabled(False)
            self.browser.setPlainText("The manual is not installed with this build.")
            return
        self._add(build_toc(self.root), None)
        self.tree.expandAll()
        self.show_page()

    # -- search ------------------------------------------------------------------

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def end_search(self) -> None:
        self.search.clear()
        self.run_search()
        self.browser.setFocus()

    def run_search(self) -> None:
        """Show the pages matching the search field instead of the tree."""
        self._search_timer.stop()
        query = self.search.text()
        self.terms = search_terms(query)
        if not self.terms or self.root is None:
            self.left.setCurrentIndex(0)
            self._highlight()
            return
        hits = search_manual(self.root, query)
        self.results.clear()
        colors = theme.colors()
        for hit in hits:
            item = QListWidgetItem()
            item.setData(PATH_ROLE, str(hit.path))
            plain = f"{hit.title}\n{hit.chapter}\n{hit.snippet}"
            # The label draws the row; the item keeps the text for tooltips
            # and screen readers (no second, overlapping text).
            item.setToolTip(str(hit.path.relative_to(self.root)))
            item.setData(Qt.ItemDataRole.AccessibleTextRole, plain)
            chapter = (
                f" <span style='color:{colors.text_secondary}'>"
                f"\u00b7 {escape(hit.chapter)}</span>"
                if hit.chapter
                else ""
            )
            label = QLabel(
                f"<b>{escape(hit.title)}</b>{chapter}<br>"
                f"<span style='font-size:small'>{_marked(hit.snippet, self.terms)}"
                "</span>"
            )
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setContentsMargins(6, 4, 6, 4)
            self.results.addItem(item)
            self.results.setItemWidget(item, label)
            item.setSizeHint(label.sizeHint())
        count = len(hits)
        self.results_label.setText(
            f"{count} page{'s' if count != 1 else ''} found"
            if count
            else "Nothing found."
        )
        self.left.setCurrentIndex(1)
        self._highlight()

    def open_first_result(self) -> None:
        self.run_search()
        if self.results.count():
            self._open_result(self.results.item(0))

    def _open_result(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        self.results.setCurrentItem(item)
        path = Path(item.data(PATH_ROLE)).resolve()
        if path != self.current_page():
            self.browser.setSource(QUrl.fromLocalFile(str(path)))
        else:
            self._highlight()

    def _highlight(self) -> None:
        """Mark every occurrence of the search words; jump to the first."""
        selections = []
        fmt = QTextCharFormat()
        mark = QColor(theme.colors().warning)
        mark.setAlpha(110)
        fmt.setBackground(mark)
        document = self.browser.document()
        for term in self.terms:
            cursor = QTextCursor(document)
            while True:
                cursor = document.find(term, cursor)
                if cursor.isNull():
                    break
                selection = QTextEdit.ExtraSelection()
                selection.cursor = cursor
                selection.format = fmt
                selections.append(selection)
        self.browser.setExtraSelections(selections)
        if selections:
            first = min(selections, key=lambda s: s.cursor.selectionStart())
            cursor = QTextCursor(first.cursor)
            self.browser.setTextCursor(cursor)
            self.browser.ensureCursorVisible()

    def match_count(self) -> int:
        return len(self.browser.extraSelections())

    def find_next(self, backward: bool = False) -> bool:
        """Move to the next (or previous) occurrence of the first word."""
        if not self.terms:
            return False
        flags = QTextDocument.FindFlag(0)
        if backward:
            flags = QTextDocument.FindFlag.FindBackward
        if self.browser.find(self.terms[0], flags):
            return True
        cursor = self.browser.textCursor()  # wrap around
        cursor.movePosition(
            QTextCursor.MoveOperation.End
            if backward
            else QTextCursor.MoveOperation.Start
        )
        self.browser.setTextCursor(cursor)
        return self.browser.find(self.terms[0], flags)

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
