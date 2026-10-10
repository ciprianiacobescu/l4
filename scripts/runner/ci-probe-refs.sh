#!/usr/bin/env bash
# G7: can l4-bot push, list and delete custom refs on this GitLab? Run from a CI job (tags: [agentic]) on a
# throwaway branch of the dummy repo. Needs L4_FORGE_TOKEN in the job environment; its value is never printed.
# Per namespace: push HEAD to <ref> with an empty lease (the ref must not exist), ls-remote it, delete it with a
# lease on the pushed sha, ls-remote again. Exit 0 only when every step of every namespace worked.
set -u
set +x

: "${L4_FORGE_TOKEN:?L4_FORGE_TOKEN is not set}"
: "${CI_SERVER_URL:?run this from a GitLab CI job}"
: "${CI_PROJECT_PATH:?run this from a GitLab CI job}"

# The same shape as l4.forge.pushurl: a user name in the URL keeps the runner's insteadOf (job token) off it.
URL="https://oauth2@${CI_SERVER_URL#*://}/${CI_PROJECT_PATH}.git"
HELPER='!f() { test "$1" = get || exit 0; echo username=oauth2; echo "password=$L4_FORGE_TOKEN"; }; f'
NONCE="$(date +%s)-$$"
SHA="$(git rev-parse HEAD)"

# Masked by shape, never by value: the token must not appear in any argv (visible to local users through ps).
mask() { sed -E 's#(password=)[^[:space:]]+#\1***#; s#glpat-[A-Za-z0-9_-]+#***#g'; }
g() { git -c credential.helper= -c "credential.helper=$HELPER" "$@" 2>&1 | mask; return "${PIPESTATUS[0]}"; }
# listed <ref> <sha>: ls-remote prints "<sha>\t<ref>"; with an empty <sha> the ref must be absent
listed() {
  local out
  out=$(g ls-remote "$URL" "$1"); echo "[$out]"
  if [ -n "$2" ]; then [ "$out" = "$(printf '%s\t%s' "$2" "$1")" ]; else [ -z "$out" ]; fi
}

fail=0
step() { # step <label> <command...>
  local label=$1; shift
  echo "--- $label"
  if "$@"; then echo "RESULT $label: ok"; else echo "RESULT $label: REFUSED (exit $?)"; fail=1; return 1; fi
}

echo "server $CI_SERVER_URL project $CI_PROJECT_PATH head $SHA"
git --version
for ref in "refs/l4/doctor/$NONCE" "refs/l4/locks/probe/$NONCE"; do
  echo "=== namespace ${ref%/*}"
  if step "push $ref" g push --porcelain "--force-with-lease=$ref:" "$URL" "$SHA:$ref"; then
    step "ls-remote $ref" listed "$ref" "$SHA"
    step "delete $ref" g push --porcelain "--force-with-lease=$ref:$SHA" "$URL" ":$ref"
    step "ls-remote after delete $ref" listed "$ref" ""
  fi
done
if [ "$fail" = 0 ]; then echo "VERDICT custom refs accepted"; else echo "VERDICT custom refs NOT fully accepted"; fi
exit "$fail"
