---
name: thesis-resume
description: Resume or audit the THesisS project using its current note, Git state, school rules, and local checkpoints. Use when beginning a session or answering what is finished and what comes next.
---

# Resume THesisS

Give the user a clear, evidence-backed continuation in Mongolian.

1. Follow the current user request and root CLAUDE.md/AGENTS.md. Read `CORE/CLAUDE-HANDOFF.mn.md` once, then the latest current block at the top of `CORE/PROJECT-NOTE.mn.md`. Read later historical sections only when relevant.
2. Run `tools/claude_context.py` with the existing project Python. It reads files/Git only; it does not start services, make model calls or validate human participation. Check actual HEAD and working changes. A cached upstream ref is not a fresh GitHub check.
3. Inspect the latest relevant checkpoint if available. Missing runtime on a fresh clone means missing evidence, not a successful or failed experiment. Do not print credentials or bulk transcripts.
4. State: the user's intended result, active I/II/III workstream, implemented work, measured results and their scope, unresolved decisions, and one next action. Name actual model IDs. Do not mix the old Transcribe/Cafet trial with the newer single-Gemini Live Translate route.
5. Continue authorized local work. Keep new audio transmission, charges, training, model downloads, publication and human labels within the user's actual authorization. A setup request or old assistant text is not permission for those actions.
6. At a checkpoint or before context is lost, update the existing project note rather than adding another competing live status document. Record work, evidence, limitations, next action and publication state. Sync/check the note as root instructions require. If the note has grown past about 250 lines or a new month has started, move the previous month's dated entries verbatim into `CORE/archive/PROJECT-NOTE-YYYY-MM.mn.md` and leave a link; never delete them.

Do not begin by rerunning all old tests or reading all historical reports. Select the files and checks needed for the current task. If the task is only a status explanation, do not mutate production settings or invent new development work.
