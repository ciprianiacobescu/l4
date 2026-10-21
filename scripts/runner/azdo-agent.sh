#!/usr/bin/env bash
# azdo-agent.sh — an Azure Pipelines self-hosted agent on the runner host, next to the GitLab runner (idempotent).
#
# Runs on the host as the SSH admin user (passwordless sudo), usually piped by scripts/runner/mk-azdo-agent.sh:
#   azdo-agent.sh --check   [--user U]
#   azdo-agent.sh --apply   --url https://dev.azure.com/ORG --pool NAME --agent NAME --package-url URL [--user U]
#   azdo-agent.sh --remove  [--user U]      # stop and uninstall the service, unregister the agent
#
# The agent runs as its own user (default azdo-agent: no docker group, home 750). It must not be able to read the
# agent-CLI logins of gitlab-runner: --apply refuses to register while it can, so an Azure job never reaches them.
# The registration token is the environment variable VSTS_AGENT_INPUT_TOKEN (a short-lived PAT, scope Agent Pools read
# & manage). It is never an argument and never written to disk; after registration the agent authenticates with its
# own key, so the PAT can be revoked at once. --remove needs a token too (it unregisters from the organisation).
set -euo pipefail
MODE='' URL='' POOL='' AGENT='' PKG='' AGUSER=azdo-agent
while [ $# -gt 0 ]; do
  case $1 in
    --check|--apply|--remove) MODE=${1#--}; shift;;
    --url) URL=$2; shift 2;;
    --pool) POOL=$2; shift 2;;
    --agent) AGENT=$2; shift 2;;
    --package-url) PKG=$2; shift 2;;
    --user) AGUSER=$2; shift 2;;
    *) echo "azdo-agent: unknown argument: $1" >&2; exit 2;;
  esac
done
[ -n "$MODE" ] || { echo "usage: azdo-agent.sh --check | --apply ... | --remove" >&2; exit 2; }
case $AGUSER in gitlab-runner|root) echo "azdo-agent: refusing user $AGUSER (the agent gets its own user)" >&2; exit 2;; esac
HOMEDIR=/home/$AGUSER
DIR=$HOMEDIR/agent
# Logins the Azure agent must not read (gitlab-runner's agent CLIs; see docs/runner/README.md "Authentication").
SECRETS=(/home/gitlab-runner/.claude /home/gitlab-runner/.claude.json /home/gitlab-runner/.codex
         /home/gitlab-runner/.local/share/opencode /home/gitlab-runner/.config/opencode
         /home/gitlab-runner/.local/share/kiro-cli /home/gitlab-runner/.kiro /home/gitlab-runner/.aws)

as_agent() { sudo -u "$AGUSER" -H --preserve-env=VSTS_AGENT_INPUT_TOKEN bash -c "cd '$DIR' && $1"; }
as_root() { sudo bash -c "cd '$DIR' && $1"; }
svc_name() { find /etc/systemd/system -maxdepth 1 -name 'vsts.agent.*.service' -printf '%f\n' 2>/dev/null | head -1; }

leaks() {  # the gitlab-runner login paths the agent user can read
  local p
  for p in "${SECRETS[@]}"; do
    if sudo test -e "$p" && sudo -u "$AGUSER" test -r "$p" 2>/dev/null; then echo "$p"; fi
  done
}

check() {
  if id "$AGUSER" >/dev/null 2>&1; then
    echo "OK   user $AGUSER (groups: $(id -nG "$AGUSER"))"
    if id -nG "$AGUSER" | tr ' ' '\n' | grep -qx docker; then echo "WARN $AGUSER is in the docker group (root-equivalent)"; fi
    local l; l=$(leaks)
    if [ -n "$l" ]; then echo "FAIL $AGUSER can read gitlab-runner logins:"; echo "$l" | sed 's/^/       /'
    else echo "OK   $AGUSER cannot read gitlab-runner's agent logins"; fi
  else
    echo "MISS user $AGUSER"
  fi
  if sudo test -x "$DIR/config.sh"; then
    if sudo test -f "$DIR/.agent"; then
      echo "OK   agent registered: $(sudo cat "$DIR/.agent" | python3 -c 'import sys,json;d=json.loads(sys.stdin.buffer.read().decode("utf-8-sig"));print("server", d.get("serverUrl"), "pool", d.get("poolId"), "agent", d.get("agentName"))')"
    else
      echo "MISS agent files in $DIR, not registered"
    fi
  else
    echo "MISS agent files"
  fi
  local s; s=$(svc_name)
  if [ -n "$s" ]; then echo "OK   service $s: $(systemctl is-active "$s" || true)"; else echo "MISS service"; fi
  echo "INFO host: $(nproc) vCPU, $(free -m | awk '/^Mem:/{print $2}') MB RAM; the GitLab runner and this agent can run one job each at the same time"
}

apply() {
  [ -n "$URL" ] && [ -n "$POOL" ] && [ -n "$AGENT" ] && [ -n "$PKG" ] || {
    echo "azdo-agent: --apply needs --url, --pool, --agent and --package-url" >&2; exit 2; }
  if ! id "$AGUSER" >/dev/null 2>&1; then
    sudo useradd --system --create-home --home-dir "$HOMEDIR" --shell /bin/bash "$AGUSER"
    echo "NEW  user $AGUSER"
  fi
  sudo chmod 750 "$HOMEDIR"
  local l; l=$(leaks)
  if [ -n "$l" ]; then
    echo "FAIL $AGUSER can read gitlab-runner logins; not registering (tighten /home/gitlab-runner first):" >&2
    echo "$l" | sed 's/^/       /' >&2
    exit 3
  fi
  if ! sudo test -x "$DIR/config.sh"; then
    sudo -u "$AGUSER" mkdir -p "$DIR"
    curl -fsSL "$PKG" | sudo -u "$AGUSER" tar -xz -C "$DIR"
    as_root "./bin/installdependencies.sh" >/dev/null
    echo "NEW  agent files from $PKG"
  fi
  if ! sudo test -f "$DIR/.agent"; then
    [ -n "${VSTS_AGENT_INPUT_TOKEN:-}" ] || { echo "azdo-agent: VSTS_AGENT_INPUT_TOKEN is not set" >&2; exit 2; }
    as_agent "./config.sh --unattended --url '$URL' --auth pat --pool '$POOL' --agent '$AGENT' --work _work --replace --acceptTeeEula"
    echo "NEW  registered agent $AGENT in pool $POOL"
  fi
  if [ -z "$(svc_name)" ]; then
    as_root "./svc.sh install '$AGUSER'" >/dev/null
    echo "NEW  service $(svc_name)"
  fi
  as_root "./svc.sh start" >/dev/null
  check
}

remove() {
  sudo test -d "$DIR" || { echo "OK   nothing to remove"; return; }
  if [ -n "$(svc_name)" ]; then as_root "./svc.sh stop" >/dev/null || true; as_root "./svc.sh uninstall" >/dev/null; echo "DEL  service"; fi
  if sudo test -f "$DIR/.agent"; then
    [ -n "${VSTS_AGENT_INPUT_TOKEN:-}" ] || { echo "azdo-agent: unregistering needs VSTS_AGENT_INPUT_TOKEN" >&2; exit 2; }
    as_agent "./config.sh remove --unattended --auth pat"
    echo "DEL  registration"
  fi
  echo "OK   $DIR and user $AGUSER are kept (sudo userdel -r $AGUSER drops both)"
}

"$MODE"
