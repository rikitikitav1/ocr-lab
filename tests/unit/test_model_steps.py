import model_steps


def test_the_first_object_is_read_through_prose_fences_and_trailing_braces():
    assert model_steps.parse_json('Here:\n```json\n{"entries": [{"title": "One"}]}\n```\nNote {see above}') == {
        "entries": [{"title": "One"}]}


def test_a_broken_answer_reads_as_empty_instead_of_failing_the_job():
    assert model_steps.parse_json('{"entries": [{"title": "One",') == {}
    assert model_steps.parse_json("no json here") == {}
    assert model_steps.parse_json("[1, 2]") == {}
