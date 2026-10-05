import threading

import pdf

from tests.fixtures import build, text_page


def test_parallel_reads_do_not_corrupt_each_other(tmp_path):
    paths = [build(tmp_path / f"{i}.pdf", [text_page(f"Page {i}")] * 30) for i in range(4)]
    errors = []

    def read(path):
        try:
            for _ in range(5):
                assert len(pdf.page_texts(path)) == 30
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=read, args=(p,)) for p in paths]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


def test_cp1251_read_as_latin1_is_repaired():
    assert pdf.repair("Áîãäàí Êîâàëü÷óê\nЁжик") == "Богдан Ковальчук\nЁжик"
    assert pdf.repair("Café déjà vu") == "Café déjà vu"
