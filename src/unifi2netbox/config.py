import math
import os
import re
import tempfile
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from urllib.parse import urlsplit

import tomlkit
from platformdirs import user_config_path


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class NetBoxConfig:
    url: str = ""
    token: str = field(default="", repr=False)
    verify_tls: bool = True
    ca_bundle: str = ""
    timeout: float = 10.0

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str)
            for value in (self.url, self.token, self.ca_bundle)
        ):
            raise ConfigError("URL, token and CA bundle must be strings.")
        if type(self.verify_tls) is not bool:
            raise ConfigError("TLS verification must be true or false.")
        if (
            isinstance(self.timeout, bool)
            or not isinstance(self.timeout, (int, float))
            or not math.isfinite(self.timeout)
            or not 1 <= self.timeout <= 60
        ):
            raise ConfigError("Timeout must be between 1 and 60 seconds.")
        if any(ord(character) < 32 for character in self.token):
            raise ConfigError("Token must not contain control characters.")
        if self.url:
            try:
                parsed = urlsplit(self.url)
                port = parsed.port
                valid = (
                    parsed.scheme in {"http", "https"}
                    and parsed.hostname
                    and not parsed.username
                    and not parsed.password
                    and not parsed.query
                    and not parsed.fragment
                    and not any(character.isspace() for character in self.url)
                    and (port is None or port > 0)
                )
            except ValueError:
                valid = False
            if not valid:
                raise ConfigError(
                    "Enter an explicit http:// or https:// base URL without "
                    "credentials, a query or a fragment."
                )
            if parsed.path.rstrip("/").endswith("/api"):
                raise ConfigError("Enter the NetBox base URL, without /api.")
        if self.ca_bundle and not Path(self.ca_bundle).is_file():
            raise ConfigError("The CA bundle must be an existing file.")

    @property
    def configured(self) -> bool:
        return bool(self.url and self.token.strip())

    @property
    def security_warning(self) -> str:
        if self.url.startswith("http://"):
            return "Plain HTTP: the API token is transmitted without encryption."
        if self.url and not self.verify_tls:
            return "TLS certificate verification is disabled."
        return ""


def default_config_path() -> Path:
    return user_config_path("unifi2netbox", appauthor=False) / "config.toml"


@dataclass(frozen=True)
class UniFiConfig(NetBoxConfig):
    site: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.site, str) or any(
            ord(character) < 32 for character in self.site
        ):
            raise ConfigError("Site must be a string without control characters.")
        if self.url and "/integration/" in urlsplit(self.url).path:
            raise ConfigError("Enter the UniFi console base URL, not an API endpoint.")


@dataclass(frozen=True)
class ProtectConfig(NetBoxConfig):
    """Console running UniFi Protect (for example a UNVR); optional."""

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.url and "/integration/" in urlsplit(self.url).path:
            raise ConfigError(
                "Enter the Protect console base URL, not an API endpoint."
            )


@dataclass(frozen=True)
class AccessConfig(NetBoxConfig):
    """UniFi Access developer API (console URL with port 12445); optional."""

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.url and "/api/" in urlsplit(self.url).path + "/":
            raise ConfigError("Enter the Access API base URL, without /api.")


@dataclass(frozen=True)
class DriveConfig(NetBoxConfig):
    """UniFi Drive console (UNAS) with its local API key; optional."""

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.url and urlsplit(self.url).path.strip("/"):
            raise ConfigError("Enter the UNAS console base URL, without a path.")


@dataclass(frozen=True)
class BehaviorConfig:
    include_all_netbox_delete_candidates: bool = False
    default_device_role_name: str = ""
    netbox_site_name: str = ""

    def __post_init__(self) -> None:
        if type(self.include_all_netbox_delete_candidates) is not bool:
            raise ConfigError(
                "Delete-candidate scope must be enabled or disabled explicitly."
            )
        if not isinstance(self.default_device_role_name, str) or any(
            ord(character) < 32 for character in self.default_device_role_name
        ):
            raise ConfigError(
                "Default device role name must be a string without control characters."
            )
        if not isinstance(self.netbox_site_name, str) or any(
            ord(character) < 32 for character in self.netbox_site_name
        ):
            raise ConfigError(
                "NetBox site name must be a string without control characters."
            )


DEFAULT_LIBRARY_REPOSITORY = "netbox-community/devicetype-library"
DEFAULT_LIBRARY_BRANCH = "master"
LOCAL_TYPES_FOLDER = "devicetype-library"
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_BRANCH = re.compile(r"[A-Za-z0-9_./-]+")


@dataclass(frozen=True)
class DeviceTypesConfig:
    """Device type sources: local folder, devicetype-library, techspecs."""

    local_folder: str = ""
    use_library: bool = True
    library_repository: str = DEFAULT_LIBRARY_REPOSITORY
    library_branch: str = DEFAULT_LIBRARY_BRANCH
    use_techspecs: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.local_folder, str) or any(
            ord(character) < 32 for character in self.local_folder
        ):
            raise ConfigError("The local type folder must be a path.")
        if type(self.use_library) is not bool or type(self.use_techspecs) is not bool:
            raise ConfigError("Library and techspecs lookups must be on or off.")
        if not isinstance(self.library_repository, str) or not _REPOSITORY.fullmatch(
            self.library_repository
        ):
            raise ConfigError("Enter the library repository as owner/name.")
        if (
            not isinstance(self.library_branch, str)
            or not _BRANCH.fullmatch(self.library_branch)
            or ".." in self.library_branch
        ):
            raise ConfigError("Enter a valid library branch name.")


def local_type_folder(config: DeviceTypesConfig, config_path: Path) -> Path:
    """The configured folder, or ``devicetype-library`` next to the config."""
    if config.local_folder.strip():
        return Path(config.local_folder.strip()).expanduser()
    return config_path.parent / LOCAL_TYPES_FOLDER


THEME_CHOICES = ("system", "light", "dark")


@dataclass(frozen=True)
class UiConfig:
    theme: str = "system"

    def __post_init__(self) -> None:
        if self.theme not in THEME_CHOICES:
            raise ConfigError("Theme must be system, light or dark.")


def load_config(path: Path) -> NetBoxConfig:
    return _load_section(path, "netbox", NetBoxConfig)


def load_unifi_config(path: Path) -> UniFiConfig:
    return _load_section(path, "unifi_network", UniFiConfig)


def load_protect_config(path: Path) -> ProtectConfig:
    return _load_section(path, "unifi_protect", ProtectConfig)


def save_protect_config(path: Path, config: ProtectConfig) -> None:
    _save_sections(path, {"unifi_protect": config})


def load_access_config(path: Path) -> AccessConfig:
    return _load_section(path, "unifi_access", AccessConfig)


def load_drive_config(path: Path) -> DriveConfig:
    return _load_section(path, "unifi_drive", DriveConfig)


def load_behavior_config(path: Path) -> BehaviorConfig:
    return _load_section(path, "behavior", BehaviorConfig)


def _load_section[Config: NetBoxConfig](
    path: Path, name: str, config_type: type[Config]
) -> Config:
    try:
        with path.open("rb") as source:
            document = tomllib.load(source)
    except FileNotFoundError:
        return config_type()
    except OSError, ValueError:
        raise ConfigError(
            "Cannot read configuration: check file access and TOML."
        ) from None
    if (
        type(document.get("schema_version", 1)) is not int
        or document.get("schema_version", 1) != 1
    ):
        raise ConfigError("Unsupported configuration schema version.")
    section = document.get(name, {})
    if not isinstance(section, dict):
        raise ConfigError(f"The {name} configuration must be a TOML table.")
    return config_type(
        **{
            item.name: section[item.name]
            for item in fields(config_type)
            if item.name in section
        }
    )


def save_config(path: Path, config: NetBoxConfig) -> None:
    _save_sections(path, {"netbox": config})


def save_unifi_config(path: Path, config: UniFiConfig) -> None:
    _save_sections(path, {"unifi_network": config})


def save_behavior_config(path: Path, config: BehaviorConfig) -> None:
    _save_sections(path, {"behavior": config})


def load_device_types_config(path: Path) -> DeviceTypesConfig:
    return _load_section(path, "device_types", DeviceTypesConfig)


def save_device_types_config(path: Path, config: DeviceTypesConfig) -> None:
    _save_sections(path, {"device_types": config})


def load_ui_config(path: Path) -> UiConfig:
    return _load_section(path, "ui", UiConfig)


def save_ui_config(path: Path, config: UiConfig) -> None:
    _save_sections(path, {"ui": config})


def save_connections(
    path: Path,
    netbox: NetBoxConfig,
    unifi: UniFiConfig,
    behavior: BehaviorConfig | None = None,
    protect: ProtectConfig | None = None,
    access: AccessConfig | None = None,
    drive: DriveConfig | None = None,
    device_types: DeviceTypesConfig | None = None,
) -> None:
    sections: dict[str, object] = {"netbox": netbox, "unifi_network": unifi}
    if behavior is not None:
        sections["behavior"] = behavior
    if protect is not None:
        sections["unifi_protect"] = protect
    if access is not None:
        sections["unifi_access"] = access
    if drive is not None:
        sections["unifi_drive"] = drive
    if device_types is not None:
        sections["device_types"] = device_types
    _save_sections(path, sections)


def _save_sections(path: Path, configs: dict[str, object]) -> None:
    temporary: Path | None = None
    try:
        document = (
            tomlkit.parse(path.read_text(encoding="utf-8"))
            if path.exists()
            else tomlkit.document()
        )
        schema_version = document.unwrap().get("schema_version", 1)
        if type(schema_version) is not int or schema_version != 1:
            raise ConfigError("Unsupported configuration schema version.")
        document["schema_version"] = 1
        for name, config in configs.items():
            section = document.get(name)
            if section is None:
                section = tomlkit.table()
                document[name] = section
            if not isinstance(section, dict):
                raise ConfigError(f"The {name} configuration must be a TOML table.")
            for item in fields(config):
                section[item.name] = getattr(config, item.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, filename = tempfile.mkstemp(dir=path.parent, prefix=".config-")
        temporary = Path(filename)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(tomlkit.dumps(document))
            output.flush()
            os.fsync(output.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
    except ConfigError:
        raise
    except OSError, ValueError, TypeError:
        raise ConfigError(
            "Cannot save configuration. The previous file has been preserved."
        ) from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
