

def test_each_character_of_a_spaceless_script_is_a_word_and_other_text_reads_as_before():
    import re

    from assembly import referee

    assert referee.WORD.findall("学习汉语 hello 日本語テスト 한국어") == [
        "学", "习", "汉", "语", "hello", "日", "本", "語", "テ", "ス", "ト", "한", "국", "어"]
    text = "Hello, world 42 snake_case Привет, мир"
    assert referee.WORD.findall(text) == re.findall(r"\w+", text)
