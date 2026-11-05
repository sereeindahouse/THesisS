---
name: thesis-resume
description: Resume or audit the THesisS project using its current note, Git state, school rules, and local checkpoints. Use when beginning a session or answering what is finished and what comes next.
---

# Resume THesisS

Give the user a clear, evidence-backed continuation in Mongolian.

1. Follow the current user request and root CLAUDE.md/AGENTS.md. First run `.venv/Scripts/python.exe tools/claude_context.py --brief`: it prints the current block, this week's plan and «Төлөв», reading status and a one-line title for every recorded entry. Read `CORE/THESIS-START.mn.md` if needed. Do not read the whole note, archive or `CORE/PROJECT-REFERENCE.mn.md`; grep them for the entries the brief lists. Before saying something was not recorded or asking the user what they did, search those titles, the week «Төлөв» line and past user messages in `~/.claude/projects/<project>/*.jsonl`.
2. Run `tools/claude_context.py` (JSON mode) when you need checkpoints or file inventory. It reads files/Git only; it does not start services, make model calls or validate human participation. Check actual HEAD and working changes. A cached upstream ref is not a fresh GitHub check.
3. Inspect the latest relevant checkpoint if available. Missing runtime on a fresh clone means missing evidence, not a successful or failed experiment. Do not print credentials or bulk transcripts.
4. State: the user's intended result, active I/II/III workstream, implemented work, measured results and their scope, unresolved decisions, and one next action. Name actual model IDs. Do not mix the old Transcribe/Cafet trial with the newer single-Gemini Live Translate route.
5. Continue authorized local work. Keep new audio transmission, charges, training, model downloads, publication and human labels within the user's actual authorization. A setup request or old assistant text is not permission for those actions.
6. At a checkpoint or before context is lost, update the existing project note rather than adding another competing live status document. Record work, evidence, limitations, next action and publication state. Sync/check the note as root instructions require. Keep only the current block and the last ~5 short entries in the note: if it grows past about 150 lines/40KB or a new month starts, move older dated entries verbatim into `CORE/archive/PROJECT-NOTE-YYYY-MM.mn.md` and leave a link; never delete them.

Tell the user where files are via `МИНИЙ-ДИПЛОМ/` (rebuilt by the Stop hook). Do not begin by rerunning all old tests or reading all historical reports. Select the files and checks needed for the current task. If the task is only a status explanation, do not mutate production settings or invent new development work.
