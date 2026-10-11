import httpx
import net
import pytest


class _Flaky:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), 0

    def request(self, method, url, **kwargs):
        self.calls += 1
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(answer, request=httpx.Request(method, url))


# the shared table is tested on a scratch database below; here the process-local fallback only
@pytest.fixture
def local(monkeypatch):
    monkeypatch.setattr(net.time, "sleep", lambda s: None)
    monkeypatch.setattr(net, "_db_rows", lambda: None)
    monkeypatch.setattr(net, "_db_write", lambda *a: None)
    monkeypatch.setattr(net, "_db_clear", lambda *a: None)
    net.reset()
    yield
    net.reset()


def test_a_flaky_answer_is_retried_until_it_works(local):
    client = _Flaky([403, httpx.ConnectError("boom"), 200])
    assert net.request("GET", "https://www.litres.ru/x", client=client).status_code == 200
    assert client.calls == 3 and net.inactive() == {}


def test_a_host_failing_every_retry_is_set_aside_and_skipped(local):
    client = _Flaky([503, 503, 503, 503])
    with pytest.raises(net.SourceDown):
        net.request("GET", "https://www.litres.ru/x", client=client)
    assert client.calls == 4 and "litres.ru" in net.inactive()
    with pytest.raises(net.SourceDown):
        net.request("GET", "https://www.litres.ru/y", client=_Flaky([]))


def test_not_found_is_an_answer_not_a_failure(local):
    client = _Flaky([404])
    assert net.request("GET", "https://openlibrary.org/x", client=client).status_code == 404
    assert client.calls == 1


def test_the_stands_own_services_are_never_set_aside(local):
    with pytest.raises(net.SourceDown):
        net.request("GET", "http://converter-docling:5001/supervisor", client=_Flaky([503] * 4))
    assert net.inactive() == {}


def test_a_host_set_aside_in_one_process_is_seen_by_another(stand, monkeypatch):
    monkeypatch.setattr(net.time, "sleep", lambda s: None)
    with pytest.raises(net.SourceDown):
        net.request("GET", "https://www.litres.ru/x", client=_Flaky([503] * 4))
    net._inactive.clear()
    assert "litres.ru" in net.inactive()
    net.reset()
    assert net.inactive() == {}


def test_an_sdk_call_through_the_transport_is_retried_and_set_aside(local):
    seen = []

    def answer(request):
        seen.append(request.url.host)
        return httpx.Response(503 if len(seen) < 3 else 200, json={})

    with httpx.Client(transport=net.Transport(httpx.MockTransport(answer))) as client:
        assert client.post("https://api.provider.test/v1/chat/completions", json={}).status_code == 200
    assert len(seen) == 3 and net.inactive() == {}

    with httpx.Client(transport=net.Transport(httpx.MockTransport(lambda r: httpx.Response(429)))) as client:
        with pytest.raises(net.SourceDown):
            client.post("https://api.provider.test/v1/chat/completions", json={})
    assert "api.provider.test" in net.inactive()


def test_a_read_timeout_is_not_sent_again(local):
    client = _Flaky([httpx.ReadTimeout("slow"), 200])
    with pytest.raises(net.SourceDown, match="ReadTimeout"):
        net.request("GET", "https://www.litres.ru/x", client=client)
    assert client.calls == 1
