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
    assert derived["piece_overrides"] == {"2": {"assembly.mono_paragraphs": False}}
    assert profiles.derive(first, {"assembly.code_union": True}, {"2": {"assembly.mono_paragraphs": False}})["id"] \
        == derived["id"]


def test_knobs_applied_are_the_values_that_differ_from_the_registry_default():
    from orm.catalogue import Profile
    from stages import bundle

    values = {"assembly.code_union": {"value": True, "source": "preset", "evidence": "preset code"},
              "assembly.mono_paragraphs": {"value": True, "source": "manual", "evidence": "derived"}}
    got = bundle.profile_view(Profile(id=1, preset="code", sha256="x", values=values, piece_overrides={}))
    assert got["knobs_applied"] == {"assembly.code_union": True}
