#!/usr/bin/env bash
# mk-azdo-agent.sh — register the runner host as an Azure Pipelines self-hosted agent, from a workstation with `az`.
#
#   scripts/runner/mk-azdo-agent.sh --check                 # read-only: the pool, the project queue, the host side
#   scripts/runner/mk-azdo-agent.sh --apply  [--pool agentic] [--agent l4-agent]
#   scripts/runner/mk-azdo-agent.sh --remove                # unregister and remove the service (keeps the pool)
#   scripts/runner/mk-azdo-agent.sh --smoke                 # run one job on the pool, print its log, delete it again
#
# --smoke proves the agent runs jobs without touching a repository: a classic release pipeline with no artifacts and
# one agent job on the project queue (an inline Bash task that checks, from inside the job, that it runs as the agent
# user with no docker, no sudo and no read access to gitlab-runner's logins). The definition is deleted on exit.
#
# Azure side, through the az login (Azure DevOps resource token, sent to curl on stdin, never in argv or on disk):
#   - the pool (organisation level, autoProvision false) and one queue in the project with authorizePipelines false,
#     so a pipeline uses this host only when it names the pool and someone authorizes that pipeline once;
#   - a PAT of scope Agent Pools (read & manage), valid one day, used once for registration, revoked on exit (trap).
# Host side: scripts/runner/azdo-agent.sh, piped through scripts/runner/mk-ssh.sh; the PAT travels inside that stdin
# stream as VSTS_AGENT_INPUT_TOKEN (never an argument, never a file).
#
# Environment: AZDO_ORG (default https://dev.azure.com/example-org), AZDO_PROJECT (default SampleProject),
# AZDO_AGENT_USER (default azdo-agent), MINTKEY_* as for mk-ssh.sh.
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ORG=${AZDO_ORG:-https://dev.azure.com/example-org}
PROJECT=${AZDO_PROJECT:-SampleProject}
AGUSER=${AZDO_AGENT_USER:-azdo-agent}
POOL=agentic AGENT=l4-agent MODE=''
while [ $# -gt 0 ]; do
  case $1 in
    --check|--apply|--remove|--smoke) MODE=${1#--}; shift;;
    --pool) POOL=$2; shift 2;;
    --agent) AGENT=$2; shift 2;;
    *) echo "unknown argument: $1" >&2; exit 2;;
  esac
done
[ -n "$MODE" ] || { echo "usage: mk-azdo-agent.sh --check | --apply | --remove | --smoke" >&2; exit 2; }
ORGNAME=${ORG##*/}
VSSPS=https://vssps.dev.azure.com/$ORGNAME

AAD=$(az account get-access-token --resource 499b84ac-1321-427f-aa17-267ca6975798 --query accessToken -o tsv)
api() {  # api METHOD URL [JSON-BODY]: the bearer goes to curl through its config on stdin; an error body goes to stderr
  local method=$1 url=$2 body=${3:-} out code
  local args=(-sS -K - -X "$method" -w '\n%{http_code}')
  if [ -n "$body" ]; then args+=(-H 'Content-Type: application/json' --data "$body"); fi
  out=$(curl "${args[@]}" "$url" <<<"header = \"Authorization: Bearer $AAD\"") || return 1
  code=${out##*$'\n'} out=${out%$'\n'*}
  if [ "$code" -ge 400 ]; then echo "HTTP $code from $method ${url%%\?*}: ${out:0:400}" >&2; return 1; fi
  printf '%s\n' "$out"
}
jq_py() { python3 -c "import sys,json;d=json.load(sys.stdin);print($1)"; }

pool_id() { api GET "$ORG/_apis/distributedtask/pools?poolName=$POOL&api-version=7.1" | jq_py "d['value'][0]['id'] if d['count'] else ''"; }
queue_id() {
  api GET "$ORG/$PROJECT/_apis/distributedtask/queues?queueNames=$POOL&api-version=7.1" | jq_py "d['value'][0]['id'] if d['count'] else ''"
}

PAT_ID=
revoke() {
  if [ -n "$PAT_ID" ]; then
    api DELETE "$VSSPS/_apis/tokens/pats?authorizationId=$PAT_ID&api-version=7.1-preview.1" >/dev/null \
      && echo "DEL  registration PAT revoked" || echo "WARN could not revoke PAT $PAT_ID: revoke it in User settings > Personal access tokens" >&2
  fi
}
trap revoke EXIT

new_pat() {  # prints the token on stdout once; sets PAT_ID
  local until resp
  until=$(python3 -c 'import datetime;print((datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))')
  resp=$(api POST "$VSSPS/_apis/tokens/pats?api-version=7.1-preview.1" \
    "{\"displayName\":\"l4 azdo-agent registration $AGENT\",\"scope\":\"vso.agentpools_manage\",\"validTo\":\"$until\",\"allOrgs\":false}")
  PAT_ID=$(jq_py "d['patToken']['authorizationId']" <<<"$resp")
  PAT=$(jq_py "d['patToken']['token']" <<<"$resp")
}

VSRM=https://vsrm.dev.azure.com/$ORGNAME/$PROJECT/_apis/release
SMOKE_DEF=
drop_smoke() {
  if [ -n "$SMOKE_DEF" ]; then
    api DELETE "$VSRM/definitions/$SMOKE_DEF?forceDelete=true&api-version=7.1" >/dev/null \
      && echo "DEL  smoke release pipeline $SMOKE_DEF" || echo "WARN could not delete release pipeline $SMOKE_DEF" >&2
  fi
}

# What the smoke job runs, as the agent user. Shipped base64-encoded: a release pipeline expands $(name) macros in
# inline scripts, which would garble shell command substitutions.
smoke_script() {
  cat <<EOF
fail=0
ok() { echo "OK   \$*"; }
bad() { echo "FAIL \$*"; fail=1; }
echo "INFO agent \$AGENT_NAME v\$AGENT_VERSION on \$(hostname), user \$(whoami), groups: \$(id -nG)"
echo "INFO \$(nproc) vCPU, \$(free -m | awk '/^Mem:/{print \$2" MB RAM, "\$7" MB available"}')"
if [ "\$(whoami)" = "$AGUSER" ]; then ok "the job runs as $AGUSER"; else bad "the job runs as \$(whoami), not $AGUSER"; fi
if id -nG | tr ' ' '\n' | grep -qx docker; then bad "in the docker group"; else ok "not in the docker group"; fi
if docker ps >/dev/null 2>&1; then bad "can use docker"; else ok "cannot use docker"; fi
if sudo -n true 2>/dev/null; then bad "has passwordless sudo"; else ok "no passwordless sudo"; fi
if ls /home/gitlab-runner >/dev/null 2>&1; then bad "can list /home/gitlab-runner"; else ok "cannot list /home/gitlab-runner"; fi
for p in .claude .claude.json .codex .local/share/opencode .config/opencode .local/share/kiro-cli .kiro .aws; do
  if test -r "/home/gitlab-runner/\$p"; then bad "can read ~gitlab-runner/\$p"; fi
done
[ \$fail = 0 ] && ok "isolation checks passed"
exit \$fail
EOF
}

smoke_definition() {  # smoke_definition QUEUE-ID OWNER-ID: the release pipeline JSON
  SCRIPT_B64=$(smoke_script | base64 | tr -d '\n') python3 - "$1" "$2" <<'PY'
import json, os, sys
queue, owner = int(sys.argv[1]), sys.argv[2]
script = ("echo \"$SCRIPT_B64\" | base64 -d > smoke.sh\n"   # $SCRIPT_B64 is a task-level env var, not a macro
          "bash smoke.sh")
approvals = {"approvals": [{"rank": 1, "isAutomated": True, "isNotificationOn": False}]}
print(json.dumps({
    "name": "l4-agentic-agent-smoke", "path": "\\",
    "description": "Throwaway smoke job for the agentic pool (scripts/runner/mk-azdo-agent.sh --smoke); deleted after its run.",
    "releaseNameFormat": "smoke-$(rev:r)", "artifacts": [], "triggers": [], "variables": {}, "variableGroups": [],
    "environments": [{
        "name": "agentic", "rank": 1, "owner": {"id": owner}, "variables": {}, "variableGroups": [],
        "preDeployApprovals": approvals, "postDeployApprovals": approvals,
        "conditions": [{"name": "ReleaseStarted", "conditionType": "event", "value": ""}],
        "executionPolicy": {"concurrencyCount": 1, "queueDepthCount": 0},
        "retentionPolicy": {"daysToKeep": 1, "releasesToKeep": 1, "retainBuild": False},
        "environmentOptions": {"emailNotificationType": "Never", "emailRecipients": "release.creator", "skipArtifactsDownload": True,
                               "timeoutInMinutes": 0, "enableAccessToken": False, "publishDeploymentStatus": False,
                               "badgeEnabled": False, "autoLinkWorkItems": False, "pullRequestDeploymentEnabled": False},
        "deployPhases": [{
            "rank": 1, "phaseType": "agentBasedDeployment", "name": "smoke",
            "deploymentInput": {"queueId": queue, "skipArtifactsDownload": True, "timeoutInMinutes": 10,
                                "jobCancelTimeoutInMinutes": 1, "condition": "succeeded()", "enableAccessToken": False,
                                "parallelExecution": {"parallelExecutionType": "none"}, "demands": [], "overrideInputs": {}},
            "workflowTasks": [{
                "taskId": "6c731c3c-3c68-459a-a5c9-bde6e6595b5b", "version": "3.*", "name": "isolation checks",
                "refName": "", "enabled": True, "alwaysRun": False, "continueOnError": False, "timeoutInMinutes": 5,
                "retryCountOnTaskFailure": 0, "definitionType": "task", "overrideInputs": {}, "condition": "succeeded()",
                "environment": {"SCRIPT_B64": os.environ["SCRIPT_B64"]},
                "inputs": {"targetType": "inline", "script": script, "failOnStderr": "false", "workingDirectory": ""},
            }],
        }],
    }],
}))
PY
}

remote() {  # remote ARGS...: azdo-agent.sh on the host; the PAT (if any) rides in the piped script
  "$HERE/mk-ssh.sh" --script <(
    [ -n "${PAT:-}" ] && printf 'export VSTS_AGENT_INPUT_TOKEN=%q\n' "$PAT"
    cat "$HERE/azdo-agent.sh"
  ) -- "$@"
}

case $MODE in
  check)
    p=$(pool_id); q=$(queue_id)
    if [ -n "$p" ]; then echo "OK   pool $POOL (id $p) in $ORG"; else echo "MISS pool $POOL in $ORG"; fi
    if [ -n "$q" ]; then echo "OK   queue $POOL (id $q) in project $PROJECT"; else echo "MISS queue $POOL in project $PROJECT"; fi
    if [ -n "$p" ]; then
      api GET "$ORG/_apis/distributedtask/pools/$p/agents?api-version=7.1" \
        | jq_py "'\n'.join(f\"INFO agent {a['name']}: {a['status']} enabled={a['enabled']} v{a['version']}\" for a in d['value']) or 'INFO no agents'"
    fi
    remote --check --user "$AGUSER"
    ;;
  apply)
    p=$(pool_id)
    if [ -z "$p" ]; then
      p=$(api POST "$ORG/_apis/distributedtask/pools?api-version=7.1" \
        "{\"name\":\"$POOL\",\"autoProvision\":false,\"autoUpdate\":true}" | jq_py "d['id']")
      echo "NEW  pool $POOL (id $p)"
    fi
    if [ -z "$(queue_id)" ]; then
      api POST "$ORG/$PROJECT/_apis/distributedtask/queues?authorizePipelines=false&api-version=7.1" \
        "{\"name\":\"$POOL\",\"pool\":{\"id\":$p}}" >/dev/null
      echo "NEW  queue $POOL in project $PROJECT (pipelines need a one-time authorization)"
    fi
    pkg=$(api GET "$ORG/_apis/distributedtask/packages/agent?platform=linux-x64&\$top=1&api-version=7.1" \
      | jq_py "d['value'][0]['downloadUrl']")
    new_pat
    remote --apply --url "$ORG" --pool "$POOL" --agent "$AGENT" --package-url "$pkg" --user "$AGUSER"
    sleep 5
    api GET "$ORG/_apis/distributedtask/pools/$p/agents?agentName=$AGENT&api-version=7.1" \
      | jq_py "'\n'.join(f\"OK   {a['name']} is {a['status']} in pool $POOL (v{a['version']})\" for a in d['value']) or 'FAIL agent not listed'"
    ;;
  remove)
    new_pat
    remote --remove --user "$AGUSER"
    ;;
  smoke)
    q=$(queue_id)
    [ -n "$q" ] || { echo "MISS queue $POOL in project $PROJECT: run --apply first" >&2; exit 1; }
    owner=$(api GET "$ORG/_apis/connectionData" | jq_py "d['authenticatedUser']['id']")
    trap 'drop_smoke; revoke' EXIT
    SMOKE_DEF=$(api POST "$VSRM/definitions?api-version=7.1" "$(smoke_definition "$q" "$owner")" | jq_py "d['id']")
    echo "NEW  release pipeline l4-agentic-agent-smoke (id $SMOKE_DEF): no artifacts, one job on queue $POOL"
    rel=$(api POST "$VSRM/releases?api-version=7.1" "{\"definitionId\":$SMOKE_DEF,\"description\":\"agentic pool smoke\"}" \
      | jq_py "d['id']")
    echo "NEW  release $rel; waiting for its job (up to 10 minutes)"
    status=''
    for _ in $(seq 60); do
      status=$(api GET "$VSRM/releases/$rel?api-version=7.1" | jq_py "d['environments'][0]['status']")
      case $status in succeeded|rejected|canceled|partiallySucceeded) break;; esac
      sleep 10
    done
    logs=$(mktemp -d)
    if curl -fsS -K - -o "$logs/logs.zip" "$VSRM/releases/$rel/logs?api-version=7.1-preview.2" \
        <<<"header = \"Authorization: Bearer $AAD\"" && unzip -qo "$logs/logs.zip" -d "$logs"; then
      find "$logs" -name '*isolation checks*' -exec cat {} + \
        | sed -nE 's/^[0-9T:.-]+Z //; /^(OK|FAIL|INFO) /p'
    else
      echo "WARN could not fetch the job log" >&2
    fi
    rm -rf "$logs"
    if [ "$status" = succeeded ]; then echo "OK   smoke job succeeded on pool $POOL"
    else echo "FAIL smoke job status: ${status:-unknown}" >&2; exit 1; fi
    ;;
esac
