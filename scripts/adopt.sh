#!/usr/bin/env bash
# adopt.sh — adopt this harness in the repository you are standing in (clone-and-adopt bootstrap).
#
#   git clone https://github.com/ciprianiacobescu/agent-supervisor.git ~/l4
#   cd /path/to/your-project && ~/l4/scripts/adopt.sh
#
# adopt.sh [--repo DIR] [--ci gitlab|github] [--framework openspec|kiro] [--commit] [--no-install] [--no-gates] [--dry-run]
#
#   --repo DIR        the repository to adopt (default: the current directory)
#   --ci F            forge CI to write: gitlab or github (default: derived from the origin remote)
#   --framework F     spec framework: openspec or kiro (default: detected by `l4 init`)
#   --commit          commit exactly the adoption paths as "Adopt the L4 harness" (never `git add -A`)
#   --no-install      do not install uv when it is missing; fail and print the install command
#   --no-gates        `l4 doctor --adoption --no-gates`: check the configuration only, skip the gate dry run
#   --dry-run         change nothing: `l4 init --dry-run` / `l4 upgrade --dry-run`; skip sync, doctor and commit
#
# Installs uv (pinned, user-local) when missing, syncs the harness environment, runs `l4 init --vendor` (or
# `l4 upgrade` when .l4/config.yaml exists), runs `l4 doctor --adoption`, then prints the remaining steps. A second run
# is safe. It reads no secret and uses the network only for the uv installer and `uv sync`.
# Every step prints "[ADOPT-nn] <STATUS> <title> — <detail>" with STATUS in OK | MISSING | FIXED | FAILED | WARN | SKIP | INFO.
# Exit: 0 done; 1 a step failed; 2 refused (precondition or the tool's refusal); 3 doctor found a red base.
set -uo pipefail

L4=$(cd "$(dirname "$0")/.." && pwd)
GIT_MIN=${GIT_MIN:-2.34.0}
if [ -z "${UV_VERSION:-}" ]; then   # one source of truth: the pin in the runner prerequisites script
  # shellcheck disable=SC2016  # the sed pattern is literal text of prereqs.sh
  UV_VERSION=$(sed -n 's/^UV_VERSION=\${UV_VERSION:-\([^}]*\)}.*/\1/p' "$L4/scripts/runner/prereqs.sh" 2>/dev/null | head -1)
  UV_VERSION=${UV_VERSION:-0.12.22}
fi

REPO_ARG=.; CI=""; FRAMEWORK=""; COMMIT=0; NO_INSTALL=0; NO_GATES=0; DRY=0
while [ $# -gt 0 ]; do
  a=$1; shift
  case "$a" in
    --repo) REPO_ARG=${1:?--repo needs a directory}; shift;;
    --ci) CI=${1:?--ci needs gitlab or github}; shift
          case "$CI" in gitlab|github) ;; *) echo "--ci must be gitlab or github" >&2; exit 2;; esac;;
    --framework) FRAMEWORK=${1:?--framework needs openspec or kiro}; shift
          case "$FRAMEWORK" in openspec|kiro) ;; *) echo "--framework must be openspec or kiro" >&2; exit 2;; esac;;
    --commit) COMMIT=1;; --no-install) NO_INSTALL=1;; --no-gates) NO_GATES=1;; --dry-run) DRY=1;;
    -h|--help) sed -n "2,21p" "$0"; exit 0;;
    *) echo "unknown argument: $a" >&2; exit 2;;
  esac
done

report() { printf '[%s] %-7s %s — %s\n' "$1" "$2" "$3" "$4"; }
die() { report "$1" FAILED "$2" "$3"; echo "adopt: done (exit $4)"; exit "$4"; }
ver_ge() { [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -1)" = "$2" ]; }   # ver_ge A B  <=>  A >= B

# ADOPT-01 — the harness checkout is this script's parent directory.
if [ -f "$L4/pyproject.toml" ] && [ -d "$L4/src/l4" ]; then report ADOPT-01 OK "harness" "$L4"
else die ADOPT-01 "harness" "$L4 has no pyproject.toml and src/l4 — run the copy of adopt.sh inside a harness checkout" 2; fi

# ADOPT-02 — git.
gv=$(git --version 2>/dev/null | awk '{print $3}')
if [ -n "$gv" ] && ver_ge "$gv" "$GIT_MIN"; then report ADOPT-02 OK "git" "git $gv (need >= $GIT_MIN)"
else die ADOPT-02 "git" "git ${gv:-missing} (need >= $GIT_MIN)" 2; fi

# ADOPT-03 — the repository.
REPO=$(git -C "$REPO_ARG" rev-parse --show-toplevel 2>/dev/null) || die ADOPT-03 "repository" "$REPO_ARG is not inside a git repository" 2
REPO=$(cd "$REPO" && pwd -P)
if [ "$REPO" = "$(cd "$L4" && pwd -P)" ]; then die ADOPT-03 "repository" "$REPO is the harness checkout itself — run adopt.sh from the project to adopt" 2; fi
git -C "$REPO" rev-parse --verify -q HEAD >/dev/null 2>&1 || die ADOPT-03 "repository" "$REPO has no commit — commit something first" 2
DIRTY0=$(git -C "$REPO" status --porcelain --untracked-files=all 2>/dev/null)
if [ -n "$DIRTY0" ]; then report ADOPT-03 WARN "repository" "$REPO has uncommitted changes; doctor checks HEAD only"
else report ADOPT-03 OK "repository" "$REPO"; fi

# ADOPT-04 — uv.
HAVE_UV=1
if ! command -v uv >/dev/null 2>&1; then
  for d in "$HOME/.local/bin" "$HOME/.cargo/bin"; do
    if [ -x "$d/uv" ]; then PATH="$d:$PATH"; export PATH; break; fi
  done
fi
INSTALL_CMD="curl -LsSf \"https://astral.sh/uv/${UV_VERSION}/install.sh\" | sh"
if command -v uv >/dev/null 2>&1; then report ADOPT-04 OK "uv" "$(uv --version 2>/dev/null) at $(command -v uv)"
elif [ "$NO_INSTALL" = 1 ]; then
  die ADOPT-04 "uv" "uv not found and --no-install given; install it with: $INSTALL_CMD" 2
elif [ "$DRY" = 1 ]; then
  HAVE_UV=0; report ADOPT-04 MISSING "uv" "dry run: would install uv $UV_VERSION user-locally with: $INSTALL_CMD"
else
  if curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" | sh >/dev/null 2>&1; then
    PATH="$HOME/.local/bin:$PATH"; export PATH
    if command -v uv >/dev/null 2>&1; then report ADOPT-04 FIXED "uv" "installed $(uv --version 2>/dev/null) in $HOME/.local/bin"
    else die ADOPT-04 "uv" "installer ran but uv is not on PATH; try: $INSTALL_CMD" 1; fi
  else die ADOPT-04 "uv" "install failed; run it yourself: $INSTALL_CMD" 1; fi
fi

# ADOPT-05 — the harness environment.
if [ "$DRY" = 1 ] || [ "$HAVE_UV" = 0 ]; then report ADOPT-05 SKIP "harness environment" "dry run: uv sync not run"
else
  out=$(uv sync --frozen --project "$L4" 2>&1); rc=$?
  if [ "$rc" -eq 0 ]; then report ADOPT-05 OK "harness environment" "uv sync --frozen --project $L4"
  else die ADOPT-05 "harness environment" "uv sync failed (exit $rc): $(printf '%s\n' "$out" | tail -5 | tr '\n' ' ')" 1; fi
fi

# ADOPT-06 — which CI.
ORIGIN=$(git -C "$REPO" remote get-url origin 2>/dev/null || true)
if [ -n "$CI" ]; then report ADOPT-06 INFO "CI" "$CI (--ci)"
elif [ -n "$ORIGIN" ]; then
  case "$ORIGIN" in
    *github.com*) CI=github; report ADOPT-06 INFO "CI" "github (origin contains github.com)";;
    *) CI=gitlab; report ADOPT-06 INFO "CI" "gitlab (origin is not github.com)";;
  esac
elif [ -f "$REPO/.gitlab-ci.yml" ]; then CI=gitlab; report ADOPT-06 INFO "CI" "gitlab (no origin, but a .gitlab-ci.yml exists)"
else die ADOPT-06 "CI" "no origin remote and no .gitlab-ci.yml: pass --ci gitlab or --ci github" 2; fi

SNAP=$(git -C "$REPO" status --porcelain -z --untracked-files=all 2>/dev/null | tr '\0' '\n' | sort)   # before ADOPT-07

# ADOPT-07 — adopt (or upgrade when already adopted).
DRYFLAG=""; [ "$DRY" = 1 ] && DRYFLAG="--dry-run"
if [ "$HAVE_UV" = 0 ]; then report ADOPT-07 SKIP "adopt" "uv is not installed (dry run)"
else
  if [ ! -e "$REPO/.l4/config.yaml" ]; then
    ARGS=(init --repo "$REPO" --ci "$CI" --vendor)
    [ -n "$FRAMEWORK" ] && ARGS+=(--framework "$FRAMEWORK")
    [ -n "$DRYFLAG" ] && ARGS+=("$DRYFLAG")
    report ADOPT-07 INFO "adopt" "l4 ${ARGS[*]}"
  else
    ARGS=(upgrade --repo "$REPO")
    [ -n "$DRYFLAG" ] && ARGS+=("$DRYFLAG")
    report ADOPT-07 INFO "adopt" "already adopted: upgrading the vendored harness (l4 ${ARGS[*]})"
  fi
  uv run --frozen --project "$L4" l4 "${ARGS[@]}"; rc=$?
  if [ "$rc" -ne 0 ]; then
    [ "$rc" -eq 2 ] && echo "adopt: l4 refused; add the snippet it printed, then rerun with the same flags" >&2
    die ADOPT-07 "adopt" "l4 ${ARGS[0]} exited $rc" "$rc"
  fi
  report ADOPT-07 OK "adopt" "l4 ${ARGS[0]} done"
fi

# ADOPT-08 — the adoption check.
RED=0
if [ "$DRY" = 1 ]; then report ADOPT-08 SKIP "check" "dry run: doctor not run"
elif [ ! -x "$REPO/.l4/bin/l4" ]; then die ADOPT-08 "check" "$REPO/.l4/bin/l4 is missing after adoption" 1
else
  DARGS=(doctor --adoption); [ "$NO_GATES" = 1 ] && DARGS+=(--no-gates)
  (cd "$REPO" && .l4/bin/l4 "${DARGS[@]}"); rc=$?
  if [ "$rc" -eq 0 ]; then report ADOPT-08 OK "check" "l4 ${DARGS[*]}"
  elif [ "$rc" -eq 3 ]; then RED=1; report ADOPT-08 WARN "check" "red base: fix what doctor lists (config edits in .l4/config.yaml), then rerun adopt.sh"
  else die ADOPT-08 "check" "l4 ${DARGS[*]} exited $rc" "$rc"; fi
fi

# ADOPT-09 — commit exactly what the adoption wrote: the paths that are new or changed compared with the snapshot taken
# before ADOPT-07. A path that was already dirty before stays unstaged, so your own edits are never swept in.
if [ "$COMMIT" = 1 ] && [ "$DRY" = 0 ] && [ "$RED" = 0 ]; then
  NOW=$(git -C "$REPO" status --porcelain -z --untracked-files=all 2>/dev/null | tr '\0' '\n' | sort)
  LIST=$(mktemp "${TMPDIR:-/tmp}/adopt-paths.XXXXXX")
  printf '%s\n' "$NOW" | grep -vxF -f <(printf '%s\n' "$SNAP") | grep -v '^$' | cut -c4- | tr '\n' '\0' > "$LIST"
  if [ -s "$LIST" ]; then git -C "$REPO" add --pathspec-from-file="$LIST" --pathspec-file-nul >/dev/null 2>&1; fi
  rm -f "$LIST"
  if git -C "$REPO" diff --cached --quiet; then report ADOPT-09 SKIP "commit" "nothing to commit"
  elif git -C "$REPO" commit -q -m "Adopt the L4 harness"; then report ADOPT-09 OK "commit" "Adopt the L4 harness ($(git -C "$REPO" rev-parse --short HEAD))"
  else die ADOPT-09 "commit" "git commit failed (hooks? identity?)" 1; fi
elif [ "$COMMIT" = 1 ]; then report ADOPT-09 SKIP "commit" "$([ "$DRY" = 1 ] && echo 'dry run' || echo 'red base: not committed')"
fi

# Next steps.
BRANCH=$(git -C "$REPO" symbolic-ref --short -q HEAD 2>/dev/null || echo main)
project_path() {   # group/name from https://host/group/name(.git), ssh://git@host[:port]/group/name or git@host:group/name
  local u=$1 rest
  case "$u" in
    *://*) rest=${u#*://}; rest=${rest#*@}; rest=${rest#*/};;
    *) rest=${u#*@}; rest=${rest#*:};;
  esac
  rest=${rest%/}; rest=${rest%.git}; printf '%s' "$rest"
}
server_url() {     # https://host[:port] of the forge: an https origin keeps its port, an SSH origin's port is the SSH port
  local u=$1 host
  case "$u" in
    https://*|http://*) host=${u#*://}; host=${host#*@}; host=${host%%/*}; printf '%s' "${u%%://*}://$host";;
    *://*) host=${u#*://}; host=${host#*@}; host=${host%%/*}; host=${host%%:*}; printf 'https://%s' "$host";;
    *@*:*) host=${u#*@}; host=${host%%:*}; printf 'https://%s' "$host";;
  esac
}
echo
echo "Remaining steps:"
if [ -z "$ORIGIN" ]; then echo "  0. git remote add origin <url of the empty ${CI} project>   # no origin remote yet"; fi
RUNNER_BLOCK() {
  echo "  Runner (see docs/quickstart.md, \"Prepare the runner\"):"
  if [ "$CI" = gitlab ]; then
    echo "     install gitlab-runner (https://docs.gitlab.com/runner/install/linux-repository/), create a PROJECT runner"
    echo "     (Settings > CI/CD > Runners > New project runner, tags = ci.runner_tags, default agentic, run untagged jobs off), then on the host:"
    echo "     sudo gitlab-runner register --non-interactive --url $GLURL --token <glrt-... runner token> --executor shell"
  else
    echo "     register a self-hosted runner (repo Settings > Actions > Runners > New self-hosted runner) with the labels of runs-on: $RUNSON"
  fi
  echo "     then, as an admin with sudo, from a clone of the harness on the runner host:"
  echo "     bash scripts/runner/prereqs.sh --check, then bash scripts/runner/prereqs.sh --apply"
  echo "     (set RUNNER_USER=<user the runner service runs as> when it is not gitlab-runner)"
  echo "     then log in the agent CLIs AS the runner user (prereqs PRQ-15 prints the exact steps);"
  echo "     never copy CLI credentials between users or machines"
}
WF="$REPO/.github/workflows/l4.yml"
RUNSON=$(sed -n 's/^ *runs-on: *//p' "$WF" 2>/dev/null | head -1); RUNSON=${RUNSON:-<see runs-on in .github/workflows/l4.yml>}
if [ "$CI" = gitlab ]; then
  PROJ=$(project_path "$ORIGIN"); PROJ=${PROJ:-<group/name>}
  GLURL=$(server_url "$ORIGIN"); GLURL=${GLURL:-<gitlab url>}
  echo "  1. git -C \"$REPO\" push -o ci.skip -u origin $BRANCH   # ci.skip: the token does not exist yet"
  echo "  2. the runner (below): setup in step 3 needs an online runner with the ci.runner_tags"
  echo "  3. GITLAB_TOKEN=<maintainer token> \"$REPO/.l4/bin/l4\" setup gitlab --project $PROJ --watch"
  RUNNER_BLOCK
else
  SECRET=$(sed -n 's/.*secrets\.\([A-Za-z0-9_]*\).*/\1/p' "$WF" 2>/dev/null | head -1); SECRET=${SECRET:-L4_FORGE_TOKEN}
  echo "  1. git -C \"$REPO\" push -u origin $BRANCH"
  echo "  2. the runner (below), with the labels the workflow runs on: runs-on: $RUNSON"
  echo "  3. add a repository secret named $SECRET holding a fine-grained token for this repository with"
  echo "     contents, pull requests, commit statuses and actions write access"
  echo "  4. run the l4 workflow by hand (Actions > l4 > Run workflow) and read its log"
  echo "  Note: \`l4 setup\` automates GitLab only; on GitHub the secret and the runner are manual steps."
  RUNNER_BLOCK
fi
echo
if [ "$RED" = 1 ]; then echo "adopt: done (exit 3)"; exit 3; fi
echo "adopt: done (exit 0)"; exit 0
