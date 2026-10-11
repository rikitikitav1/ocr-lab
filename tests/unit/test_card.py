from types import SimpleNamespace

import httpx
import job_queue
import pytest
from engines import card
from use_cases import stand


def test_the_card_is_taken_only_on_the_gpu_lane(monkeypatch):
    monkeypatch.setattr(card, "_hand_to", lambda target: None)
    token = job_queue.running_lane.set("cpu")
    try:
        with pytest.raises(card.WrongLane):
            card.hand_to("mineru")
    finally:
        job_queue.running_lane.reset(token)
    token = job_queue.running_lane.set("gpu")
    try:
        card.hand_to("mineru")
    finally:
        job_queue.running_lane.reset(token)


def test_a_call_outside_any_lane_never_takes_the_card(monkeypatch):
    monkeypatch.setattr(card, "_hand_to", lambda target: None)
    with pytest.raises(card.WrongLane):
        card.hand_to("mineru")


def test_ollama_models_carry_their_card_memory(monkeypatch):
    body = {"models": [{"name": "qwen", "size_vram": 3 * 2**30}]}
    monkeypatch.setattr(card.net, "get",
                        lambda url, **kw: httpx.Response(200, json=body, request=httpx.Request("GET", url)))
    assert card.ollama_models() == [{"name": "qwen", "vram_mb": 3072}]
    assert card._ollama_loaded() == ["qwen"]


def test_the_stand_says_why_it_cannot_see_the_card(monkeypatch):
    monkeypatch.setattr(card, "ollama_models", lambda: [])
    monkeypatch.setattr(stand.shutil, "which", lambda name: None)
    assert stand._gpu_memory() == {"ollama_models": [], "card": None, "card_unseen_because": stand.NO_SMI}


def test_the_stand_reads_the_card_from_nvidia_smi(monkeypatch):
    monkeypatch.setattr(card, "ollama_models", lambda: [])
    monkeypatch.setattr(stand.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    answers = {"--query-gpu=memory.used,memory.total": "5120, 24576\n",
               "--query-compute-apps=pid,process_name,used_memory": "41, python, 4800\n"}
    monkeypatch.setattr(stand.subprocess, "run", lambda args, **kw: SimpleNamespace(stdout=answers[args[1]]))
    assert stand._gpu_memory()["card"] == {"used_mb": 5120, "total_mb": 24576,
                                           "processes": [{"pid": 41, "name": "python", "used_mb": 4800}]}
