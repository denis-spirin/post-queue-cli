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

## Development

Runtime uses Python 3.11+ and only the standard library. Run tests from the
repository root:

```bash
uv run python -m unittest discover -s tests -v
uv run ruff check skills/post-queue-cli/scripts/post_queue.py tests
```

`unittest` is part of Python and runs the tests. Ruff is the only development
package because it only checks formatting and code quality.

Verify skill discovery:

```bash
npx --yes skills add . --list
```
