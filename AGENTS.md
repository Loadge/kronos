<!-- graft:start -->
## Graft — repo context graph

This repo is indexed in `graft/`: small linked markdown nodes that explain each
system and carry exact file:line spans, kept in sync with the code through git.

For ANY task here — understanding how something works, finding where code lives,
or scoping a change — get context from the graph before grepping or opening
source files. Re-ask freely (it's cheap) and reuse literal identifiers you
already have (symbol, error string, file name) as the query. New to this repo?
Run `graft map` first — a token-budgeted orientation (dir clusters, hubs,
hotspots), no LLM, no key.

- Run `graft ask "<your question>" --source` → ranked nodes with the relevant
  code spans inlined (each hit's ≤8-line crux by default; `--full` for whole
  definitions when the crux isn't enough). Match the tool to the task shape:
  for understanding or editing, the top node IS the answer — cite its
  `covers:` file:line spans and edit straight from `--source`. For
  exhaustive tasks ("every occurrence / every caller of this pattern"), ranked
  results are top-N, not complete — run `graft grep "<literal>"` instead
  (exhaustive over indexed files, grouped by enclosing symbol), falling back
  to raw `grep -rn` only for unindexed files.
- `graft skeleton <file>` → every definition's signature + span, ~10× cheaper
  than reading the file; use it to skim an API surface.
- `graft callers <symbol>` gives precomputed, exact edges — who calls this.
  Add `--direction out` for what it calls, or `--depth N` to walk
  transitively for the full blast radius. For structural questions, skip
  ranking and use this directly.
- Or browse: `graft/INDEX.md` lists every node; follow the links.
- Monorepos and folders of multiple repos rank fairly across sub-projects —
  hits carry `[scope/]` labels naming which one they're from. Narrow with
  `graft ask "<task>" --in <scope>/` once you know where you're working.

If a returned span is truncated ("+N more lines"), open the file at that exact
range before finalizing. Only open source files when a node genuinely lacks a
needed detail, and then at the exact file:line the node points to — never
re-read whole files.

After big code changes, refresh the graph with `graft build` (deterministic,
no API key, $0).
<!-- graft:end -->

## CI/CD

This repo lives in the self-hosted GitLab (`origin`) and follows the homelab pipeline contract. The text of
this section is the same in every GitLab repo; only "This repo" at the end differs.

1. **Every push**: the test stage runs.
2. **Default branch** (`master`; `main` in the portfolio): after the tests, **INT deploys by itself** at
   `https://<app>-int.<domain>`, the same build as PROD with its own port and data volume, never real data.
3. **PROD is a manual job, pressed by Miguel.** An agent never presses it and never deploys PROD from a shell
   for a repo that has a pipeline. A local `deploy.sh` is for debugging INT or for an emergency, and only
   after asking.

Rules:

- **No host details in the repo** (it may be mirrored publicly). Hosts, paths, URLs and keys are CI/CD variables
  scoped `int` / `production`; locally they live in a git-ignored `deploy.env`, and the environment wins over the file.
- **Secrets are never typed by an agent.** Miguel pastes them into GitLab (Settings > CI/CD > Variables).
- **A failure on the default branch notifies Telegram.** A broken `.gitlab-ci.yml` fails with *no jobs* and notifies
  nobody: lint it before pushing (`gl.sh lint`).
- **Reading a pipeline**: the `gitlab-admin` skill (`gl.sh last`, `gl.sh pipelines <project>`, `gl.sh log <job>`),
  with the read-only `claude-bot` token. A change is not done until its last pipeline is green **and** the host
  confirms it (container healthy; PROD's `StartedAt` unchanged after an INT run).
- **Trying a change without deploying**: push a temporary non-default branch. Only the tests run; delete it afterwards.
- **Mirrors**: where a repo has a GitHub mirror, only the pipeline publishes there (its guard checks what goes out); never push to the `github` remote by hand.

**This repo**: tests (unit + E2E) -> INT -> PROD manual, then the public GitHub mirror (`mirror-github`, after INT; it uses the shared `.mirror-github` block in public mode: gitleaks plus the `MIRROR_DENYLIST` variable over what is published, and it refuses to run without that list). Branch `master`.
