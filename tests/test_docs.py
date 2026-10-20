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


def test_each_guide_has_its_pages():
    assert (ROOT / "docs" / "reference.md").exists()
    for guide in ("django", "fastapi", "flask"):
        assert {f.stem for f in (ROOT / "docs" / guide).glob("*.md")} == GUIDE, guide


def test_links_reach_files():
    for file in FILES:
        for link in re.findall(r"\]\((?!https?:|#)([^)#]+)", file.read_text()):
            assert (file.parent / link).exists(), f"{file.name} → {link}"


def test_docs_link_the_site_by_its_pages():
    for file in DOCS:
        for path in re.findall(r"\]\(https://docs\.wordplus\.cloud/([^)#]*)", file.read_text()):
            assert re.fullmatch(rf"({SECTIONS})/[a-z-]+/|img/[a-z]+/[a-z0-9-]+\.webp", path), f"{file.name} → {path}"
