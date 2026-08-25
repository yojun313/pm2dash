import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.git_service import GitService


@unittest.skipUnless(shutil.which("git"), "Git is required")
class GitServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.remote = self.root / "remote.git"
        self.source = self.root / "source"
        self.clone = self.root / "clone"

        self._git(self.root, "init", "--bare", str(self.remote))
        self.source.mkdir()
        self._git(self.source, "init")
        self._git(self.source, "config", "user.name", "PM2Dash Test")
        self._git(self.source, "config", "user.email", "test@example.com")
        (self.source / "README.md").write_text("first\n", encoding="utf-8")
        self._git(self.source, "add", "README.md")
        self._git(self.source, "commit", "-m", "first commit")
        self._git(self.source, "branch", "-M", "main")
        self._git(self.source, "remote", "add", "origin", str(self.remote))
        self._git(self.source, "push", "-u", "origin", "main")
        self._git(self.remote, "symbolic-ref", "HEAD", "refs/heads/main")
        self._git(self.root, "clone", str(self.remote), str(self.clone))
        self._git(self.clone, "config", "user.name", "PM2Dash Test")
        self._git(self.clone, "config", "user.email", "test@example.com")

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def _git(cwd: Path, *args: str):
        subprocess.run(
            [shutil.which("git"), *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )

    def _repositories(self):
        with patch.dict(os.environ, {"GIT_REPOSITORY_ROOTS": str(self.root), "GIT_REPOSITORIES": ""}):
            return GitService.list_repositories()

    def _repository_id(self, name: str):
        return next(item["id"] for item in self._repositories() if item["name"] == name)

    def test_lists_repositories_and_returns_status_and_commits(self):
        clone_id = self._repository_id("clone")
        (self.clone / "local.txt").write_text("change\n", encoding="utf-8")

        with patch.dict(os.environ, {"GIT_REPOSITORY_ROOTS": str(self.root), "GIT_REPOSITORIES": ""}):
            detail = GitService.get_repository_detail(clone_id)

        self.assertEqual(detail["branch"], "main")
        self.assertTrue(detail["dirty"])
        self.assertEqual(detail["changes"][0]["path"], "local.txt")
        self.assertEqual(detail["commits"][0]["subject"], "first commit")
        self.assertEqual(detail["ahead"], 0)
        self.assertEqual(detail["behind"], 0)

    def test_fetch_pull_and_push_work_against_remote(self):
        clone_id = self._repository_id("clone")
        (self.source / "README.md").write_text("first\nsecond\n", encoding="utf-8")
        self._git(self.source, "add", "README.md")
        self._git(self.source, "commit", "-m", "remote update")
        self._git(self.source, "push")

        environment = {"GIT_REPOSITORY_ROOTS": str(self.root), "GIT_REPOSITORIES": ""}
        with patch.dict(os.environ, environment):
            fetch = GitService.run_action(clone_id, "fetch")
            fetched_detail = GitService.get_repository_detail(clone_id)
            pull = GitService.run_action(clone_id, "pull")

            (self.clone / "local.txt").write_text("local\n", encoding="utf-8")
            self._git(self.clone, "add", "local.txt")
            self._git(self.clone, "commit", "-m", "local update")
            push = GitService.run_action(clone_id, "push")
            final_detail = GitService.get_repository_detail(clone_id)

        self.assertTrue(fetch["success"], fetch["output"])
        self.assertEqual(fetched_detail["behind"], 1)
        self.assertTrue(pull["success"], pull["output"])
        self.assertTrue(push["success"], push["output"])
        self.assertEqual(final_detail["ahead"], 0)
        self.assertEqual(final_detail["behind"], 0)


if __name__ == "__main__":
    unittest.main()
