#!/usr/bin/env bash
# mk-setup.sh QUEUEFILE [with-bundle] > setup-remote.sh : the one-shot runner setup (files via base64, owned by gitlab-runner)
F=$(cd "$(dirname "$0")" && pwd)
Q=$1; WB=${2:-}
W=/home/gitlab-runner/l4-free-20261006
put() {  # put LOCALFILE REMOTENAME
  echo "base64 -d <<'B64EOF' | sudo -n -u gitlab-runner tee $W/$2 >/dev/null"
  base64 -i "$1"
  echo "B64EOF"
}
echo 'set -eu'
echo "sudo -n -u gitlab-runner -H bash -c 'mkdir -p $W/runs && chmod 700 $W'"
[ "$WB" = with-bundle ] && put "$F/seed.bundle" seed.bundle
put "$F/cfg.tmpl.yaml" cfg.tmpl.yaml
put "$F/driver.sh" driver.sh
put "$Q" queue.txt
echo "sudo -n -u gitlab-runner chmod 700 $W/driver.sh"
if [ "$WB" = with-bundle ]; then
cat <<EOS
sudo -n -u gitlab-runner -H bash -lc 'cd $W && rm -rf origin-seed.git && git init -q --bare origin-seed.git && git -C origin-seed.git fetch -q $W/seed.bundle "refs/free/*:refs/heads/*" && git -C origin-seed.git symbolic-ref HEAD refs/heads/main && git -C origin-seed.git for-each-ref --format="%(refname) %(objectname:short)"'
EOS
fi
echo "sudo -n -u gitlab-runner ls -la $W"
