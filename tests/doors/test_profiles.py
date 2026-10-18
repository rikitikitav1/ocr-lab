from stages.structure import collect

from tests.doors.test_runs import TEXT, _drain, engines
from tests.fixtures import build, text_page
from tests.real_db import needs_db

pytestmark = needs_db


def test_the_knob_doors_list_every_knob_and_preset_and_a_derived_profile_is_new_and_manual(client, inbox, monkeypatch):
    groups = client.get("/v1/knobs").json()["groups"]
    run_knobs = {path: spec for g in groups.values() for path, spec in g["knobs"].items() if spec["scope"] == "run"}
    assert run_knobs and all({"options", "help", "probe", "default"} <= set(spec) for spec in run_knobs.values())
    assert "default" in {p["name"] for p in client.get("/v1/presets").json()}
    pages = [text_page("One", TEXT, bookmark="One"), text_page("Two", TEXT, bookmark="Two")]
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "profiles.pdf", pages))],
                                          "then": []}).json()["id"]
    collect.collect(book)
    engines(monkeypatch)
    run = client.post(f"/v1/books/{book}/runs", json={}).json()["run"]
    _drain()
    first = client.get(f"/v1/profiles/{run['profile_id']}").json()
    assert first["id"] == run["profile_id"] and first["values"]
    knob = next(iter(run_knobs))
    other = next(o for o in run_knobs[knob]["options"] if o != first["values"][knob]["value"])
    derived = client.post(f"/v1/profiles/{first['id']}/derive", json={"set": {knob: other}})
    assert derived.status_code == 201
    made = derived.json()
    assert made["id"] != first["id"] and made["parent_id"] == first["id"] and made["sha256"] != first["sha256"]
    evidence = f"derived from profile {first['id']}"
    assert made["values"][knob] == {"value": other, "source": "manual", "evidence": evidence}
    assert client.get(f"/v1/profiles/{first['id']}").json() == first
    again = client.post(f"/v1/profiles/{first['id']}/derive", json={"set": {knob: other}}).json()
    assert again["id"] == made["id"]
    assert client.post(f"/v1/profiles/{first['id']}/derive", json={"set": {knob: "nope"}}).status_code == 400
    assert client.get("/v1/profiles/999999").status_code == 404
