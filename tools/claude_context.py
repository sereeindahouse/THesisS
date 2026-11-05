"""Read-only handoff inventory. No network, model calls, secret reads or services."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
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


WEEK_HEADING = re.compile(r"^### (W\d+) · (\d{4})\.(\d\d)\.(\d\d)–(\d\d)\.(\d\d)")
ENTRY_HEADING = re.compile(r"^(?:\*\*(\d\d\.\d\d[^*]{0,160})\*\*|#{2,3} (2026\.\d\d\.\d\d[^\n]{0,160}))")
NOTE_FILES = ("CORE/PROJECT-NOTE.mn.md", "CORE/archive/PROJECT-NOTE-2026-11.mn.md")


def _text(root: Path, name: str):
    try:
        return (root / name).read_text(encoding="utf-8-sig")
    except OSError:
        return ""


def current_block(note: str):
    start, end = "<!-- project-state:start -->", "<!-- project-state:end -->"
    if start not in note or end not in note:
        return ""
    return note.split(start, 1)[1].split(end, 1)[0].strip()


def week_section(plan: str, today: date):
    """Return (this week's section, next week's heading) from the weekly plan."""
    lines = plan.splitlines()
    for index, line in enumerate(lines):
        match = WEEK_HEADING.match(line)
        if not match:
            continue
        year, month, day, end_month, end_day = (int(value) for value in match.groups()[1:])
        start = date(year, month, day)
        end = date(year + (end_month < month), end_month, end_day)
        if start <= today <= end:
            body = [line]
            following = ""
            for later in lines[index + 1:]:
                if later.startswith("### "):
                    following = later
                    break
                body.append(later)
            return "\n".join(body).strip(), following
    return "", ""


def reading_rows(plan: str):
    rows, inside = [], False
    for line in plan.splitlines():
        if "Унших дараалал ба төлөв" in line:
            inside = True
            continue
        if inside and line.startswith("|") and not line.startswith("|---"):
            cells = [re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", cell).strip() for cell in line.strip("|").split("|")]
            if cells and cells[0] != "7 хоног":
                rows.append(f"{cells[0]} · {cells[1][:70]} · {cells[-1]}")
        elif inside and rows and not line.startswith("|"):
            break
    return rows


def entry_index(root: Path):
    found = []
    for name in NOTE_FILES:
        for line in _text(root, name).splitlines():
            match = ENTRY_HEADING.match(line)
            if match:
                title = (match.group(1) or match.group(2)).strip()
                found.append(f"{Path(name).name}: {title[:110]}")
    return found


def brief(root: Path, today: date | None = None):
    """One-screen digest so a new session knows everything recorded without reading every note."""
    today = today or date.today()
    plan = _text(root, "CORE/WEEKLY-PLAN-2026-2027.mn.md")
    week, following = week_section(plan, today)
    status = git(root, "status", "--short")
    head = git(root, "log", "-1", "--format=%h %s")
    folder = root / "МИНИЙ-ДИПЛОМ"
    parts = [
        f"# THesisS товчоо — {today.isoformat()}",
        f"Git: {head.get('value', '?')} · өөрчлөлт: {len(status.get('value', '').splitlines())} файл",
        "", "## Одоогийн бүртгэл (PROJECT-NOTE)", current_block(_text(root, "CORE/PROJECT-NOTE.mn.md")),
        "", "## Энэ долоо хоног (WEEKLY-PLAN)", week or "(олдсонгүй)",
        f"Дараагийнх: {following}" if following else "",
        "", "## Унших төлөв (✅ = хэрэглэгч өөрөө хэлсэн)", *reading_rows(plan),
        "", "## Бүх бүртгэлийн гарчиг (дэлгэрэнгүйг grep-ээр хай)", *entry_index(root),
        "", "## Хэрэглэгчийн нэг хавтас",
        f"{folder.name}/00_ЭНДЭЭС_ЭХЭЛ.md" if (folder / "00_ЭНДЭЭС_ЭХЭЛ.md").is_file()
        else "алга — python tools/build_my_thesis_folder.py",
        "", "Лавлагаа: CORE/THESIS-START.mn.md (хэрэглэгчийн 1 хуудас), CORE/PROJECT-REFERENCE.mn.md (тогтвортой мэдээлэл).",
    ]
    return "\n".join(part for part in parts if part is not None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--brief", action="store_true", help="One-screen Mongolian digest for resuming.")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.brief:
        print(brief(args.root.resolve()))
        return
    print(json.dumps(snapshot(args.root.resolve()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
