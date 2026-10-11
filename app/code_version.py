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
DOORS = ("pdf.py", "text_clean.py", "models_client.py", "engines/converter_tools.py")


def files_hash(app_files: list[Path], config_files: tuple[str, ...] = ()):
    digest = hashlib.sha256()
    for path in [*app_files, *(settings.APP_DIR / d for d in DOORS)]:
        digest.update(path.read_bytes())
    for name in config_files:
        digest.update((settings.CONFIG_DIR / name).read_bytes())
    return digest


def differs_from_disk() -> bool:
    return tree_hash(SOURCE_DIR) != LOADED


# the API and the worker share the data volume, so a file there is how a reload is asked for
def _reload_flag() -> Path:
    return settings.DATA_DIR / "worker_reload"


def request_reload() -> None:
    _reload_flag().parent.mkdir(parents=True, exist_ok=True)
    _reload_flag().touch()


def reload_requested() -> bool:
    return _reload_flag().exists()


def clear_reload() -> None:
    _reload_flag().unlink(missing_ok=True)
