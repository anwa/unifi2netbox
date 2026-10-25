import math
import os
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


def load_config(path: Path) -> NetBoxConfig:
    return _load_section(path, "netbox", NetBoxConfig)


def load_unifi_config(path: Path) -> UniFiConfig:
    return _load_section(path, "unifi_network", UniFiConfig)


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
    _save_section(path, "netbox", config)


def save_unifi_config(path: Path, config: UniFiConfig) -> None:
    _save_section(path, "unifi_network", config)


def _save_section(path: Path, name: str, config: NetBoxConfig) -> None:
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
