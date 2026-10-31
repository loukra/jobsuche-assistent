"""Which repository is this checkout - the upstream template or a fork?

Several tests guard the *pristine* upstream template: the placeholder
sentinels in `cv/main_example.tex` and `01-candidate-profile.md`, the
`[YOUR_NAME]`-style tokens in `05-cv-templates.md`/`06-cover-letter-templates.md`,
and `/reset`'s skeleton headings. A personalized fork rewrites exactly those
files via `/setup`, so the tests skip on forks. The skip used to key on
`GITHUB_REPOSITORY` alone, which only GitHub Actions sets - a fork running
its suite locally defaulted to "upstream" and failed on its own profile data
(40 red tests on 2026-10-12). The `origin` remote's slug is the local
equivalent, so it is consulted when the variable is absent; with neither
(no git, no origin) the checkout is treated as upstream, keeping the guard
in the only place where the files are supposed to be pristine.
"""
import os
import re
import subprocess
from pathlib import Path

UPSTREAM = "MadsLorentzen/ai-job-search"
REPO = Path(__file__).resolve().parent.parent

_SLUG = re.compile(r"[:/]([^/:]+/[^/]+?)(?:\.git)?/?$")


def repository_slug() -> str:
    """`owner/name` of this checkout: `GITHUB_REPOSITORY` in CI, else the
    `origin` remote; the upstream slug when neither can be determined."""
    env = os.environ.get("GITHUB_REPOSITORY")
    if env:
        return env
    try:
        proc = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return UPSTREAM
    if proc.returncode != 0:
        return UPSTREAM
    match = _SLUG.search(proc.stdout.strip())
    return match.group(1) if match else UPSTREAM


def is_upstream() -> bool:
    return repository_slug().casefold() == UPSTREAM.casefold()


FORK_SKIP_REASON = (
    f"{repository_slug()} is a fork: these files are personalized via /setup; "
    "the guard targets the pristine upstream template"
)
