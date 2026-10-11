import subprocess
from pathlib import Path

import httpx
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.stand


def test_every_image_is_used_as_is_and_never_pulled():
    config = yaml.safe_load(subprocess.run(["docker", "compose", "config"], cwd=ROOT,
                                           capture_output=True, text=True, check=True).stdout)
    pulled = [name for name, s in config["services"].items() if "image" in s and "build" not in s
              and s.get("pull_policy") != "never"]
    assert pulled == []


def test_stand_door_sees_both_converters_with_build_stamps():
    stand = httpx.get("http://localhost:8100/v1/stand", timeout=30).json()
    assert stand["db"]["ok"]
    for name in ("docling", "mineru"):
        assert stand["converters"][name]["state"] in ("free", "holds"), name
        assert stand["converters"][name]["build"], name
    assert not stand["code"]["worker_behind_disk"]
