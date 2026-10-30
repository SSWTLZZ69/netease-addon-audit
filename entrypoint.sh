#!/bin/sh
# Inspect the exact payload, then lint it even if structural checks fail.
set -eu
tool_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
output=${AUDIT_OUTPUT:-out/audit}
status=0
python "$tool_dir/.ci/audit.py" --output "$output" "$@" || status=$?
if [ -d "$output/payload" ]; then
    sh "$tool_dir/.ci/python-audit.sh" "$output/payload" "$output" || status=$?
else
    status=1
fi
exit "$status"
