# Contributor guidance

- Keep application code, workload tools, optional integrations and deployment
  configuration separate. Platform operators are not application dependencies.
- Use `make test`, `make docs` and the focused checks appropriate to a change.
  Run `pre-commit run --all-files` before committing.
- Use Conventional Commit pull request titles. Include Summary, Test Plan, Demo,
  Type of change, Test coverage and Coverage notes from the PR template.
- Never merge a PR or enable auto-merge without the user's explicit approval for
  that specific PR. Opening a PR is not approval to merge.
- Do not publish private deployment values, credentials, internal endpoints or
  demo/PoC applications. Keep private integrations in their owning repository.
- Tell the user how to verify completed work.
