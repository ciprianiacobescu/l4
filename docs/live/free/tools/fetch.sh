#!/usr/bin/env bash
# fetch.sh LABEL...: export each finished run (meta, logs, .l4-out, the unit folder at the branch head, the src/tests diff)
# from the runner into $F/got/LABEL/ (a tar through the SSH channel, base64)
F=$(cd "$(dirname "$0")" && pwd)
for L in "$@"; do
cat > /tmp/free-fetch-$$.sh <<EOS
sudo -n -u gitlab-runner -H bash -c '
set -e
W=/home/gitlab-runner/l4-free-20261006; R=\$W/runs/$L
grep -q ^END \$R/meta.txt
UNIT=\$(sed -n "s/.* UNIT=\\([^ ]*\\) .*/\\1/p" \$R/meta.txt | head -1)
rm -rf \$R/export && mkdir -p \$R/export
B=l4/openspec/\$UNIT; O=\$R/origin.git
if git -C \$O rev-parse -q --verify \$B >/dev/null; then
  git -C \$O log --format="%h %an <%ae> | %s%n%(trailers:only,unfold)" main..\$B > \$R/export/branch-commits.txt
  git -C \$O diff main...\$B -- src tests e2e > \$R/export/src-tests.diff || true
  git -C \$O archive \$B openspec/changes/\$UNIT | tar -x -C \$R/export
fi
cd \$R && tar czf - meta.txt run.log status.txt branch-log.txt ci-overlap.txt ratelimit.txt cfg.yaml export repo/.l4-out 2>/dev/null | base64 -w0
'
EOS
mkdir -p "$F/got/$L"
"$F/rssh.sh" --script /tmp/free-fetch-$$.sh | tail -1 | base64 -d | tar xzf - -C "$F/got/$L" && echo "$L: $(find "$F/got/$L" -type f | wc -l) files" || echo "$L: FETCH FAILED"
rm -f /tmp/free-fetch-$$.sh
done
