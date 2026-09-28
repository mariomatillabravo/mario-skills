---
name: token-reviewer
description: Token usage and estimated cost (USD, Anthropic API list prices) of Claude Code sessions, turn by turn, read from the local transcripts, with the split by model, cache and subagents. Use it when the user asks how many tokens or how much money the current session, a past session, a project or a period (today, this week, this month) has used, which prompts were the most expensive, or wants a usage or cost report. En español - cuántos tokens llevo, cuánto me ha costado esta sesión o este proyecto, cuánto he gastado esta semana, reporte de consumo.
argument-hint: "[here | last | all | list | <project> | <session-id> | <file.jsonl>] [--days N]"
allowed-tools:
  - Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/token_reviewer.py" *)
  - Bash(python "${CLAUDE_SKILL_DIR}/scripts/token_reviewer.py" *)
  - Bash(py -3 "${CLAUDE_SKILL_DIR}/scripts/token_reviewer.py" *)
  - Bash(uv run --no-project python "${CLAUDE_SKILL_DIR}/scripts/token_reviewer.py" *)
compatibility: Claude Code running on the user's machine (reads ~/.claude/projects, or $CLAUDE_CONFIG_DIR/projects). Needs Python 3.8+ with the standard library only. Windows, macOS and Linux.
---

# Token Reviewer

`scripts/token_reviewer.py` reads the transcripts that Claude Code keeps on disk and reports tokens and estimated cost per user turn: uncached input, output (including thinking), cache reads, 5-minute and 1-hour cache writes, web searches, subagents and fast mode. Each API response is counted once, although the transcript stores one line per content block, so the totals match the cost Claude Code records for the session.

## 1. Run the script

Use the Bash tool with exactly this command form, which is pre-approved:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/token_reviewer.py" --session ${CLAUDE_SESSION_ID} --top 15
```

If `python3` is not available (common on Windows, where it can open the Microsoft Store instead), retry with `python`, then `py -3`, then `uv run --no-project python`, keeping the rest of the command identical. If none works, tell the user that Python 3.8 or newer is required and stop.

Always pass options. Without a terminal and without options, the script only prints the list of sessions. Run it from the user's working directory, not from the skill folder, so that `--here` finds the right project.

## 2. Choose the options

Arguments given to the skill (may be empty): $ARGUMENTS

| The user wants | Options |
|---|---|
| This session (default) | `--session ${CLAUDE_SESSION_ID} --top 15` |
| The latest session of a project | `<project-name> --top 15` |
| A specific session | `--session <id or prefix> --top 15`, or the path of a `.jsonl` file |
| The total of a project | `--all <project-name>`, or `--all --here` for the current directory |
| A period (today, this week, this month) | `--all --since YYYY-MM-DD` or `--all --days N`, optionally with a project name |
| The available sessions | `--list`, optionally with a project name, `--days N` or `--limit N` |
| A saved report | add `--save` (JSON in `~/.claude/token-reviewer/reports/`; `--out DIR` changes the folder) |
| Structured data to process further | add `--json` (JSON on stdout instead of the table) |
| Refresh the price table now | `--update-prices` |
| No internet access at all | add `--offline` |

Skill arguments map as follows: `here` becomes `--here`, `last` becomes `--last`, `all` becomes `--all`, `list` becomes `--list`. Anything else is a project name, a session id or a path, passed as the first positional argument. Options such as `--days 7` pass through unchanged.

`--top N` limits the table to the N most expensive rows; the totals always cover everything. The output language follows the system locale; force it with `--lang es` or `--lang en`. If the session id is not recognized, the script falls back to the latest session of the current directory and says so.

## 3. Present the results

- Answer in the user's language and keep it short. Lead with the estimated total and the number of turns and API calls, then the most expensive turns (what was asked and what it cost), the split by model and the cache hit rate. Paste the whole table only if the user asks for it.
- Say that these are estimates at Anthropic API list prices: on a Pro or Max subscription the user doesn't pay per token, and Bedrock or Vertex rates differ.
- When the output includes the cost recorded by Claude Code, mention it. It is usually slightly higher, because internal calls such as session titles or compaction are not in the transcript.
- Relay every warning (lines starting with `!`). A model without a known price is never guessed: the script first downloads the official price table (at most once a day), then falls back to the cost Claude Code recorded, and only then excludes it from the total. If a model is still unpriced, run `--update-prices`; if that doesn't help, offer to add its price to the local price file named in the warning.
- Subagent turns are marked with `>` (or `↳` in a terminal) and are included in the totals.
- Reports saved with `--save` contain the full text of the prompts; point this out before the user shares one.

## Maintenance

Prices come from three places, in this order:

1. `~/.claude/token-reviewer/prices.json`: the official table downloaded from https://platform.claude.com/docs/en/about-claude/pricing, either automatically when an unknown model shows up or with `--update-prices`. Models can also be added to it by hand (`input`, `output`, `cache_read`, `cache_write_5m`, `cache_write_1h`, in USD per million tokens); it survives plugin updates.
2. `MODEL_PRICES`, at the top of the script: the offline baseline, dated by `PRICES_DATE`. It wins over a download older than that date.
3. The cost recorded by Claude Code in the transcript, for models still unpriced.

Fast mode uses `FAST_MULTIPLIER` (also read from the official page), and US-only inference adds 1.1x on Claude 4.6 and later models. Set `TOKEN_REVIEWER_OFFLINE=1` to never go online.
