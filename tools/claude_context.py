"""Read-only handoff inventory. No network, model calls, secret reads or services."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig")), None
    except (OSError, ValueError) as exc:
        return None, type(exc).__name__


def git(root: Path, *args: str):
    executable = shutil.which("git")
    if not executable:
        return {"available": False, "error": "git_not_found"}
    try:
        result = subprocess.run(
            [executable, "-C", str(root), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=12, check=False,
        )
        if result.returncode:
            # Git stderr can contain local paths; do not copy it into a shared report.
            return {"available": False, "exit_code": result.returncode}
        return {"available": True, "value": result.stdout.strip()}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "error": type(exc).__name__}


def snapshot(root: Path):
    progress, progress_error = read_json(root / "config/project-progress.json")
    progress = progress if isinstance(progress, dict) else {}
    project_note = progress.get("project_note", {})
    if not isinstance(project_note, dict):
        project_note = {}
    paths = [
        "runtime/gemini-real-use-20261030/completion-checkpoint.json",
        "runtime/ii-evaluation-20261030/completion-checkpoint.json",
        "runtime/stt-candidate-20261030/completion-checkpoint.json",
        "runtime/content.db", "CORE/database/website.db", "models",
        "models/multilingual-e5-small", "models/faster-whisper-small-mn-cafet",
        "runtime/school-handbook-20261028/ТСА гарын авлага.pdf",
        "CORE/THESIS-START.mn.md",
        "papers/10-thesis-decisions-review-45-20261029.mn.md",
    ]
    tracked = git(root, "ls-files", "--", *paths)
    tracked_paths = set(tracked.get("value", "").splitlines()) if tracked.get("available") else None
    inventory = []
    for name in paths:
        path = root / name
        entry = {"path": name, "exists_locally": path.exists()}
        if tracked_paths is not None:
            entry["tracked_by_git"] = name in tracked_paths or any(
                value.startswith(name + "/") for value in tracked_paths
            )
        inventory.append(entry)
    checkpoints = []
    safe_fields = (
        "updated_utc", "status", "goal_complete", "thesis_section_II_complete",
        "engineering_pack_complete", "active_workstream", "actual_google_audio_posts",
        "old_15_budget_reused", "per_clip_scores_public", "remaining_human_judgments",
        "next_single_step", "outstanding_automatic_work",
    )
    for name in paths[:3]:
        data, error = read_json(root / name)
        item = {"path": name, "readable": isinstance(data, dict)}
        if isinstance(data, dict):
            item["recorded_state"] = {key: data[key] for key in safe_fields if key in data}
        else:
            item["error"] = error
        checkpoints.append(item)
    hashes = {}
    for name in (
        "AGENTS.md", "CLAUDE.md", "CORE/PROJECT-NOTE.mn.md",
        "config/project-progress.json", "gemini_live_transport.py",
        "demo_server.py", "rag_runtime.py", "voice_runtime.py",
    ):
        try:
            hashes[name] = hashlib.sha256((root / name).read_bytes()).hexdigest()
        except OSError:
            hashes[name] = None
    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "local_read_only_inventory_not_live_verification_or_human_evaluation",
        "git": {
            "head": git(root, "rev-parse", "HEAD"),
            "branch": git(root, "branch", "--show-current"),
            "working_changes": git(root, "status", "--short", "--untracked-files=normal"),
            "cached_upstream_ref_not_fresh_remote": git(root, "rev-parse", "@{u}"),
        },
        "recorded_current_focus": {
            key: project_note[key] for key in ("active_workstream", "current_focus")
            if key in project_note
        },
        "progress_read_error": progress_error,
        "local_inventory": inventory,
        "checkpoints": checkpoints,
        "source_sha256": hashes,
        "new_model_calls": 0, "new_training": 0, "new_human_results": 0,
        "limitations": [
            "Existence is not content validation or proof of consent.",
            "Historical recorded state is not a fresh test or a current server status.",
            "No fresh remote request, credentials, raw transcripts or audio were read.",
            "Cached upstream refs may be stale; verify GitHub separately when needed.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(snapshot(args.root.resolve()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
