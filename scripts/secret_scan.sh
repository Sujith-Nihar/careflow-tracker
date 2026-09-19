#!/usr/bin/env bash
# Fail if anything that looks like a credential is tracked by git.
# Run before every submission: `make secret-scan`.
set -uo pipefail
cd "$(dirname "$0")/.."

patterns=(
  'sk-[A-Za-z0-9]{16,}'
  'pub_vogent_[A-Za-z0-9]+'
  'eyJ[A-Za-z0-9_-]{20,}\.'                 # JWTs
  'postgres(ql)?://[^:]+:[^@ ]+@'           # DSNs with an inline password
  'AKIA[0-9A-Z]{16}'                        # AWS access key ids
  'ngrok[_-]?auth?token[[:space:]]*[=:][[:space:]]*[A-Za-z0-9_]{20,}'
)

# Placeholders in the example file and docs are expected, not secrets.
allow='(\.env\.example|docs/|README\.md|scripts/secret_scan\.sh)'

found=0
for pattern in "${patterns[@]}"; do
  while IFS= read -r hit; do
    [[ -z "$hit" ]] && continue
    [[ "$hit" =~ $allow ]] && continue
    echo "possible secret: $hit"
    found=1
  done < <(git grep -nIE "$pattern" -- . 2>/dev/null)
done

if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo "fatal: .env is tracked by git"
  found=1
fi

if [[ $found -eq 0 ]]; then
  echo "secret scan clean: no credentials tracked"
fi
exit $found
