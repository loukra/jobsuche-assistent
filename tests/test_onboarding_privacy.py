"""Guards for the onboarding privacy rules.

/setup writes personal data into tracked files (CLAUDE.md, the profile
skill files). A copy that still points at the public project could push
them by accident. These tests pin that the clone instructions remove the
remote, and that /setup checks the origin's visibility BEFORE writing
anything, not in its closing notes.
"""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
README = REPO / "README.md"
SETUP_GUIDE = REPO / "SETUP.md"
SETUP_COMMAND = REPO / ".claude" / "commands" / "setup.md"


def section(text: str, heading: str) -> str:
    """Body of a markdown section up to the next heading of the same level."""
    level = heading.split(" ")[0]
    pattern = re.compile(
        rf"^{re.escape(heading)}\n(.*?)(?=^{level} |\Z)", re.MULTILINE | re.DOTALL
    )
    match = pattern.search(text)
    return match.group(1) if match else ""


class TestCloneInstructionsCutTheRemote(unittest.TestCase):
    """The copy must be independent of the public project before /setup writes personal data."""

    def test_readme_setup_block_removes_origin(self):
        body = README.read_text(encoding="utf-8")
        self.assertIn("git remote remove origin", body)
        self.assertRegex(body, re.compile(r"persönlich|personal data", re.IGNORECASE))

    def test_setup_guide_removes_origin_next_to_the_clone_command(self):
        body = section(SETUP_GUIDE.read_text(encoding="utf-8"), "## 2. Get the project")
        self.assertIn("git clone", body, "sanity: the clone command lives in this section")
        self.assertIn("git remote remove origin", body)
        self.assertIn("personal data", body)


class TestSetupChecksOriginBeforeWriting(unittest.TestCase):
    def test_preflight_exists_and_precedes_profile_generation(self):
        text = SETUP_COMMAND.read_text(encoding="utf-8")
        self.assertIn(
            "git remote get-url origin",
            text,
            "/setup must check where the working copy would publish to",
        )
        preflight_at = text.index("git remote get-url origin")
        writes_at = text.index("## Step 3: Generate Profile Files")
        self.assertLess(
            preflight_at,
            writes_at,
            "the origin check must run before any profile file is written - the "
            "existing Step 4 note fires after everything is already on disk",
        )
        self.assertIn(
            "public",
            text[max(0, preflight_at - 2000) : preflight_at + 2000].lower(),
            "the preflight must be about public visibility, not just remote presence",
        )


if __name__ == "__main__":
    unittest.main()
