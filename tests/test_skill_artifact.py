from __future__ import annotations

import re
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPOSITORY_ROOT / "skills" / "post-queue-cli"


class SkillArtifactTests(unittest.TestCase):
    def test_readme_installs_from_public_repository(self) -> None:
        contents = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn(
            "npx skills add denis-spirin/post-queue-cli "
            "--skill post-queue-cli --global",
            contents,
        )
        self.assertNotIn("/path/to/post-queue-cli", contents)
        self.assertNotIn("Install this checkout", contents)
        self.assertNotIn("## Development", contents)
        self.assertNotIn("uv run", contents)
        self.assertNotIn("skills add .", contents)
        self.assertNotIn("tests", contents)
        self.assertNotIn("references/", contents)
        self.assertNotIn("skills/post-queue-cli", contents)

    def test_frontmatter_uses_exact_public_name_and_activation_terms(self) -> None:
        contents = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        match = re.match(r"\A---\n(?P<frontmatter>.*?)\n---\n", contents, re.DOTALL)

        self.assertIsNotNone(match, "SKILL.md must start with YAML frontmatter")
        frontmatter = match.group("frontmatter") if match else ""
        self.assertIn("name: post-queue-cli", frontmatter)
        self.assertRegex(frontmatter, r"(?m)^description: .+")
        self.assertIn("Post Queue", frontmatter)
        self.assertIn("posts", frontmatter)
        self.assertIn("queues", frontmatter)
        self.assertIn("connected accounts", frontmatter)
        self.assertIn("queue items", frontmatter)
        self.assertIn("compatibility: Requires Python 3.11+", frontmatter)

    def test_runtime_files_are_inside_selected_skill(self) -> None:
        self.assertTrue((SKILL_ROOT / "scripts" / "post_queue.py").is_file())
        self.assertTrue((SKILL_ROOT / "references" / "ENV.md").is_file())
        self.assertFalse((SKILL_ROOT / "references" / "API.md").exists())

    def test_installed_skill_has_only_runtime_files(self) -> None:
        files = {
            path.relative_to(SKILL_ROOT).as_posix()
            for path in SKILL_ROOT.rglob("*")
            if path.is_file()
        }
        self.assertEqual(
            files,
            {".env.example", "SKILL.md", "references/ENV.md", "scripts/post_queue.py"},
        )

    def test_skill_uses_commands_instead_of_raw_payloads(self) -> None:
        contents = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        environment = (SKILL_ROOT / "references" / "ENV.md").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("--input", contents)
        self.assertNotIn("API.md", contents)
        self.assertNotIn("POST_QUEUE_SKILL_DIR", contents)
        self.assertNotIn("POST_QUEUE_SKILL_DIR", environment)
        self.assertNotIn("configure", environment)
        self.assertNotIn("POST_QUEUE_BASE_URL", environment)
        self.assertNotIn("localhost", environment)
        self.assertNotIn("127.0.0.1", environment)
        self.assertIn("cp .env.example .env", environment)
        self.assertNotIn("—", contents)
        self.assertNotIn("–", contents)

    def test_skill_tree_excludes_repository_only_files_and_caches(self) -> None:
        installed_paths = [
            path.relative_to(SKILL_ROOT) for path in SKILL_ROOT.rglob("*")
        ]

        self.assertFalse(any("tests" in path.parts for path in installed_paths))
        self.assertFalse(any("docs" in path.parts for path in installed_paths))
        self.assertFalse(any("__pycache__" in path.parts for path in installed_paths))
        self.assertFalse(any(path.suffix == ".pyc" for path in installed_paths))
        self.assertFalse(
            any(path.name == "INSTALL_SENTINEL.txt" for path in installed_paths)
        )

    def test_skill_lists_every_supported_command(self) -> None:
        contents = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        commands = (
            "account list",
            "media upload FILE",
            "post create",
            "post list",
            "post get GROUP_ID",
            "post update GROUP_ID",
            "post delete GROUP_ID",
            "queue create",
            "queue list",
            "queue get QUEUE_ID",
            "queue update QUEUE_ID",
            "queue delete QUEUE_ID",
            "queue-item add QUEUE_ID",
            "queue-item update QUEUE_ID ITEM_ID",
            "queue-item delete QUEUE_ID ITEM_ID",
        )

        for command in commands:
            self.assertIn(
                f"python3 scripts/post_queue.py {command}",
                contents,
                f"SKILL.md is missing {command}",
            )

    def test_test_sentinel_is_repository_root_only(self) -> None:
        sentinel = REPOSITORY_ROOT / "tests" / "INSTALL_SENTINEL.txt"

        self.assertEqual(
            sentinel.read_text(encoding="utf-8").strip(),
            "REPOSITORY_TESTS_MUST_NOT_BE_INSTALLED",
        )


if __name__ == "__main__":
    unittest.main()
