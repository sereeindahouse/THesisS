---
name: thesis-debug
description: Diagnose and fix a reproducible THesisS text, STT, retrieval, answer-selection, source-guard or TTS problem, then verify the affected behavior with scoped evidence.
---

# Diagnose before changing THesisS

The outcome is a specific verified fix, with the user's original data preserved.

- Reproduce the reported symptom using an existing saved case or a clearly labelled synthetic fixture. Read the error and recent relevant diff before proposing a fix.
- Find the first wrong boundary: audio/input transcription → raw/edited text → routing → retrieved evidence → selected IDs → restored source and year/entity/condition guards → displayed/spoken text → audio delivery. A correct transcription can still produce a wrong answer; a successful HTTP request can still contain a wrong answer.
- Separate observations from hypotheses. Test the smallest justified change, keeping model/source/query versions fixed where the comparison needs them. Do not normalize away an important number/year error or edit the reference after seeing model output.
- Keep diagnostics narrow: IDs, hashes, stage outcomes and safe error codes. Never dump environment variables, keys, tokens or private speech into logs.
- Add a regression check when it captures a real failure. Run the relevant existing tests and check the reported symptom after the fix. A local fixture is not browser QA; decode is not human listening. Do not rerun unrelated full suites merely to make the count larger.
- If attempts fail, use the new evidence to reconsider the cause. Do not stack speculative edits or retry cloud audio automatically. Service lifecycle changes require the actual owner/PID/path/start/listener checks from AGENTS.md.
- Before saying “fixed” or “passes”, inspect the current command result and its scope. Report historical test results as historical. Choose adequate verification for this change; it need not be the full project suite.
- Finish with what changed, why, the actual check, limits, and one next action. Update the existing project note/config metadata as needed.

For a new model/method decision use `/thesis-research`. For actual paid/cloud/audio work, verify the current authorization first. This skill itself grants none.

Method inspiration, rewritten for this project: [systematic-debugging](https://github.com/davila7/claude-code-templates/tree/main/cli-tool/components/skills/development/systematic-debugging) and [verification-before-completion](https://github.com/davila7/claude-code-templates/tree/main/cli-tool/components/skills/development/verification-before-completion). Source review and exclusions are in `.claude/references/aitmpl-review.mn.md`.
