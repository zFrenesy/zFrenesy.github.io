import pytest

from rp.validation.links import LinkReport, check_external_links, host_problem, verify_pins

SHA = "a" * 40
OTHER = "b" * 40


def record(*externals, **text):
    artifacts = [{"role": "code", "location": "external_pinned", "external": e} for e in externals]
    return {"title": text.get("title", "T"), "artifacts": artifacts, "claim": {"scope_statement": text.get("scope", "S")}}


def gh(url, pin=SHA, kind="git_commit"):
    return {"url": url, "pin": {"kind": kind, "value": pin}}


@pytest.mark.parametrize("external", [
    gh(f"https://github.com/owner/repo/tree/{SHA}"),
    gh(f"https://github.com/owner/repo/blob/{SHA}/src/Main.lean"),
    gh(f"https://huggingface.co/owner/model/tree/{SHA}", kind="hf_revision"),
    gh(f"https://huggingface.co/datasets/owner/data/blob/{SHA}/x.csv", kind="hf_revision"),
    gh("https://zenodo.org/records/1234567", pin="10.5281/zenodo.1234567", kind="zenodo_doi"),
    gh("https://doi.org/10.5281/zenodo.1234567", pin="10.5281/zenodo.1234567", kind="zenodo_doi"),
    gh(f"https://archive.softwareheritage.org/swh:1:dir:{SHA};origin=https://github.com/o/r", pin=f"swh:1:dir:{SHA}", kind="swhid"),
])
def test_pinned_artifacts_pass(external):
    report = check_external_links(record(external))
    assert report.ok, [str(i) for i in report.issues]
    assert len(report.artifacts) == 1


@pytest.mark.parametrize("external, message", [
    (gh("https://github.com/owner/repo/tree/main"), "exact GitHub revision"),
    (gh("https://github.com/owner/repo/releases/latest"), "exact GitHub revision"),
    (gh(f"https://github.com/owner/repo/tree/{OTHER}"), "does not match"),
    (gh(f"https://github.com/owner/repo/tree/{SHA}?x=1"), "exact GitHub revision"),
    (gh(f"https://gitlab.com/owner/repo/-/tree/{SHA}"), "not on an allowed artifact host"),
    (gh(f"https://huggingface.co/owner/model/tree/{SHA}"), "pinned with hf_revision"),
    (gh("https://zenodo.org/records/1234567", pin="10.5281/zenodo.7654321", kind="zenodo_doi"), "does not match"),
    (gh(f"https://user:pw@github.com/owner/repo/tree/{SHA}"), "plain HTTPS"),
    (gh(f"https://github.com:8443/owner/repo/tree/{SHA}"), "plain HTTPS"),
])
def test_unpinned_or_disallowed_artifacts_fail(external, message):
    report = check_external_links(record(external))
    assert not report.ok and any(message in i.message for i in report.errors), [str(i) for i in report.issues]


@pytest.mark.parametrize("url, message", [
    ("http://arxiv.org/abs/1234.5678", "HTTPS"),
    ("https://bit.ly/3abc", "shortener"),
    ("https://www.tinyurl.com/x", "shortener"),
    ("https://192.168.1.10/paper.pdf", "raw IP"),
    ("https://[::1]/paper.pdf", "raw IP"),
    ("https://user@example.org/", "user names"),
    ("https://аррӏе.com/", "imitate Latin"),
    ("https://раураl.com/", "mixes alphabets"),
    ("https://xn--80ak6aa92e.com/", "imitate Latin"),
    ("https://gооgle.com/", "mixes alphabets"),
    ("https://xn--ggle-55da.com/", "mixes alphabets"),
])
def test_reference_links_in_text_are_checked(url, message):
    report = check_external_links(record(), {"files/attempt.md": f"See [the paper]({url}) for details.".encode()})
    assert not report.ok and any(message in i.message for i in report.errors), [str(i) for i in report.issues]


@pytest.mark.parametrize("text", [
    "[click](javascript:alert(1))",
    "\\href{data:text/html;base64,AAAA}{x}",
    '<a href="vbscript:x">x</a>',
])
def test_script_schemes_are_rejected(text):
    report = check_external_links(record(), {"files/attempt.md": text.encode()})
    assert any("scheme" in i.message for i in report.errors)


def test_record_text_and_acceptable_links():
    report = check_external_links(record(scope="See javascript:alert(1)"))
    assert not report.ok
    ok = check_external_links(record(), {
        "files/attempt.tex": b"\\url{https://arxiv.org/abs/2101.00001}, https://doi.org/10.1000/xyz123. https://m\xc3\xbcnchen.de/x https://\xd0\xbc\xd0\xbe\xd1\x81\xd0\xba\xd0\xb2\xd0\xb0.\xd1\x80\xd1\x84/",
        "files/data.csv": b"http://ignored-in-data.example",
    })
    assert ok.ok, [str(i) for i in ok.issues]
    assert "https://arxiv.org/abs/2101.00001" in ok.references and "https://doi.org/10.1000/xyz123" in ok.references


def test_host_problem_accepts_plain_and_single_script_names():
    assert host_problem("example.org") is None
    assert host_problem("xn--mnchen-3ya.de") is None  # münchen.de
    assert host_problem("10.0.0.1") == "links to a raw IP address"


class FakeHttp:
    def __init__(self, responses):
        self.responses, self.calls = responses, []

    def get_json(self, url):
        self.calls.append(url)
        result = self.responses.get(url)
        if isinstance(result, Exception):
            raise result
        return result if result is not None else (404, None)


def test_verify_pins_via_the_apis_only():
    externals = [
        gh(f"https://github.com/owner/repo/tree/{SHA}"),
        gh(f"https://github.com/owner/gone/tree/{SHA}"),
        gh(f"https://huggingface.co/owner/model/tree/{SHA}", kind="hf_revision"),
        gh("https://zenodo.org/records/1", pin="10.5281/zenodo.1", kind="zenodo_doi"),
    ]
    report = check_external_links(record(*externals))
    http = FakeHttp({
        f"https://api.github.com/repos/owner/repo/commits/{SHA}": (200, {}),
        f"https://huggingface.co/api/models/owner/model/revision/{SHA}": (200, {
            "siblings": [{"rfilename": "pytorch_model.bin"}, {"rfilename": "modeling_x.py"}, {"rfilename": "model.safetensors"}],
            "config": {"auto_map": {"AutoModel": "modeling_x.X"}}}),
    })
    verify_pins(report, http)
    assert report.verified == {externals[0]["url"]: "available", externals[1]["url"]: "unavailable",
                               externals[2]["url"]: "available", externals[3]["url"]: "not_checked"}
    assert any("pinned commit was not found" in i.message for i in report.errors)
    warnings = " ".join(i.message for i in report.warnings)
    assert "pickle-format" in warnings and "pytorch_model.bin" in warnings and "remote code" in warnings
    assert all(u.startswith(("https://api.github.com/", "https://huggingface.co/api/")) for u in http.calls)
    assert any("not examined" in n for n in report.notes)


def test_network_failure_leaves_pins_unverified_not_failed():
    report = check_external_links(record(gh(f"https://github.com/owner/repo/tree/{SHA}")))
    verify_pins(report, FakeHttp({f"https://api.github.com/repos/owner/repo/commits/{SHA}": OSError("timeout")}))
    assert report.ok and set(report.verified.values()) == {"unverified"}
    assert "not evidence of a problem" in report.warnings[0].message


def test_bounded_http_refuses_other_hosts():
    from rp.validation.links import BoundedHttp

    with pytest.raises(OSError):
        BoundedHttp().get_json("https://example.org/api")
    with pytest.raises(OSError):
        BoundedHttp().get_json("http://api.github.com/repos/a/b")
    assert isinstance(LinkReport().ok, bool)
