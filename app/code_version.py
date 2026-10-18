import hashlib
import os
from pathlib import Path

import settings

# the worker runs from a copy of app/ and config/; SOURCE_DIR is the tree it was copied from
SOURCE_DIR = Path(os.getenv("SOURCE_DIR", settings.APP_DIR.parent))


# every python file under app/ and every config file, so a row says which code and settings ran it
def tree_hash(root: Path = settings.APP_DIR.parent) -> str:
    digest = hashlib.sha256()
    for path in sorted([*(root / "app").rglob("*.py"), *(root / "config").rglob("*.yaml")]):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


LOADED = tree_hash()

# the modules every text passes through on its way in; a stage's output depends on them as on its own code
DOORS = ("pdf.py", "text_layer.py", "text_clean.py", "models_client.py", "engines/converter_tools.py")


def files_hash(app_files: list[Path], config_files: tuple[str, ...] = ()):
    digest = hashlib.sha256()
    for path in [*app_files, *(settings.APP_DIR / d for d in DOORS)]:
        digest.update(path.read_bytes())
    for name in config_files:
        digest.update((settings.CONFIG_DIR / name).read_bytes())
    return digest


# the code on disk a worker would load next, the one question every door and the worker ask of it
def on_disk() -> str:
    return tree_hash(SOURCE_DIR)


def differs_from_disk() -> bool:
    return on_disk() != LOADED


# the live workers running other code than the source on disk, by host; the stand and its reload door both ask this
def behind(live: dict[str, dict], disk: str | None = None) -> list[str]:
    disk = disk or on_disk()
    return sorted(h for h, w in live.items() if w["code"] != disk)


# the API and the worker share the data volume, so a file there is how a reload is asked for
def _reloads() -> Path:
    return settings.DATA_DIR / "worker_reloads"


def _reload_flag(host: str) -> Path:
    return _reloads() / host


# a flag a host, each worker clearing its own; flags of hosts no longer alive go
def request_reload(hosts: list[str], alive: set[str] | None = None) -> None:
    _reloads().mkdir(parents=True, exist_ok=True)
    for old in _reloads().iterdir():
        if alive is not None and old.name not in alive:
            old.unlink(missing_ok=True)
    for host in hosts:
        _reload_flag(host).touch()


def reload_requested(host: str) -> bool:
    return _reload_flag(host).is_file()


def clear_reload(host: str) -> None:
    _reload_flag(host).unlink(missing_ok=True)
