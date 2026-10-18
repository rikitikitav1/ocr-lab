import job_specs
import profiles
import pytest
from assembly import passes
from knobs import registry
from orm.db import Session
from stages import intake

from tests.fixtures import build, text_page
from tests.real_db import needs_db


def test_every_assembly_pass_is_a_run_knob_whose_default_is_one_of_its_options():
    knobs = registry.run_knobs()
    assert {registry.RUN_PREFIX + name for name in passes.conf()} == set(knobs)
    assert all(spec["default"] in spec["options"] and spec["help"] and spec["probe"] for spec in knobs.values())


def test_book_knobs_are_listed_in_their_own_group():
    assert "structure.contents_pages" in registry.registry()["groups"]["book"]["knobs"]


def test_an_unknown_knob_or_option_is_refused():
    with pytest.raises(job_specs.Refused):
        registry.check({"assembly.no_such_pass": True})
    with pytest.raises(job_specs.Refused):
        registry.check({"assembly.tables_by": "guess"})


def test_a_chapter_override_wins_over_the_profile_for_that_chapter_only():
    values = {"assembly.code_union": {"value": False, "source": "preset", "evidence": "registry default"}}
    overrides = {"3": {"assembly.code_union": True}}
    assert profiles.passes_for(values, overrides, 3) == {"code_union": True}
    assert profiles.passes_for(values, overrides, 4) == {"code_union": False}


@needs_db
def test_the_default_profile_is_one_per_book_and_a_derived_one_records_the_manual_source(stand, tmp_path):
    book, _ = intake.register([(build(tmp_path / "a.pdf", [text_page("Body")]), "a.pdf")])
    with Session() as session:
        first, again = profiles.resolve(session, book).id, profiles.resolve(session, book).id
        session.commit()
    assert first == again
    derived = profiles.derive(first, {"assembly.code_union": True}, {"2": {"assembly.mono_paragraphs": False}})
    assert derived["parent_id"] == first and derived["values"]["assembly.code_union"]["source"] == "manual"
    assert derived["piece_overrides"] == {"2": {"assembly.mono_paragraphs": {
        "value": False, "source": "manual", "evidence": f"derived from profile {first}"}}}
    assert profiles.passes_for({}, derived["piece_overrides"], 2) == {"mono_paragraphs": False}
    assert profiles.passes_for({}, {"2": {"assembly.mono_paragraphs": False}}, 2) == {"mono_paragraphs": False}
    assert profiles.derive(first, {"assembly.code_union": True}, {"2": {"assembly.mono_paragraphs": False}})["id"] \
        == derived["id"]


def test_knobs_applied_are_the_values_that_differ_from_the_registry_default():
    from orm.catalogue import Profile
    from stages import bundle

    values = {"assembly.code_union": {"value": True, "source": "preset", "evidence": "preset code"},
              "assembly.mono_paragraphs": {"value": False, "source": "manual", "evidence": "derived"}}
    got = bundle.profile_view(Profile(id=1, preset="code", sha256="x", values=values, piece_overrides={}))
    assert got["knobs_applied"] == {"assembly.code_union": True}
    assert got["knob_sources"] == {"assembly.code_union": "preset"}
    line = bundle._profile_line({"profile": {**got, "piece_overrides": {"10": {}, "2": {}}}})
    assert line == "assembly.code_union (preset) / 2, 10"


def test_a_knob_no_pass_reads_or_without_help_fails_the_start_and_is_named(monkeypatch):
    from knobs import registry

    assert registry.validate()["groups"]
    bad = {"tables": {"question": "q", "knobs": {
        "tables_from": {"options": ["mineru"], "help": "", "probe": "p", "cost": "cpu"},
        "nothing_reads_me": {"options": [True], "help": "h", "probe": "p", "cost": "cpu"}}}}
    monkeypatch.setattr(registry, "_groups", lambda: bad)
    with pytest.raises(ValueError) as error:
        registry.validate()
    assert "tables.tables_from: no help" in str(error.value)
    assert "tables.nothing_reads_me: no pass reads it" in str(error.value)


@needs_db
def test_a_book_set_in_a_monospace_face_starts_on_the_technical_preset_unless_its_knob_says_otherwise(stand, tmp_path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from stages.layout import collect as layout
    from use_cases import books

    path = tmp_path / "code.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    for _ in range(6):
        c.setFont("Helvetica", 10)
        c.drawString(72, 780, "Every listing in this book is set in a monospace face below the prose")
        c.setFont("Courier", 10)
        for k in range(4):
            c.drawString(72, 750 - 16 * k, f"for (int i = 0; i < count; i++) total += values[{k}];")
        c.showPage()
    c.save()
    book, _ = intake.register([(path, "code.pdf")])
    layout.collect_page(book, force=True)
    assert profiles.chosen_preset(book)[0] == "technical"
    with Session() as session:
        values = profiles.resolve(session, book).values
        session.commit()
    assert values["assembly.code_from_layer"]["value"] is True and values["assembly.mono_paragraphs"]["value"]
    books.set_book_knobs(book, set={"run.preset": "default"})
    assert profiles.chosen_preset(book) == ("default", "book knob run.preset")
    with pytest.raises(job_specs.Refused):
        books.set_book_knobs(book, set={"run.preset": "code"})


def test_the_layer_code_passes_are_off_by_default_and_on_in_technical():
    defaults = {path: spec["default"] for path, spec in registry.run_knobs().items()}
    technical = registry.preset("technical")
    assert defaults["assembly.code_from_layer"] is False and defaults["assembly.mono_paragraphs"] is False
    assert technical["values"] == {"assembly.code_from_layer": True, "assembly.mono_paragraphs": True}
    assert defaults["assembly.join_code_across_pages"] is True
