"""The README and the docs (docs/: the reference at the top, a guide each for Django, FastAPI and Flask in their folders,
as docs.wordplus.cloud shows them) link only to files that are there, and to other pages of the docs, and their
illustrations, by their address on docs.wordplus.cloud."""

import pathlib
import re

ROOT = pathlib.Path(__file__).parent.parent
DOCS = [*sorted((ROOT / "docs").glob("*.md")), *sorted((ROOT / "docs").glob("*/*.md"))]
FILES = [ROOT / "README.md", *DOCS]

# A guide's pages, as docs.wordplus.cloud lists them (its scripts/sync.mjs).
GUIDE = {"getting-started", "rooms", "presence", "sending", "events", "calls", "streams", "encryption", "customizing", "deploying", "example"}
SECTIONS = "apps|wordpress|nextjs|laravel|django|fastapi|express|php|flask|mobile|ios|android|use-cases"


def test_the_docs_name_the_ready_made_parts_as_they_are_now():
    # Their names since @wordplus/realtime-ui 1.0.6 (its f919f81): the old ones do nothing on a page.
    for file in FILES:
        assert not re.search(r"--bm-|\bbm-messages-|\.bm-[a-z]", file.read_text()), file


def test_each_guide_has_its_pages():
    assert (ROOT / "docs" / "reference.md").exists()
    for guide in ("django", "fastapi", "flask"):
        assert {f.stem for f in (ROOT / "docs" / guide).glob("*.md")} == GUIDE, guide


def _section(page, heading):
    """The text of a page's `## heading` section, up to the next `## `."""
    text = (ROOT / "docs" / page).read_text()
    start = text.find(f"\n## {heading}\n")
    assert start > -1, f"{page}: ## {heading}"
    end = text.find("\n## ", start + 1)
    return text[start:] if end < 0 else text[start:end]


def test_the_guides_start_a_call_and_a_stream_by_a_token():
    # Every guide teaches one first call and one first stream: a route of the app that answers call_token() or
    # stream_token() for the signed-in user, then the element that asks it (asked on 2026-11-09: "the users application
    # provides the authorization token to client to start call so we need to make a clear that in api and examples"). A
    # rule is the other way, in a section of its own, "By a rule", after the token way, as in the Node guides.
    rules = re.compile(r"realtime\.(calls|group_calls|streams)\(")
    for guide in ("django", "fastapi", "flask"):
        call = _section(f"{guide}/calls.md", "Your first call")
        assert "realtime.call_token(" in call and "token-url=" in call and not rules.search(call), guide

        stream = _section(f"{guide}/streams.md", "Your first stream")
        assert "realtime.stream_token(" in stream and "token-url=" in stream and not rules.search(stream), guide

        who = _section(f"{guide}/calls.md", "Who may call")
        assert "realtime.group_call_token(" in who, guide
        assert "token-url=" in _section(f"{guide}/calls.md", "Group calls"), guide
        assert who.find("\n### By a rule\n") > who.find("realtime.call_token("), f"{guide}: calls, By a rule"
        assert "realtime.calls(" in who, guide

        who_is = _section(f"{guide}/streams.md", "Who is who")
        assert who_is.find("\n### By a rule\n") > who_is.find("realtime.stream_token("), f"{guide}: streams, By a rule"
        assert "realtime.streams(" in who_is, guide


def test_links_reach_files():
    for file in FILES:
        for link in re.findall(r"\]\((?!https?:|#)([^)#]+)", file.read_text()):
            assert (file.parent / link).exists(), f"{file.name} → {link}"


def test_docs_link_the_site_by_its_pages():
    for file in DOCS:
        for path in re.findall(r"\]\(https://docs\.wordplus\.cloud/([^)#]*)", file.read_text()):
            assert re.fullmatch(rf"({SECTIONS})/[a-z-]+/|img/[a-z]+/[a-z0-9-]+\.webp", path), f"{file.name} → {path}"
