#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this installer as root: sudo $0" >&2
    exit 1
fi

umask 022

package_url="git+https://github.com/alissonchaves/seff.git"
global_home="${PIPX_GLOBAL_HOME:-/opt/pipx}"
global_bin="${PIPX_GLOBAL_BIN_DIR:-/usr/local/bin}"

pipx install --global --force "$package_url"

# pipx may inherit a restrictive root umask. The application must be readable
# and executable by users because the command is intended to be system-wide.
chmod -R a+rX "$global_home/venvs/slurm-seff"
chmod a+rx "$global_home" "$global_home/venvs" "$global_bin/seff"

pipx ensurepath --global >/dev/null 2>&1 || true
echo "Installed seff globally at $global_bin/seff"

