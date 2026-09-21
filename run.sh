#!/bin/sh
# The application owns all repository processing; this script selects Python only.
launcher=$0
while [ -L "$launcher" ]; do
    launcher_dir=$(CDPATH= cd -- "$(dirname -- "$launcher")" && pwd -P) || exit 1
    target=$(readlink "$launcher") || exit 1
    case $target in /*) launcher=$target ;; *) launcher=$launcher_dir/$target ;; esac
done
project_root=$(CDPATH= cd -- "$(dirname -- "$launcher")" && pwd -P) || exit 1
cd "$project_root" || exit 1

supports_python() {
    "$1" -c 'import sys; sys.exit(sys.version_info < (3, 12))' >/dev/null 2>&1
}

snapshot_python=
if [ -n "${REPO_SNAPSHOT_PYTHON:-}" ]; then
    if supports_python "$REPO_SNAPSHOT_PYTHON"; then
        snapshot_python=$REPO_SNAPSHOT_PYTHON
    fi
else
    for candidate in "$project_root/.venv/bin/python" python3 python; do
        if supports_python "$candidate"; then
            snapshot_python=$candidate
            break
        fi
    done
fi

if [ -z "$snapshot_python" ]; then
    printf '%s\n' 'Error: Python 3.12 or newer is required. Install Python or set REPO_SNAPSHOT_PYTHON to its executable.' >&2
    status=1
else
    "$snapshot_python" -B -m repo_snapshot "$@"
    status=$?
fi

if [ "${REPO_SNAPSHOT_PAUSE:-0}" = 1 ] && [ -t 0 ] && [ -t 1 ]; then
    printf '\nPress Enter to close...'
    IFS= read -r ignored || :
fi
exit "$status"
