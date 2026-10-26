# CI runners

Every job in `ci.yml` and `release.yml` first calls `select-runner.yml`, which
asks the GitHub API which self-hosted runners are online and picks the first
available tier:

| Priority | Runner | `runs-on` | Used when |
| --- | --- | --- | --- |
| 1 | WSL runner on blackhole | `[self-hosted, blackhole]` | online and idle |
| 2 | GitHub-hosted | `ubuntu-latest` | always, unless `RUNNER_GITHUB_HOSTED=false` |
| 3 | this repository's VPS runner | `[self-hosted, <repo name>]` | online (idle preferred) |
| 4 | shared organization VPS runner | `[self-hosted, sentrymo-shared]` | online, or as the last resort |

This repository has no VPS runner of its own, so tier 3 is skipped and the
shared runner covers it. Pull requests from forks always run on GitHub-hosted
runners, so outside code never reaches blackhole or the VPS.

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
3. **Shared VPS runner.** Run `setup-shared-runner.sh` on the VPS as root (see
   below). It registers an organization runner with the label
   `sentrymo-shared` in the `Default` runner group.
4. **Runner group access.** Organization -> Settings -> Actions -> Runner
   groups -> Default: allow the repositories that may use the shared runner,
   and enable *Allow public repositories*, because this repository is public.
5. **Fork protection.** Repository -> Settings -> Actions -> General ->
   *Require approval for all external contributors*.

## Shared VPS runner

```bash
# Organization -> Settings -> Actions -> Runners -> New runner: copy the token
sudo RUNNER_TOKEN=<token> ./setup-shared-runner.sh      # /opt/actions-runner-shared, user gh-shared
sudo RUNNER_TOKEN=<token> ./setup-shared-runner.sh 2    # optional second instance: actions-runner-shared-2
```

Other Sentrymo repositories can use it directly with
`runs-on: [self-hosted, sentrymo-shared]`, or copy `select-runner.yml` and
`select_runner.py` to get the same priority.

## Variables

Repository or organization Actions variables, all optional:

| Variable | Default | Meaning |
| --- | --- | --- |
| `RUNNER_WSL_LABEL` | `blackhole` | label of the blackhole WSL runner |
| `RUNNER_REPO_LABEL` | repository name | label of the repository's own VPS runner |
| `RUNNER_SHARED_LABEL` | `sentrymo-shared` | label of the shared VPS runner |
| `RUNNER_GITHUB_HOSTED` | `true` | `false` skips GitHub-hosted (e.g. a private repo out of minutes) |
| `RUNNER_GITHUB_LABEL` | `ubuntu-latest` | GitHub-hosted image |
| `RUNNER_FORCE` | | `wsl`, `github`, `repo` or `shared` to bypass detection |
| `RUNNER_SELECTOR_RUNS_ON` | `ubuntu-latest` | JSON `runs-on` for the selector job itself |
