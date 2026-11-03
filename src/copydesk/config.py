"""Load the configuration file (copydesk.toml) and environment overrides.

The file holds what the server needs before it can talk to the database:
where the database is, how to send email, the secret key and so on. Everything
an editor might want to change (the publication's name, colours, reader
groups, permissions) lives in the database and is edited in the dashboard.

Lookup order for the file:
  1. the path passed in explicitly (``quillsail --config ...``)
  2. the COPYDESK_CONFIG environment variable
  3. ./copydesk.toml
  4. /etc/copydesk/copydesk.toml

Any value can also be set with an environment variable (see ENV_OVERRIDES),
which is handy for Docker and for keeping passwords out of the file.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

CONFIG_ENV = "COPYDESK_CONFIG"
DEFAULT_LOCATIONS = (Path("copydesk.toml"), Path("/etc/copydesk/copydesk.toml"))

MAIL_BACKENDS = ("smtp", "console", "file", "memory")
MAIL_SECURITY = ("none", "starttls", "ssl")

# Environment variable -> (section, key) in the TOML file.
ENV_OVERRIDES: dict[str, tuple[str, str]] = {
    "CLOUDFLARE_CLIENT_ID": ("oauth", "cloudflare_client_id"),
    "COPYDESK_CLOUDFLARE_CLIENT_ID": ("oauth", "cloudflare_client_id"),
    "COPYDESK_CLOUDFLARE_EDGE_SCOPES": ("oauth", "cloudflare_edge_scopes"),
    "COPYDESK_CLOUDFLARE_SCOPES": ("oauth", "cloudflare_scopes"),
    "COPYDESK_CLOUDFLARE_RELAY_URL": ("oauth", "cloudflare_relay_url"),
    "COPYDESK_CLOUDFLARE_METADATA_URL": ("oauth", "cloudflare_metadata_url"),
    "COPYDESK_BASE_URL": ("site", "base_url"),
    "COPYDESK_SECRET_KEY": ("site", "secret_key"),
    "COPYDESK_DATA_DIR": ("site", "data_dir"),
    "COPYDESK_DEBUG": ("site", "debug"),
    "COPYDESK_DATABASE_URL": ("database", "url"),
    "COPYDESK_MAIL_BACKEND": ("mail", "backend"),
    "COPYDESK_MAIL_HOST": ("mail", "host"),
    "COPYDESK_MAIL_PORT": ("mail", "port"),
    "COPYDESK_MAIL_SECURITY": ("mail", "security"),
    "COPYDESK_MAIL_USERNAME": ("mail", "username"),
    "COPYDESK_MAIL_PASSWORD": ("mail", "password"),
    "COPYDESK_MAIL_FROM_EMAIL": ("mail", "from_email"),
    "COPYDESK_MAIL_RATE_PER_MINUTE": ("mail", "rate_per_minute"),
    "COPYDESK_UPLOADS_DIR": ("uploads", "dir"),
    "COPYDESK_UPLOADS_MAX_SIZE_MB": ("uploads", "max_size_mb"),
    "COPYDESK_UPLOADS_MAX_IMPORT_MB": ("uploads", "max_import_mb"),
    "COPYDESK_JOBS_RUN_IN_WEB": ("jobs", "run_in_web"),
    "COPYDESK_PROXY_HOPS": ("server", "proxy_hops"),
    "COPYDESK_EXTENSIONS": ("extensions", "enabled"),
    "COPYDESK_LOG_LEVEL": ("logging", "level"),
    "GOOGLE_CLIENT_ID": ("oauth", "google_client_id"),
    "GOOGLE_CLIENT_SECRET": ("oauth", "google_client_secret"),
    "MICROSOFT_CLIENT_ID": ("oauth", "microsoft_client_id"),
    "MICROSOFT_CLIENT_SECRET": ("oauth", "microsoft_client_secret"),
    "MICROSOFT_TENANT": ("oauth", "microsoft_tenant"),
    "COPYDESK_GOOGLE_CLIENT_ID": ("oauth", "google_client_id"),
    "COPYDESK_GOOGLE_CLIENT_SECRET": ("oauth", "google_client_secret"),
    "COPYDESK_GOOGLE_METADATA_URL": ("oauth", "google_metadata_url"),
    "COPYDESK_MICROSOFT_CLIENT_ID": ("oauth", "microsoft_client_id"),
    "COPYDESK_MICROSOFT_CLIENT_SECRET": ("oauth", "microsoft_client_secret"),
    "COPYDESK_MICROSOFT_METADATA_URL": ("oauth", "microsoft_metadata_url"),
    "COPYDESK_MICROSOFT_TENANT": ("oauth", "microsoft_tenant"),
}


class ConfigError(Exception):
    """The configuration is missing or invalid. The message says how to fix it."""


@dataclass
class MailConfig:
    backend: str = "console"
    host: str = "localhost"
    port: int = 587
    security: str = "starttls"
    username: str = ""
    password: str = field(default="", repr=False)
    timeout: int = 30
    from_email: str = "newsletter@localhost"
    rate_per_minute: int = 120
    file_dir: Path = Path("mail")
    connection_id: str = ""


@dataclass
class Config:
    path: Path | None
    root: Path
    base_url: str
    secret_key: str = field(repr=False)
    data_dir: Path
    database_url: str
    mail: MailConfig
    uploads_dir: Path
    max_upload_mb: int
    max_import_mb: int
    run_jobs_in_web: bool
    proxy_hops: int
    extensions: list[str]
    extensions_dir: Path
    extension_options: dict[str, dict[str, Any]]
    themes_dir: Path
    log_level: str = "INFO"
    debug: bool = False
    testing: bool = False
    raw: dict[str, Any] = field(default_factory=dict, repr=False)
    oauth_clients: dict[str, dict[str, str]] = field(default_factory=dict, repr=False)

    @property
    def is_https(self) -> bool:
        return self.base_url.startswith("https://")

    @property
    def url_prefix(self) -> str:
        """Path the site is mounted under, e.g. "/newsletter" ("" for the root)."""
        return urlsplit(self.base_url).path.rstrip("/")

    @property
    def origin(self) -> str:
        """Scheme and host of the public URL, without any path."""
        parts = urlsplit(self.base_url)
        return f"{parts.scheme}://{parts.netloc}"

    @property
    def server_name(self) -> str:
        return urlsplit(self.base_url).netloc


def find_config_file(explicit: str | os.PathLike | None = None) -> Path | None:
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise ConfigError(f"Configuration file not found: {path}")
        return path.resolve()
    env_path = os.environ.get(CONFIG_ENV)
    if env_path:
        path = Path(env_path).expanduser()
        if not path.is_file():
            raise ConfigError(f"{CONFIG_ENV} points to {path}, but that file does not exist.")
        return path.resolve()
    for candidate in DEFAULT_LOCATIONS:
        if candidate.is_file():
            return candidate.resolve()
    return None


def load_config(
    path: str | os.PathLike | None = None,
    overrides: dict[str, dict[str, Any]] | None = None,
    *,
    require_file: bool = False,
    use_environment: bool = True,
) -> Config:
    """Read the configuration file, apply environment variables, then ``overrides``."""
    file_path = find_config_file(path)
    if file_path is None and require_file:
        raise ConfigError(
            "No configuration file found. Run `quillsail init` to create one, or set "
            f"{CONFIG_ENV} to its location."
        )

    data: dict[str, Any] = {}
    if file_path is not None:
        try:
            with file_path.open("rb") as fh:
                data = tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{file_path} is not valid TOML: {exc}") from exc

    for env_name, (section, key) in ENV_OVERRIDES.items():
        if use_environment and env_name in os.environ:
            data.setdefault(section, {})[key] = os.environ[env_name]

    for section, values in (overrides or {}).items():
        if isinstance(values, dict):
            data.setdefault(section, {}).update(values)
        else:
            data[section] = values

    root = file_path.parent if file_path else Path.cwd()
    return _build(data, file_path, root)


def _build(data: dict[str, Any], file_path: Path | None, root: Path) -> Config:
    site = _section(data, "site")
    database = _section(data, "database")
    mail = _section(data, "mail")
    uploads = _section(data, "uploads")
    jobs = _section(data, "jobs")
    server = _section(data, "server")
    extensions = _section(data, "extensions")
    themes = _section(data, "themes")
    logging_ = _section(data, "logging")
    oauth = _section(data, "oauth")
    testing = _bool(data.get("testing", False), "testing")

    debug = _bool(site.get("debug", False), "site.debug")
    base_url = str(site.get("base_url", "http://localhost:5000")).strip().rstrip("/")
    parts = urlsplit(base_url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ConfigError(
            f"site.base_url must be a full URL such as https://news.example.edu (got {base_url!r})."
        )

    secret_key = str(site.get("secret_key", "")).strip()
    if not secret_key:
        if debug or testing:
            secret_key = "insecure-development-key"
        else:
            raise ConfigError(
                "site.secret_key is not set. Run `quillsail init`, or generate one with "
                "`python -c \"import secrets; print(secrets.token_hex(32))\"`."
            )
    elif len(secret_key) < 32 and not (debug or testing):
        raise ConfigError("site.secret_key is too short. Use at least 32 random characters.")

    data_dir = _path(site.get("data_dir", "data"), root)
    database_url = str(database.get("url", "")).strip() or f"sqlite:///{data_dir / 'copydesk.db'}"
    database_url = _absolute_sqlite_url(database_url, root)

    mail_cfg = MailConfig(
        backend=str(mail.get("backend", "console")).lower(),
        host=str(mail.get("host", "localhost")),
        port=_int(mail.get("port", 587), "mail.port"),
        security=str(mail.get("security", "starttls")).lower(),
        username=str(mail.get("username", "")),
        password=str(mail.get("password", "")),
        timeout=_int(mail.get("timeout", 30), "mail.timeout"),
        from_email=str(mail.get("from_email", f"newsletter@{parts.hostname or 'localhost'}")),
        rate_per_minute=_int(mail.get("rate_per_minute", 120), "mail.rate_per_minute"),
        file_dir=_path(mail.get("file_dir", data_dir / "mail"), root),
    )
    if mail_cfg.backend not in MAIL_BACKENDS:
        raise ConfigError(f"mail.backend must be one of {', '.join(MAIL_BACKENDS)}.")
    if mail_cfg.security not in MAIL_SECURITY:
        raise ConfigError(f"mail.security must be one of {', '.join(MAIL_SECURITY)}.")
    if mail_cfg.rate_per_minute < 1:
        raise ConfigError("mail.rate_per_minute must be at least 1.")

    enabled = extensions.get("enabled", [])
    if isinstance(enabled, str):
        enabled = [name.strip() for name in enabled.split(",") if name.strip()]
    extension_options = {
        name: value for name, value in extensions.items() if isinstance(value, dict)
    }

    return Config(
        path=file_path,
        root=root,
        base_url=base_url,
        secret_key=secret_key,
        data_dir=data_dir,
        database_url=database_url,
        mail=mail_cfg,
        uploads_dir=_path(uploads.get("dir", data_dir / "uploads"), root),
        max_upload_mb=_int(uploads.get("max_size_mb", 10), "uploads.max_size_mb"),
        max_import_mb=_int(uploads.get("max_import_mb", 200), "uploads.max_import_mb"),
        run_jobs_in_web=_bool(jobs.get("run_in_web", False), "jobs.run_in_web"),
        proxy_hops=_int(server.get("proxy_hops", 0), "server.proxy_hops"),
        extensions=list(enabled),
        extensions_dir=_path(extensions.get("dir", "extensions"), root),
        extension_options=extension_options,
        themes_dir=_path(themes.get("dir", "themes"), root),
        log_level=str(logging_.get("level", "INFO")).upper(),
        debug=debug,
        testing=testing,
        raw=data,
        oauth_clients={
            "cloudflare": {"client_id": str(oauth.get("cloudflare_client_id", "")),
                           "scopes": str(oauth.get("cloudflare_scopes", "")),
                           "edge_scopes": str(oauth.get("cloudflare_edge_scopes", "")),
                           "relay_url": str(oauth.get("cloudflare_relay_url", "")),
                           "metadata_url": str(oauth.get("cloudflare_metadata_url", "https://quillsail.blog/.well-known/quillsail/cloudflare.json"))},
            "gmail": {"client_id": str(oauth.get("google_client_id", "")),
                      "client_secret": str(oauth.get("google_client_secret", "")),
                      "metadata_url": str(oauth.get("google_metadata_url", "https://quillsail.blog/.well-known/quillsail/gmail.json"))},
            "outlook": {"client_id": str(oauth.get("microsoft_client_id", "")),
                        "client_secret": str(oauth.get("microsoft_client_secret", "")),
                        "tenant": str(oauth.get("microsoft_tenant", "common")),
                        "metadata_url": str(oauth.get("microsoft_metadata_url", "https://quillsail.blog/.well-known/quillsail/outlook.json"))},
        },
    )


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{name}] must be a table in the configuration file.")
    return value


def _path(value: Any, root: Path) -> Path:
    path = Path(str(value)).expanduser()
    return path if path.is_absolute() else (root / path).resolve()


def _absolute_sqlite_url(url: str, root: Path) -> str:
    """Make relative SQLite paths relative to the config file, not the working directory."""
    prefix = "sqlite:///"
    if not url.startswith(prefix) or url == "sqlite://":
        return url
    rest = url[len(prefix) :]
    if not rest or rest.startswith("/") or rest.startswith(":memory:"):
        return url
    return prefix + str((root / rest).resolve())


def _bool(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off", ""):
        return False
    raise ConfigError(f"{name} must be true or false (got {value!r}).")


def _int(value: Any, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{name} must be a whole number (got {value!r}).") from None
