# CI runners

Every job in `ci.yml` and `release.yml` first calls `select-runner.yml`, which
asks the GitHub API which self-hosted runners are online and picks the first
available tier:

| Priority | Runner | `runs-on` | Used when |
| --- | --- | --- | --- |
| 1 | WSL runner on blackhole | `[self-hosted, blackhole]` | online and idle |
| 2 | GitHub-hosted | `ubuntu-latest` | always, unless `RUNNER_GITHUB_HOSTED=false` |

The VPS runners (this repository's own and the shared organization runner
`sentrymo-shared`) were dropped on 2026-11-23; GitHub-hosted runners replace
them. With `RUNNER_GITHUB_HOSTED=false` jobs queue on the blackhole WSL runner.
Pull requests from forks always run on GitHub-hosted runners, so outside code
never reaches blackhole.

The decision logic lives in `.github/scripts/select_runner.py` (stdlib only)
and is covered by `tests/test_select_runner.py`.

## One-time setup

1. **Token for the selector.** Create a fine-grained personal access token
   with resource owner `Sentrymo`, organization permission *Self-hosted
   runners: Read* and repository permission *Administration: Read* on the
   repositories that use the selector. Store it as the organization secret
   `RUNNER_STATUS_TOKEN`. Without it the selector cannot see self-hosted
   runners and always picks GitHub-hosted (with a warning).
2. **Blackhole WSL runner.** It must carry the label `blackhole` (or set the
   variable `RUNNER_WSL_LABEL` to its label). It may be registered at the
   repository or the organization; both are checked.
3. **Runner group access.** Organization -> Settings -> Actions -> Runner
   groups: allow this repository in the group of the blackhole runner, and
   enable *Allow public repositories*, because this repository is public.
4. **Fork protection.** Repository -> Settings -> Actions -> General ->
   *Require approval for all external contributors*.

## Variables

Repository or organization Actions variables, all optional:

| Variable | Default | Meaning |
| --- | --- | --- |
| `RUNNER_WSL_LABEL` | `blackhole` | label of the blackhole WSL runner |
| `RUNNER_GITHUB_HOSTED` | `true` | `false` skips GitHub-hosted (e.g. a private repo out of minutes) |
| `RUNNER_GITHUB_LABEL` | `ubuntu-latest` | GitHub-hosted image |
| `RUNNER_FORCE` | | `wsl` or `github` to bypass detection |
| `RUNNER_SELECTOR_RUNS_ON` | `ubuntu-latest` | JSON `runs-on` for the selector job itself |
