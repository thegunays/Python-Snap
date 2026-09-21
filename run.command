#!/bin/sh
# Finder opens .command files in Terminal; retain the result for double-click use.
launcher=$0
while [ -L "$launcher" ]; do
    launcher_dir=$(CDPATH= cd -- "$(dirname -- "$launcher")" && pwd -P) || exit 1
    target=$(readlink "$launcher") || exit 1
    case $target in /*) launcher=$target ;; *) launcher=$launcher_dir/$target ;; esac
done
project_root=$(CDPATH= cd -- "$(dirname -- "$launcher")" && pwd -P) || exit 1
REPO_SNAPSHOT_PAUSE=1
export REPO_SNAPSHOT_PAUSE
exec "$project_root/run.sh" "$@"
