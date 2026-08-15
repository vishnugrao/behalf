#!/usr/bin/env bash
set -euo pipefail

# Compose scales this service by replica, naming containers `<project>-agent-<n>`.
# The trailing ordinal is the only thing that differs between replicas, so it is
# what selects which agent from config.yaml this process runs as.
if [[ "${1:-}" == "agent-by-ordinal" ]]; then
  shift
  ordinal="${HOSTNAME##*-}"
  [[ "$ordinal" =~ ^[0-9]+$ ]] || ordinal=1
  index=$((ordinal - 1))

  role="$(behalf roster | awk -v i="$index" '$1 == i"." {print $3}')"
  if [[ -z "$role" ]]; then
    echo "replica $ordinal has no agent at roster index $index; idling" >&2
    exec sleep infinity
  fi

  echo "replica $ordinal -> agent index $index ($role)" >&2
  exec behalf agent --role "$role" "$@"
fi

exec behalf "$@"
