"""The trusted agent kit and intake files for the research repository (spec §20).

The templates are rendered with the platform repository and the exact platform
commit, so the research repository's pull-request check and dev container always
run pinned platform code. Render with::

    python -m rp.contribute.kit --out DIR --research ORG/research --platform ORG/ORG.github.io --ref SHA --site URL
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = ["FILES", "render_kit", "write_kit"]

TEMPLATES = Path(__file__).with_name("templates")
# Output path in the research repository -> template name (templates avoid dot-folders).
FILES = {
    "AGENTS.md": "AGENTS.md",
    "CLAUDE.md": "CLAUDE.md",
    "CONTRIBUTING.md": "CONTRIBUTING.md",
    ".gemini/settings.json": "gemini-settings.json",
    ".devcontainer/devcontainer.json": "devcontainer.json",
    ".github/ISSUE_TEMPLATE/attempt.yml": "issue-attempt.yml",
    ".github/ISSUE_TEMPLATE/review.yml": "issue-review.yml",
    ".github/ISSUE_TEMPLATE/problem.yml": "issue-problem.yml",
    ".github/ISSUE_TEMPLATE/config.yml": "issue-config.yml",
    ".github/PULL_REQUEST_TEMPLATE.md": "pull-request-template.md",
    ".github/workflows/check.yml": "check.yml",
}
# Rendered only once the owner has approved the intake App (operations/intake-app.md).
INTAKE_FILES = {".github/workflows/intake.yml": "intake-caller.yml"}
_REPO = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+")
_PLACEHOLDER = re.compile(r"\{\{[A-Z_]+\}\}")


def render_kit(*, research: str, platform: str, ref: str, site_url: str, intake_app_id: int | None = None) -> dict[str, bytes]:
    if not (_REPO.fullmatch(research) and _REPO.fullmatch(platform)):
        raise ValueError("repositories must be OWNER/NAME")
    if not re.fullmatch(r"[0-9a-f]{40}", ref):
        raise ValueError("the platform ref must be a full commit SHA")
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+/", site_url):
        raise ValueError("the site URL must be https://host/ with a trailing slash")
    values = {"RESEARCH_REPO": research, "PLATFORM_REPO": platform, "PLATFORM_REF": ref, "SITE_URL": site_url}
    files = dict(FILES)
    if intake_app_id is not None:
        if intake_app_id <= 0:
            raise ValueError("the intake App ID must be a positive number")
        values["INTAKE_APP_ID"] = str(intake_app_id)
        files.update(INTAKE_FILES)
    rendered = {}
    for out, name in files.items():
        text = (TEMPLATES / name).read_text(encoding="utf-8")
        for key, value in values.items():
            text = text.replace("{{" + key + "}}", value)
        leftover = _PLACEHOLDER.search(text)
        if leftover:
            raise ValueError(f"{name}: unknown placeholder {leftover.group(0)}")
        rendered[out] = text.encode("utf-8")
    return rendered


def write_kit(out: Path, files: dict[str, bytes]) -> list[Path]:
    written = []
    for rel, data in files.items():
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        written.append(path)
    return written
