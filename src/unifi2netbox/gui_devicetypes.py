"""Device type GUI: Settings page, editor window and picker dialog (M12)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from unifi2netbox.config import (
    DEFAULT_LIBRARY_BRANCH,
    DEFAULT_LIBRARY_REPOSITORY,
    ConfigError,
    DeviceTypesConfig,
    local_type_folder,
)
from unifi2netbox.gui_jobs import TaskRunner
from unifi2netbox.library import (
    LibraryCache,
    LibraryIndex,
    cache_folder,
    refresh_index,
)


def _label(text: str, role: str = "") -> QLabel:
    widget = QLabel(text)
    widget.setWordWrap(True)
    if role:
        widget.setProperty("role", role)
    return widget


def index_summary(index: LibraryIndex | None) -> str:
    if index is None:
        return "No library index yet. Refresh it to search the library."
    when = index.retrieved_at.replace("T", " ")[:16]
    return (
        f"{len(index.entries)} device types from {len(index.manufacturers())} "
        f"manufacturers, retrieved {when} UTC."
    )


class DeviceTypeSettingsPage(QWidget):
    """Settings page "Device types" (local folder, library, techspecs)."""

    changed = Signal()

    def __init__(
        self,
        config: DeviceTypesConfig,
        config_path: Path,
        pool: QThreadPool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config_path = config_path
        self.runner = TaskRunner(pool, self)
        self.runner.finished.connect(self._index_finished)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(_label("Device types", "heading"))
        layout.addWidget(
            _label(
                "Where the device type picker and editor look for definitions. "
                "Files use the netbox-community devicetype-library format, so they "
                "can be contributed there.",
                "secondary",
            )
        )
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.local_folder = QLineEdit(config.local_folder)
        self.local_folder.setObjectName("typesLocalFolder")
        self.local_folder.setPlaceholderText(
            str(local_type_folder(DeviceTypesConfig(), config_path))
        )
        browse = QToolButton()
        browse.setText("...")
        browse.setToolTip("Choose the local type folder")
        browse.clicked.connect(self._browse)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.local_folder, 1)
        folder_row.addWidget(browse)
        form.addRow("Local type folder", folder_row)
        layout.addLayout(form)
        layout.addWidget(
            _label(
                "Definitions are kept under device-types/<Manufacturer>/. Point it "
                "to a clone of your devicetype-library fork to open pull requests "
                "from it.",
                "caption",
            )
        )

        self.use_library = QCheckBox("Search netbox-community/devicetype-library")
        self.use_library.setObjectName("typesUseLibrary")
        self.use_library.setChecked(config.use_library)
        layout.addWidget(self.use_library)
        library_form = QFormLayout()
        library_form.setVerticalSpacing(10)
        self.repository = QLineEdit(config.library_repository)
        self.repository.setObjectName("typesRepository")
        self.repository.setPlaceholderText(DEFAULT_LIBRARY_REPOSITORY)
        self.branch = QLineEdit(config.library_branch)
        self.branch.setObjectName("typesBranch")
        self.branch.setPlaceholderText(DEFAULT_LIBRARY_BRANCH)
        library_form.addRow("Repository", self.repository)
        library_form.addRow("Branch", self.branch)
        layout.addLayout(library_form)
        self.refresh_button = QPushButton("Refresh index")
        self.refresh_button.setObjectName("typesRefreshIndex")
        self.refresh_button.clicked.connect(self.refresh)
        self.index_status = _label("", "caption")
        self.index_status.setObjectName("typesIndexStatus")
        row = QHBoxLayout()
        row.addWidget(self.refresh_button)
        row.addWidget(self.index_status, 1)
        layout.addLayout(row)
        layout.addWidget(
            _label(
                "The index is read from GitHub only when you refresh it; files are "
                "downloaded when you open them. Nothing about your network is sent.",
                "caption",
            )
        )

        self.use_techspecs = QCheckBox(
            "Look up UniFi models on techspecs.ui.com (on request in the editor)"
        )
        self.use_techspecs.setObjectName("typesUseTechspecs")
        self.use_techspecs.setChecked(config.use_techspecs)
        layout.addWidget(self.use_techspecs)
        layout.addStretch()
        self.use_library.toggled.connect(self._update_enabled)
        self._update_enabled()
        self._show_cached_index(config)

    def config_from_fields(self) -> DeviceTypesConfig:
        return DeviceTypesConfig(
            local_folder=self.local_folder.text().strip(),
            use_library=self.use_library.isChecked(),
            library_repository=self.repository.text().strip()
            or DEFAULT_LIBRARY_REPOSITORY,
            library_branch=self.branch.text().strip() or DEFAULT_LIBRARY_BRANCH,
            use_techspecs=self.use_techspecs.isChecked(),
        )

    @property
    def busy(self) -> bool:
        return self.runner.busy

    def refresh(self) -> None:
        try:
            config = self.config_from_fields()
        except ConfigError as error:
            self.index_status.setText(str(error))
            return
        self.refresh_button.setEnabled(False)
        self.index_status.setText("Reading the library index from GitHub...")
        path = self.config_path
        self.runner.start(lambda: refresh_index(config, path))
        self.changed.emit()

    def _index_finished(self, result: object) -> None:
        self.refresh_button.setEnabled(self.use_library.isChecked())
        if isinstance(result, LibraryIndex):
            self.index_status.setText(index_summary(result))
        else:
            self.index_status.setText(f"Index not refreshed: {result}")
        self.changed.emit()

    def _show_cached_index(self, config: DeviceTypesConfig) -> None:
        index = LibraryCache(cache_folder(self.config_path)).load_index(config)
        self.index_status.setText(index_summary(index))

    def _update_enabled(self) -> None:
        enabled = self.use_library.isChecked()
        for widget in (self.repository, self.branch, self.refresh_button):
            widget.setEnabled(enabled and not self.runner.busy)

    def _browse(self) -> None:
        start = self.local_folder.text().strip() or self.local_folder.placeholderText()
        folder = QFileDialog.getExistingDirectory(
            self, "Choose the local type folder", start
        )
        if folder:
            self.local_folder.setText(folder)
