#!/usr/bin/env bash
mask() { sed -E 's#(://[^:/@]+:)[^@]+@#\1***@#g; s#(Authorization: *[A-Za-z]+ )[^ ]+#\1***#Ig; s#(=).{12,}$#\1***(long value masked)#'; }
echo "--- include paths"; git config --show-origin --get-all include.path
for f in $(git config --get-all include.path); do
  echo "--- $f (keys and masked values)"; git config --file "$f" --list --show-origin 2>&1 | mask
done
echo "--- effective credential/url/http config"; git config --show-origin --get-regexp '^(credential|url|http)\.' | mask
echo "--- remote"; git remote -v | mask
echo "--- env names"; env | cut -d= -f1 | grep -E '^(CI_|GIT_|GITLAB_)' | sort | tr '\n' ' '; echo
