import hashlib

import settings


# a hash of every python file under app/, so a row says which code ran it
def tree_hash() -> str:
    digest = hashlib.sha256()
    for path in sorted(settings.APP_DIR.rglob("*.py")):
        digest.update(str(path.relative_to(settings.APP_DIR)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


LOADED = tree_hash()


def differs_from_disk() -> bool:
    return tree_hash() != LOADED
