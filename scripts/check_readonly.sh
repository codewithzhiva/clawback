#!/usr/bin/env bash
# CI guard: collectors must be read-only.
# Fails if any collector source calls a mutating AWS API (anything not Describe*/List*/Get*).
# Remediation *strings* in findings are fine — this greps actual boto3 client calls.
set -euo pipefail

DIR="$(cd "$(dirname "$0")/collect" && pwd)"

# boto3 method calls that mutate: .create_* .delete_* .modify_* .put_* .terminate_*
# .release_* .update_* .start_* .stop_* .reboot_* .attach_* .detach_* .associate_* .disassociate_*
PATTERN='\.(create|delete|modify|put|terminate|release|update|start|stop|reboot|attach|detach|associate|disassociate|run|register|deregister|authorize|revoke)_[a-z_]+\('

if grep -rEn "$PATTERN" "$DIR" --include='*.py'; then
  echo "FAIL: mutating API call found in collectors (must be read-only)" >&2
  exit 1
fi
echo "OK: collectors are read-only"
