#!/usr/bin/env bash
# peek.sh LABEL [N]: driver log + the [l4] lines of a run so far
L=$1; N=${2:-40}
cat <<EOS > /tmp/free-peek-$$.sh
W=/home/gitlab-runner/l4-free-20261006
sudo -n -u gitlab-runner bash -c "tail -5 \$W/driver.log; echo ---; cat \$W/runs/$L/meta.txt 2>/dev/null; echo ---; grep -E '\[l4\]|Traceback|Error|error:' \$W/runs/$L/run.log 2>/dev/null | sed -E 's/^([0-9T:-]{19})[0-9.]*Z? ?//' | cut -c1-260 | tail -$N; echo ---; cat \$W/runs/$L/ci-overlap.txt 2>/dev/null | tail -3"
EOS
/tmp/scratch/free-run/rssh.sh --script /tmp/free-peek-$$.sh; rm -f /tmp/free-peek-$$.sh
