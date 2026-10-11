import net
from engines import converter


def test_a_dead_supervisor_reads_as_down_and_a_silent_one_as_unknown(monkeypatch):
    def down(url, **kw):
        raise net.SourceDown("converter-docling", "ConnectError: refused")

    def silent(url, **kw):
        raise net.SourceDown("converter-docling", "ReadTimeout: timed out")

    monkeypatch.setattr(net, "get", down)
    assert converter.reading("docling")[0] == converter.DOWN
    monkeypatch.setattr(net, "get", silent)
    assert converter.reading("docling")[0] == converter.UNKNOWN


def test_a_reading_carries_the_build_asked_after_it_and_a_changed_build_fails_it(monkeypatch):
    import pytest
    from engines import converter, converter_tools

    reader = converter_tools.stamped("mineru", lambda path, fields, a, b, ceiling: {"status": "success"})
    monkeypatch.setattr(converter, "build", lambda name: {"base": "new"})
    assert reader("x.pdf", [], 1, 2, 60, build={"base": "new"}) == {"status": "success", "build": {"base": "new"}}
    changed = reader("x.pdf", [], 1, 2, 60, build={"base": "old"})
    assert changed["status"] == "failure" and "build changed" in changed["errors"][0]

    def unstamped(name):
        raise converter.WillNotStart(f"{name}: the supervisor reports no build stamp")

    monkeypatch.setattr(converter, "build", unstamped)
    with pytest.raises(converter.WillNotStart):
        reader("x.pdf", [], 1, 2, 60)
