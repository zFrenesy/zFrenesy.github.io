from pathlib import Path

import pytest

from rp.site.checks import SiteCheckError, validate_site


def write(root: Path, name: str, content: str | bytes) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode() if isinstance(content, str) else content)


@pytest.fixture
def site(tmp_path):
    write(tmp_path, "assets/site.css", "body { color: black }")
    write(tmp_path, "assets/site.js", "'use strict';")
    write(tmp_path, "index.html", '<h1 id="home">Home</h1>')
    return tmp_path


def test_valid_routes_queries_anchors_and_source_download(site):
    write(site, "index.html", '<a href="/problems/P1/?sort=new#proof">Problem</a>')
    write(site, "problems/P1/index.html", '<h2 id="proof">Proof</h2><a href="../../#home">Home</a>'
          '<a href="source%20file.tex?download=1">Source</a>')
    write(site, "problems/P1/source file.tex", "\\begin{proof}Source\\end{proof}")
    # The ID map is built before any links are resolved, including forward links.
    write(site, "index.html", (site / "index.html").read_text() + '<h1 id="home">Home</h1>')
    report = validate_site(site)
    assert report["html_pages"] == 2
    assert report["files"] == 5
    assert report["errors"] == []
    assert report["total_bytes"] == sum(path.stat().st_size for path in site.rglob("*") if path.is_file())


def test_project_pages_base_path(site):
    write(site, "index.html", '<a href="/research/proof#théorème">Proof</a><script src="/research/assets/site.js"></script>')
    write(site, "proof/index.html", '<h2 id="théorème">Theorem</h2><a href="../">Home</a>')
    assert validate_site(site, base_path="/research/")["html_pages"] == 2
    write(site, "index.html", '<a href="/proof/">Wrong prefix</a>')
    with pytest.raises(SiteCheckError, match="outside configured base_path"):
        validate_site(site, base_path="/research")


@pytest.mark.parametrize("link, message", [
    ('<a href="missing/">Missing</a>', "missing internal target"),
    ('<a href="#missing">Missing</a>', "missing anchor"),
    ('<script src="assets/absent.js"></script>', "missing internal target"),
    ('<a href="../secret">Escape</a>', "path traversal outside site"),
    ('<a href="%2e%2e/secret">Escape</a>', "path traversal outside site"),
    ('<a href="%5csecret">Escape</a>', "unsafe path"),
    ('<a href="javaScript:alert(1)">Bad</a>', "unsafe link scheme"),
    ('<base href="/elsewhere/">', "base elements"),
])
def test_invalid_internal_references(site, link, message):
    write(site, "index.html", link)
    with pytest.raises(SiteCheckError, match=message) as exc:
        validate_site(site)
    assert "index.html" in exc.value.errors[0]
    assert exc.value.report["html_pages"] == 1


@pytest.mark.parametrize("markup", [
    '<script src="https://cdn.example.com/library.js"></script>',
    '<script src="//cdn.example.com/library.js"></script>',
    '<script data-mathjax-src="https://cdn.example.com/tex-chtml.js"></script>',
    '<img src="https://example.com/image.png">',
    '<link rel="stylesheet" href="https://fonts.example.com/style.css">',
    '<link rel="preconnect" href="https://example.com">',
    '<img srcset="small.png 1x, https://example.com/image.png 2x">',
    '<img srcset="small.png\t1x, https://example.com/image.png 2x">',
    '<source srcset="small.png,https://example.com/image.png">',
    '<video poster="https://example.com/poster.png"></video>',
    '<object data="https://example.com/embed"></object>',
    '<iframe srcdoc="&lt;img src=&quot;https://example.com/x&quot;&gt;"></iframe>',
    '<a href="https://example.com" ping="https://tracker.example.com">Link</a>',
    '<meta http-equiv="refresh" content="0; url=https://example.com">',
    '<style>@import "https://example.com/a.css";</style>',
    '<p style="background: url(//example.com/a.png)">Text</p>',
])
def test_external_subresources_are_rejected(site, markup):
    write(site, "small.png", b"image")
    write(site, "index.html", markup)
    with pytest.raises(SiteCheckError, match="external subresource"):
        validate_site(site)


def test_external_navigation_and_release_downloads_are_allowed(site):
    write(site, "index.html", '<a href="https://example.com/release/package.zip">ZIP</a>'
          '<a href="https://example.com/paper.pdf#page=4">PDF</a>'
          '<a href="mailto:example@example.com">Mail</a>'
          '<link rel="canonical" href="https://we-solve.github.io/">'
          '<img src="data:image/png;base64,YQ==">')
    assert not validate_site(site)["errors"]


def test_css_nested_dependencies_and_svg_anchors(site):
    write(site, "assets/site.css", '@import "theme.css"; .a { background: url(../icon.svg#mark) }')
    write(site, "assets/theme.css", '@font-face { src: url("fonts/test.woff2?#version") }')
    write(site, "assets/fonts/test.woff2", b"font")
    write(site, "icon.svg", '<svg xmlns="http://www.w3.org/2000/svg"><g id="mark"/></svg>')
    write(site, "index.html", '<link rel="stylesheet" href="assets/site.css">')
    assert not validate_site(site)["errors"]
    write(site, "assets/theme.css", '/* url(https://example.com/comment) */ @font-face { src: url(missing.woff2) }')
    with pytest.raises(SiteCheckError, match="missing internal target") as exc:
        validate_site(site)
    assert not any("external subresource" in error for error in exc.value.errors)


@pytest.mark.parametrize("css", [
    '@import url("https://example.com/a.css");',
    '@font-face { src: url(//example.com/font.woff2); }',
    r'.a { background: u\72l(\68ttps://example.com/image.png); }',
])
def test_external_css_resources_and_escaped_urls(site, css):
    write(site, "assets/site.css", css)
    with pytest.raises(SiteCheckError, match="external subresource"):
        validate_site(site)


def test_duplicate_html_ids_fail(site):
    write(site, "index.html", '<h1 id="same">One</h1><h2 id="same">Two</h2>')
    with pytest.raises(SiteCheckError, match="duplicate id 'same'"):
        validate_site(site)


def test_missing_mandatory_shared_asset(site):
    (site / "assets/site.js").unlink()
    with pytest.raises(SiteCheckError, match="missing mandatory self-hosted asset: assets/site.js"):
        validate_site(site)


@pytest.mark.parametrize("attribute", ["src", "data-mathjax-src"])
def test_mathjax_assets_are_validated_but_excluded_from_payload(site, attribute):
    markup = f'<script {attribute}="assets/vendor/mathjax-3.2.2/es5/tex-mml-chtml.js"></script>'
    write(site, "index.html", markup)
    with pytest.raises(SiteCheckError, match="missing internal target"):
        validate_site(site)
    write(site, "assets/vendor/mathjax-3.2.2/es5/tex-mml-chtml.js", b"x" * 300_000)
    assert validate_site(site, payload_limit=len(markup))["max_initial_payload_bytes"] == len(markup)


def test_initial_payload_counts_unique_transitive_assets_and_utf8(site):
    markup = '<link rel="stylesheet" href="assets/site.css"><script src="assets/site.js"></script><p>α</p>'
    css = '@import "theme.css"; @font-face { src: url(font.woff2); }'
    theme = '@font-face { src: url(font.woff2); } @import "site.css";'
    write(site, "index.html", markup)
    write(site, "assets/site.css", css)
    write(site, "assets/theme.css", theme)
    write(site, "assets/font.woff2", b"x" * 200)
    expected = sum(len(s.encode()) for s in (markup, css, theme, "'use strict';")) + 200
    report = validate_site(site, payload_limit=expected)
    assert report["max_initial_payload_bytes"] == expected
    with pytest.raises(SiteCheckError, match="initial first-party payload"):
        validate_site(site, payload_limit=expected - 1)


def test_document_payload_exclusion_is_local_and_preserves_validation(site):
    prefix = '<main><div class="tex-content" data-payload-exclude>'
    suffix = '</div><footer>ordinary</footer></main>'
    content = '<div data-payload-exclude>' + "α" * 100_000 + '</div><img src="figure.png">'
    write(site, "index.html", prefix + content + suffix)
    write(site, "figure.png", b"x" * 250_000)
    expected = len((prefix + suffix).encode())
    assert validate_site(site, payload_limit=expected)["max_initial_payload_bytes"] == expected
    write(site, "index.html", prefix + '<img src="https://example.com/a.png">' + suffix)
    with pytest.raises(SiteCheckError, match="external subresource"):
        validate_site(site)


def test_unclosed_exclusion_cannot_hide_page_payload(site):
    write(site, "index.html", '<div data-payload-exclude>unfinished')
    with pytest.raises(SiteCheckError, match="unclosed data-payload-exclude"):
        validate_site(site)


def test_redirect_target_has_its_own_payload_budget(site):
    redirect = '<meta http-equiv="refresh" content="0; url=/manuscript/">'
    write(site, "index.html", redirect)
    write(site, "manuscript/index.html", '<div data-payload-exclude>' + "x" * 300_000 + '</div>')
    assert validate_site(site, payload_limit=100)["max_initial_payload_bytes"] == len(redirect)


@pytest.mark.parametrize("filename", ["downloads/package.zip", "paper.PDF"])
def test_packages_do_not_belong_on_pages(site, filename):
    write(site, filename, b"artifact")
    with pytest.raises(SiteCheckError, match="Release assets"):
        validate_site(site)


def test_total_output_limit_fails_at_boundary(site):
    total = sum(path.stat().st_size for path in site.rglob("*") if path.is_file())
    assert validate_site(site, site_limit=total + 1)["total_bytes"] == total
    with pytest.raises(SiteCheckError, match="must be under"):
        validate_site(site, site_limit=total)


def test_symlinks_are_rejected(site):
    (site / "symlink.js").symlink_to(site / "assets/site.js")
    with pytest.raises(SiteCheckError, match="symlinks are not allowed"):
        validate_site(site)


def test_missing_output_and_no_html_fail(tmp_path):
    with pytest.raises(SiteCheckError, match="does not exist"):
        validate_site(tmp_path / "absent")
    with pytest.raises(SiteCheckError, match="no HTML pages"):
        validate_site(tmp_path)
