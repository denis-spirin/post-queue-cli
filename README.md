# Post Queue CLI

Public Agent Skill and zero-dependency Python CLI for managing Post Queue posts
and posting queues from Codex or Claude Code.

## Install

Run this from any directory:

```bash
npx skills add denis-spirin/post-queue-cli --skill post-queue-cli --global
```

The installer prompts for any detected coding agents. It installs only the
contents of `skills/post-queue-cli/`; contributor tests are not installed.

Create an API key at <https://post-queue.com/api-keys>, then follow the installed
skill's `references/ENV.md` to save it in the skill's local `.env` file.
