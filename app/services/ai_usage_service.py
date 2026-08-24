import json
import os
import shutil
import threading
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class AIUsageService:
    """Claude Code와 Codex의 로컬 세션 기록을 안전하게 집계합니다."""

    _cache: dict[tuple[int, str, str], tuple[float, dict[str, Any]]] = {}
    _cache_lock = threading.Lock()
    _cache_ttl_seconds = 30
    _max_files_per_provider = 500

    @classmethod
    def get_usage(cls, days: int = 7) -> dict[str, Any]:
        days = max(1, min(days, 30))
        claude_root = cls._data_root("CLAUDE_DATA_DIR", ".claude")
        codex_root = cls._data_root("CODEX_DATA_DIR", ".codex")
        cache_key = (days, str(claude_root), str(codex_root))

        with cls._cache_lock:
            cached = cls._cache.get(cache_key)
            if cached and time.monotonic() - cached[0] < cls._cache_ttl_seconds:
                return cached[1]

        now = datetime.now().astimezone()
        dates = [(now.date() - timedelta(days=offset)) for offset in range(days - 1, -1, -1)]
        cutoff = datetime.combine(dates[0], datetime.min.time(), tzinfo=now.tzinfo)

        claude = cls._collect_claude(claude_root, cutoff, dates)
        codex = cls._collect_codex(codex_root, cutoff, dates)
        result = {
            "generated_at": now.isoformat(),
            "window_days": days,
            "providers": [claude, codex],
        }

        with cls._cache_lock:
            cls._cache[cache_key] = (time.monotonic(), result)
        return result

    @staticmethod
    def _data_root(env_name: str, default_dir: str) -> Path:
        configured = os.getenv(env_name)
        return Path(configured).expanduser() if configured else Path.home() / default_dir

    @classmethod
    def _collect_claude(
        cls, root: Path, cutoff: datetime, dates: list[Any]
    ) -> dict[str, Any]:
        files = cls._recent_jsonl_files(root / "projects", cutoff)
        summary = cls._empty_summary(
            provider_id="claude",
            name="Claude Code",
            accent="#d97757",
            command="claude",
            root=root,
            auth_files=[root / ".credentials.json", root / "credentials.json"],
            env_keys=["ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"],
            files=files,
            dates=dates,
        )
        model_counts: Counter[str] = Counter()
        sessions: set[str] = set()

        for path in files:
            fallback_time = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).astimezone()
            file_had_usage = False
            file_session_ids: set[str] = set()
            for record in cls._read_jsonl(path):
                message = record.get("message")
                if not isinstance(message, dict) or message.get("role") != "assistant":
                    continue
                usage = message.get("usage")
                if not isinstance(usage, dict):
                    continue

                input_tokens = cls._as_int(usage.get("input_tokens"))
                output_tokens = cls._as_int(usage.get("output_tokens"))
                cache_tokens = cls._as_int(usage.get("cache_creation_input_tokens")) + cls._as_int(
                    usage.get("cache_read_input_tokens")
                )
                total_tokens = input_tokens + output_tokens + cache_tokens
                if total_tokens <= 0:
                    continue

                timestamp = cls._parse_timestamp(record.get("timestamp"), fallback_time)
                cls._add_usage(
                    summary,
                    timestamp,
                    input_tokens,
                    output_tokens,
                    cache_tokens,
                    total_tokens,
                )
                summary["requests"] += 1
                file_had_usage = True

                model = message.get("model")
                if isinstance(model, str) and model:
                    model_counts[model] += 1
                session_id = record.get("sessionId") or record.get("session_id")
                if isinstance(session_id, str) and session_id:
                    file_session_ids.add(session_id)

            if file_had_usage:
                sessions.update(file_session_ids or {str(path)})

        summary["sessions"] = len(sessions)
        summary["model"] = model_counts.most_common(1)[0][0] if model_counts else None
        return cls._finalize_summary(summary)

    @classmethod
    def _collect_codex(
        cls, root: Path, cutoff: datetime, dates: list[Any]
    ) -> dict[str, Any]:
        files = cls._recent_jsonl_files(root / "sessions", cutoff)
        summary = cls._empty_summary(
            provider_id="codex",
            name="Codex",
            accent="#10a37f",
            command="codex",
            root=root,
            auth_files=[root / "auth.json"],
            env_keys=["OPENAI_API_KEY"],
            files=files,
            dates=dates,
        )
        model_counts: Counter[str] = Counter()
        sessions: set[str] = set()

        for path in files:
            fallback_time = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).astimezone()
            previous_total: dict[str, int] | None = None
            file_had_usage = False
            session_id: str | None = None

            for record in cls._read_jsonl(path):
                payload = record.get("payload")
                if not isinstance(payload, dict):
                    continue

                record_type = record.get("type")
                payload_type = payload.get("type")
                if record_type == "session_meta":
                    candidate = payload.get("id")
                    if isinstance(candidate, str) and candidate:
                        session_id = candidate
                    continue
                if record_type == "turn_context":
                    model = payload.get("model")
                    if isinstance(model, str) and model:
                        model_counts[model] += 1
                    continue
                if record_type != "event_msg" or payload_type != "token_count":
                    continue

                info = payload.get("info")
                if not isinstance(info, dict):
                    continue
                current_total = info.get("total_token_usage")
                if not isinstance(current_total, dict):
                    continue

                normalized = {
                    "input": cls._as_int(current_total.get("input_tokens")),
                    "output": cls._as_int(current_total.get("output_tokens")),
                    "cache": cls._as_int(current_total.get("cached_input_tokens")),
                    "total": cls._as_int(current_total.get("total_tokens")),
                }
                if normalized["total"] <= 0:
                    normalized["total"] = normalized["input"] + normalized["output"]

                if previous_total is None or normalized["total"] < previous_total["total"]:
                    delta = normalized
                else:
                    delta = {
                        key: max(normalized[key] - previous_total[key], 0)
                        for key in normalized
                    }
                previous_total = normalized

                if delta["total"] <= 0:
                    continue
                timestamp = cls._parse_timestamp(record.get("timestamp"), fallback_time)
                cls._add_usage(
                    summary,
                    timestamp,
                    delta["input"],
                    delta["output"],
                    delta["cache"],
                    delta["total"],
                )
                summary["requests"] += 1
                file_had_usage = True

            if file_had_usage:
                sessions.add(session_id or str(path))

        summary["sessions"] = len(sessions)
        summary["model"] = model_counts.most_common(1)[0][0] if model_counts else None
        return cls._finalize_summary(summary)

    @classmethod
    def _empty_summary(
        cls,
        *,
        provider_id: str,
        name: str,
        accent: str,
        command: str,
        root: Path,
        auth_files: list[Path],
        env_keys: list[str],
        files: list[Path],
        dates: list[Any],
    ) -> dict[str, Any]:
        command_path = shutil.which(command)
        authenticated = any(path.is_file() for path in auth_files) or any(
            bool(os.getenv(key)) for key in env_keys
        )
        installed = command_path is not None
        connected = authenticated or (installed and bool(files))
        return {
            "id": provider_id,
            "name": name,
            "accent": accent,
            "connected": connected,
            "installed": installed,
            "has_data": bool(files),
            "status": "connected" if connected else "not_connected",
            "source": "local_session_logs",
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_tokens": 0,
            "total_tokens": 0,
            "requests": 0,
            "sessions": 0,
            "model": None,
            "last_activity": None,
            "daily": {
                day.isoformat(): {
                    "date": day.isoformat(),
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_tokens": 0,
                    "total_tokens": 0,
                }
                for day in dates
            },
        }

    @staticmethod
    def _finalize_summary(summary: dict[str, Any]) -> dict[str, Any]:
        summary["has_data"] = summary["total_tokens"] > 0
        summary["daily"] = list(summary["daily"].values())
        return summary

    @staticmethod
    def _add_usage(
        summary: dict[str, Any],
        timestamp: datetime,
        input_tokens: int,
        output_tokens: int,
        cache_tokens: int,
        total_tokens: int,
    ) -> None:
        day_key = timestamp.astimezone().date().isoformat()
        bucket = summary["daily"].get(day_key)
        if bucket is None:
            return

        for key, value in (
            ("input_tokens", input_tokens),
            ("output_tokens", output_tokens),
            ("cache_tokens", cache_tokens),
            ("total_tokens", total_tokens),
        ):
            summary[key] += value
            bucket[key] += value

        current_last = summary["last_activity"]
        if current_last is None or timestamp.isoformat() > current_last:
            summary["last_activity"] = timestamp.isoformat()

    @classmethod
    def _recent_jsonl_files(cls, root: Path, cutoff: datetime) -> list[Path]:
        if not root.is_dir():
            return []

        cutoff_timestamp = cutoff.timestamp()
        candidates: list[tuple[float, Path]] = []
        try:
            for path in root.rglob("*.jsonl"):
                try:
                    modified = path.stat().st_mtime
                except OSError:
                    continue
                if modified >= cutoff_timestamp:
                    candidates.append((modified, path))
        except OSError:
            return []

        candidates.sort(key=lambda item: item[0], reverse=True)
        return [path for _, path in candidates[: cls._max_files_per_provider]]

    @staticmethod
    def _read_jsonl(path: Path):
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    try:
                        record = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if isinstance(record, dict):
                        yield record
        except OSError:
            return

    @staticmethod
    def _parse_timestamp(value: Any, fallback: datetime) -> datetime:
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(value, tz=timezone.utc).astimezone()
            except (OverflowError, OSError, ValueError):
                return fallback
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
            except ValueError:
                return fallback
        return fallback

    @staticmethod
    def _as_int(value: Any) -> int:
        try:
            return max(int(value or 0), 0)
        except (TypeError, ValueError):
            return 0
