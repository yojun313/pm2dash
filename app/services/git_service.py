import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class GitRepository:
    id: str
    name: str
    path: Path


class GitService:
    """Read and operate only on repositories discovered from configured roots."""

    COMMAND_TIMEOUT_SECONDS = 120

    @classmethod
    def _git_path(cls) -> str | None:
        return shutil.which("git")

    @classmethod
    def _run(
        cls,
        repository: Path,
        *args: str,
        timeout: int | None = None,
        check: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        git_path = cls._git_path()
        if not git_path:
            raise RuntimeError("Git 실행 파일을 찾을 수 없습니다.")

        environment = os.environ.copy()
        environment["GIT_TERMINAL_PROMPT"] = "0"
        environment["GIT_OPTIONAL_LOCKS"] = "0" if args and args[0] in {"status", "log", "branch", "for-each-ref"} else "1"
        result = subprocess.run(
            [git_path, *args],
            cwd=repository,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout or cls.COMMAND_TIMEOUT_SECONDS,
            env=environment,
            check=False,
        )
        if check and result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout).strip() or "Git 명령이 실패했습니다.")
        return result

    @staticmethod
    def _configured_paths(variable: str) -> list[Path]:
        value = os.getenv(variable, "").strip()
        if not value:
            return []
        return [Path(item).expanduser() for item in value.split(os.pathsep) if item.strip()]

    @classmethod
    def _candidate_paths(cls) -> list[Path]:
        explicit = cls._configured_paths("GIT_REPOSITORIES")
        roots = cls._configured_paths("GIT_REPOSITORY_ROOTS")
        if not explicit and not roots:
            # PM2Dash와 같은 상위 폴더에 있는 저장소를 기본으로 찾습니다.
            roots = [Path.cwd().parent]

        candidates = list(explicit)
        for root in roots:
            try:
                resolved_root = root.resolve()
                candidates.append(resolved_root)
                candidates.extend(path for path in resolved_root.iterdir() if path.is_dir())
            except (OSError, RuntimeError):
                continue
        return candidates

    @classmethod
    def list_repositories(cls) -> list[dict]:
        if not cls._git_path():
            return []

        repositories: list[GitRepository] = []
        seen: set[Path] = set()
        for candidate in cls._candidate_paths():
            try:
                path = candidate.resolve()
                if path in seen or not path.is_dir():
                    continue
                result = cls._run(path, "rev-parse", "--show-toplevel", timeout=10)
                if result.returncode != 0:
                    continue
                top_level = Path(result.stdout.strip()).resolve()
                if top_level in seen:
                    continue
                seen.add(top_level)
                repository_id = hashlib.sha256(str(top_level).encode("utf-8")).hexdigest()[:16]
                repositories.append(GitRepository(repository_id, top_level.name, top_level))
            except (OSError, RuntimeError, subprocess.SubprocessError):
                continue

        repositories.sort(key=lambda repository: repository.name.casefold())
        return [
            {"id": repository.id, "name": repository.name, "path": str(repository.path)}
            for repository in repositories
        ]

    @classmethod
    def _get_repository(cls, repository_id: str) -> GitRepository:
        for item in cls.list_repositories():
            if item["id"] == repository_id:
                return GitRepository(item["id"], item["name"], Path(item["path"]))
        raise KeyError("등록되지 않은 Git 저장소입니다.")

    @classmethod
    def _text(cls, repository: Path, *args: str, default: str = "") -> str:
        result = cls._run(repository, *args, timeout=20)
        return result.stdout.strip() if result.returncode == 0 else default

    @classmethod
    def get_repository_detail(cls, repository_id: str) -> dict:
        repository = cls._get_repository(repository_id)
        path = repository.path

        branch = cls._text(path, "branch", "--show-current")
        head = cls._text(path, "rev-parse", "--short", "HEAD", default="—")
        if not branch:
            branch = f"detached@{head}"

        status_lines = cls._text(path, "status", "--porcelain=v1").splitlines()
        changes = []
        status_names = {
            "M": "수정됨",
            "A": "추가됨",
            "D": "삭제됨",
            "R": "이름 변경",
            "C": "복사됨",
            "U": "충돌",
            "?": "추적 안 됨",
            "!": "무시됨",
        }
        for line in status_lines:
            if len(line) < 3:
                continue
            index_state, worktree_state = line[0], line[1]
            code = worktree_state if worktree_state not in {" ", "?"} else index_state
            if line[:2] == "??":
                code = "?"
            changes.append(
                {
                    "code": line[:2],
                    "state": status_names.get(code, "변경됨"),
                    "path": line[3:],
                    "staged": index_state not in {" ", "?"},
                }
            )

        ahead = behind = 0
        upstream = cls._text(path, "rev-parse", "--abbrev-ref", "@{upstream}")
        if upstream:
            counts = cls._text(path, "rev-list", "--left-right", "--count", f"HEAD...{upstream}").split()
            if len(counts) == 2:
                ahead, behind = (int(value) for value in counts)

        commit_rows = cls._text(
            path,
            "log",
            "-50",
            "--date=iso-strict",
            "--pretty=format:%H%x1f%h%x1f%s%x1f%an%x1f%aI",
        ).splitlines()
        commits = []
        for row in commit_rows:
            parts = row.split("\x1f", 4)
            if len(parts) == 5:
                commits.append(
                    {
                        "hash": parts[0],
                        "short_hash": parts[1],
                        "subject": parts[2],
                        "author": parts[3],
                        "date": parts[4],
                    }
                )

        branch_rows = cls._text(
            path,
            "for-each-ref",
            "--sort=refname",
            "--format=%(refname:short)%09%(objectname:short)%09%(upstream:short)",
            "refs/heads",
            "refs/remotes",
        ).splitlines()
        branches = []
        for row in branch_rows:
            parts = row.split("\t")
            if len(parts) >= 2 and not parts[0].endswith("/HEAD"):
                branches.append(
                    {
                        "name": parts[0],
                        "hash": parts[1],
                        "upstream": parts[2] if len(parts) > 2 else "",
                        "current": parts[0] == branch,
                        "remote": parts[0].startswith("origin/"),
                    }
                )

        remote_url = cls._text(path, "config", "--get", "remote.origin.url")
        return {
            "id": repository.id,
            "name": repository.name,
            "path": str(path),
            "branch": branch,
            "head": head,
            "remote": remote_url,
            "upstream": upstream,
            "ahead": ahead,
            "behind": behind,
            "dirty": bool(changes),
            "changes": changes,
            "commits": commits,
            "branches": branches,
        }

    @classmethod
    def run_action(cls, repository_id: str, action: str, rebase: bool = False) -> dict:
        repository = cls._get_repository(repository_id)
        allowed_actions = {"fetch", "pull", "push"}
        if action not in allowed_actions:
            raise ValueError("지원하지 않는 Git 작업입니다.")

        if action == "fetch":
            args = ["fetch", "--all", "--prune"]
        elif action == "pull":
            args = ["pull", "--rebase" if rebase else "--no-rebase"]
        else:
            branch = cls._text(repository.path, "branch", "--show-current")
            if not branch:
                raise ValueError("detached HEAD 상태에서는 Push할 수 없습니다.")
            upstream = cls._text(repository.path, "rev-parse", "--abbrev-ref", "@{upstream}")
            origin = cls._text(repository.path, "remote", "get-url", "origin")
            args = ["push"] if upstream else ["push", "--set-upstream", "origin", branch]
            if not upstream and not origin:
                raise ValueError("Push할 origin 원격 저장소가 없습니다.")

        started_at = datetime.now(timezone.utc).isoformat()
        try:
            result = cls._run(repository.path, *args)
            stdout = result.stdout.strip()
            stderr = result.stderr.strip()
            output = "\n".join(part for part in (stdout, stderr) if part)
            return {
                "success": result.returncode == 0,
                "action": action,
                "command": "git " + " ".join(args),
                "output": output or ("완료되었습니다." if result.returncode == 0 else "명령이 실패했습니다."),
                "return_code": result.returncode,
                "started_at": started_at,
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "action": action,
                "command": "git " + " ".join(args),
                "output": f"{cls.COMMAND_TIMEOUT_SECONDS}초 안에 작업이 끝나지 않아 중단했습니다.",
                "return_code": -1,
                "started_at": started_at,
            }
