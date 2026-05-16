# GitHub (github.com REST API)

You have GitHub tools prefixed `github_*`. Use them ONLY when the user
explicitly mentions GitHub, github.com, an issue, a pull request, a
repository on github.com, a release, or a workflow run.

Do NOT use these for local repo operations — use `git_*` and
`run_shell_command` for anything in the user's working directory.

Do NOT use them to "check" or "verify" anything unless the user asked
about the remote state.

## Destructive remote actions

Confirm via `ask_user` before:
- Force-pushing to protected branches.
- Deleting branches on the remote.
- Closing PRs or issues without explicit context from the user.
