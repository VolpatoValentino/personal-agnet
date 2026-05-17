# Local commit flow

When the user asks you to commit:

1. Gather context with `git_status` and `git_diff`. Do NOT ask the user to
   paste file contents — `git_diff` gives you that.
2. Write a concise commit message yourself based on the diff.
   - First line: imperative mood, under 70 chars.
   - Optional body: focus on the *why*, not the *what*.
3. Stage files by name (`git add path/...`) rather than `git add -A`/`.` —
   those can sweep up `.env` or credentials. If files look like they might
   contain secrets (`.env*`, `credentials*`, `*.key`, `*.pem`), ask the user
   via `ask_user` before committing.
4. Run `git commit -m "<message>"` via `run_shell_command`.
5. Verify with `git status`.

Don't `--amend` unless the user explicitly asks. Create a NEW commit.
Don't skip hooks (`--no-verify`) unless the user explicitly asks.
Don't `git config` anything.
