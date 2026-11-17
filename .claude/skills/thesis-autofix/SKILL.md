---
name: thesis-autofix
description: Run THesisS find → fix → measure rounds on its own — find answer issues, fix the first wrong stage, measure before/after, self-review, push, then look for the next issue — without asking the user between rounds. Use for "find issues and fix them yourself", "major improvements", or under /loop for unattended work.
---

# Autonomous find → fix → measure rounds

The user gave standing permission on 2026-11-17 (CLAUDE.md «Автомат засварын гогцоо»). Do not end a round with «хийх үү?»: do the next in-scope step and report it as done.

## One round

1. **State.** `git status`, HEAD, `http://127.0.0.1:8765/` returns 200 (else `.venv/Scripts/python.exe open_demo.py --no-browser`). Read the newest «not fixed» list (latest `papers/4*-*.mn.md` §5 and the top PROJECT-NOTE entry) and the last measurement files in `runtime/eval/` — they are the baseline for HEAD.
2. **Find issues** (stop at 5–10 per round), in this order:
   - the «not fixed» list;
   - failures in W04 / W04-b / the 80-question set's **tune** split (never tune on `split=test`; read test failures only to report them);
   - new realistic probes: `tools/probe_questions.py` with a question bank in `runtime/eval/` (reception topics in `data/reception/reception-topics-user-20261112.mn.md`, staff/teacher/timetable/room wording, two-turn follow-ups, paraphrases of answered questions);
   - the web UI through Claude in Chrome when the extension is connected (`list_connected_browsers`); otherwise say it was skipped.
   Classify each: wrong value shown, unanswerable but something shown, answerable but refused, wrong referral, crash/latency.
3. **Diagnose** with `/thesis-debug` discipline: the first wrong stage — planner → retrieval → selection → typed check → reception tables → displayed text. Observations apart from hypotheses.
4. **Fix** the smallest justified change with a regression test. Sealed `content_release.CODE_FILES`: edit a scratch copy, then `tools/manage_content_release.py stage-code-upgrade → validate → publish` (CLAUDE.md «Битүүмжилсэн код»). Never edit code while a measurement is running.
5. **Measure** on the same code, data and `.venv-modeltools`, LLM off:
   `.venv/Scripts/python.exe tools/run_config_comparison.py --label <name> --file config/answer-selection.json --key typed_value_check --values true`
   plus the probe bank before/after. Rules: wrong answers stay 0; any regression is fixed or the change reverted; a gain only on the set it was tuned on is reported as such.
6. **Self-review** the diff: `/code-review high`, then `/engineering:code-review`. Fix confirmed findings, rerun focused tests (`.venv/Scripts/python.exe -m unittest tests.test_answer_types tests.test_question_planner tests.test_staff_contact` and whatever the change touches).
7. **Ship**: scan the diff for phones, e-mails other than @nmct.edu.mn, keys; never add PPTX/PDF/`МИНИЙ-ДИПЛОМ/`/runtime/DB/school data; commit, push, record the remote SHA; short PROJECT-NOTE entry (≤6 lines) + details in `papers/`; `python tools/sync_project_note.py` then `--check`.
8. **Next round** immediately, unless a stop condition holds.

## Stop and ask only when

- the fix needs a human-only fact: what an office handles, office hours, a staff name, a reviewed question set, a teacher decision (if a stand-in is used, mark it «хэрэглэгч хянаагүй» and keep going);
- an outward action: Facebook bot, publishing, e-mail;
- thesis text, title or an approved PPT slide;
- a safety limit: staff mobiles, keys, the test split, the sealed-code procedure;
- three rounds in a row with no measured gain — then report and propose a different source of issues.

## Report

CLAUDE.md «Хариултын хэлбэр»: 5–10 plain Mongolian lines (done with files, not done with reasons, corrections, the user's next step), the reading list, skills used. Measured numbers go to `papers/` and the note, not the chat, unless asked.

For unattended multi-hour work the user types `/loop /thesis-autofix`; each wake-up runs one round.
