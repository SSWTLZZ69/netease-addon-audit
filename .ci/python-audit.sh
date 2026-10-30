#!/bin/sh
# Run inside python:2.7.18-buster; arguments are addon root and report directory.
set -eu

source_root=${1:?Usage: python-audit.sh SOURCE_ROOT [OUTPUT_DIRECTORY]}
output_directory=${2:-out/audit}
tooling_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$output_directory"
source_root=$(CDPATH= cd -- "$source_root" && pwd)
output_directory=$(CDPATH= cd -- "$output_directory" && pwd)
report="$output_directory/pylint.txt"
cd "$tooling_root"
unset PYTHONPATH

run_audit() {
    python -c 'import sys; assert sys.version_info[:2] == (2, 7), "Python 2.7 is required"' || return "$?"
    if [ "${AUDIT_SKIP_INSTALL:-0}" != 1 ]; then
        python -m pip install --disable-pip-version-check -r "$tooling_root/.ci/requirements-python2.txt" || return "$?"
    fi
    python - "$source_root" <<'PY'
from __future__ import print_function

import json
import os
import sys

source_root = os.path.abspath(sys.argv[1])
if not os.path.isdir(source_root):
    sys.exit('Addon source directory does not exist: %s' % source_root)


packs = []
for directory, subdirectories, filenames in os.walk(source_root):
    subdirectories[:] = sorted(name for name in subdirectories if name != '.git')
    for name in ('manifest.json', 'pack_manifest.json'):
        if name not in filenames:
            continue
        with open(os.path.join(directory, name), 'rb') as stream:
            manifest = json.loads(stream.read().decode('utf-8-sig'))
        if any(module.get('type') in ('data', 'resources')
               for module in manifest.get('modules', [])):
            packs.append(directory)
            break

if not packs:
    sys.exit('No behavior/resource packs discovered beneath %s' % source_root)

paths = set()
for pack in packs:
    for directory, subdirectories, filenames in os.walk(pack):
        subdirectories.sort()
        paths.update(os.path.join(directory, name)
                     for name in filenames if name.endswith('.py'))

if not paths:
    print('No Python files found in %d discovered packs' % len(packs))
    sys.exit(0)

# Each pack root is an import root in the game; do not fabricate SDK modules.
os.environ['PYTHONPATH'] = os.pathsep.join(packs)
print('Linting %d Python files in %d packs with PYTHONPATH=%s' %
      (len(paths), len(packs), os.environ['PYTHONPATH']))
sys.stdout.flush()
# E0401 stays enabled except for the engine-provided mod namespace.
# Errors-only retains every E/F diagnostic, including E0602, E1306 and E1136.
from pylint import config
from pylint.lint import Run
sys.path.extend(packs)
os.chdir(source_root)
# Repository/user pylintrc settings must not disable CI error checks.
config.PYLINTRC = None
Run([
    '--errors-only', '--ignored-modules=mod,mod.*',
    '--persistent=no', '--reports=no', '--score=no',
    '--msg-template={path}:{line}:{column}: {msg_id} ({symbol}) {msg}',
] + sorted(paths))
PY
}

status=0
run_audit >"$report" 2>&1 || status=$?
cat "$report"
exit "$status"
