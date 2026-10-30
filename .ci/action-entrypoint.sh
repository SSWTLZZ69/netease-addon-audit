#!/bin/sh
set -eu
set -- --source "$INPUT_SOURCE"
if [ -n "$INPUT_ARTIFACT" ]; then set -- "$@" --artifact "$INPUT_ARTIFACT"; fi
if [ -n "$INPUT_BASELINE" ]; then set -- "$@" --baseline "$INPUT_BASELINE"; fi
if [ -n "$INPUT_CONFIG" ]; then set -- "$@" --config "$INPUT_CONFIG"; fi
if [ "$(printenv 'INPUT_REQUIRE-BASELINE')" = true ]; then set -- "$@" --require-baseline; fi
sh /opt/audit/entrypoint.sh "$@"
