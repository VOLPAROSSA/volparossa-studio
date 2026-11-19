#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# The vendor package is visible at its normal path only in this transient unit.
set -euo pipefail
umask 077
[[ $GITHUB_ACTIONS == true && $RUNNER_ENVIRONMENT == github-hosted && $RUNNER_OS == Linux && $RUNNER_ARCH == X64 ]]
[[ $GITHUB_EVENT_NAME == workflow_dispatch && $GITHUB_REPOSITORY == VOLPAROSSA/volparossa-studio ]]
[[ $GITHUB_REF == refs/heads/main ]]
[[ $GITHUB_SHA =~ ^[0-9a-f]{40}$ && $GITHUB_SHA == "$GITHUB_WORKFLOW_SHA" ]]
[[ $GITHUB_RUN_ID =~ ^[1-9][0-9]{0,19}$ && $GITHUB_RUN_ATTEMPT =~ ^[1-9][0-9]{0,5}$ ]]
[[ $(id -u) != 0 && $(git -C "$GITHUB_WORKSPACE/studio" rev-parse HEAD) == "$GITHUB_SHA" ]]
[[ $(realpath -e -- "$RUNNER_TEMP") == "$RUNNER_TEMP" && $(realpath -e /opt/google/chrome) == /opt/google/chrome ]]
unit=studio-dashboard-chrome-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}.service
[[ $(systemctl show "$unit" --property=LoadState --value) == not-found ]]
version=158.0.8127.36-1
digest=4696bce00b128f385a870ba2eb6eede61698f22374ea0d8e09af8a1c6543d397
bytes=152702276
host_identity=$(stat -Lc '%d:%i:%u:%g:%a:%s:%y:%z' /opt/google/chrome/chrome)
stage=$(mktemp -d -- "$RUNNER_TEMP/studio-vendor-chrome.XXXXXXXXXX")
archive=$stage/chrome.deb
finish() {
    result=$?
    trap - EXIT HUP INT TERM
    set +e
    if [[ $(systemctl show "$unit" --property=LoadState --value) != not-found ]]; then
        sudo -n systemctl stop "$unit" || result=1
    fi
    [[ $(systemctl show "$unit" --property=LoadState --value) == not-found ]] || result=1
    rm -f -- "$archive" && rmdir -- "$stage" || result=1
    [[ $(stat -Lc '%d:%i:%u:%g:%a:%s:%y:%z' /opt/google/chrome/chrome) == "$host_identity" ]] || result=1
    if (( result == 0 )); then
        python3 -I -B - "$RUNNER_TEMP/silex-dashboard-browser-package.json" "$GITHUB_SHA" "$digest" "$bytes" "$version" <<'PY'
import json, sys
path, revision, sha, size, version = sys.argv[1:]
with open(path, 'x') as output:
    json.dump(dict(studio_revision=revision, package='google-chrome-stable', architecture='amd64',
        package_version=version, archive_bytes=int(size), archive_sha256=sha, read_only_package=True,
        runtime_elf_dependencies_resolved=True, original_host_file_unchanged=True,
        unit_collected=True, private_archive_removed=True), output, sort_keys=True)
    output.write('\n')
PY
        result=$?
    fi
    exit "$result"
}
trap finish EXIT
trap 'exit 1' HUP INT TERM
curl --proto '=https' --fail --silent --show-error --max-time 150 --max-filesize "$bytes" \
    "https://dl.google.com/linux/chrome/deb/pool/main/g/google-chrome-stable/google-chrome-stable_${version}_amd64.deb" -o "$archive"
[[ $(stat -c %s "$archive") == "$bytes" ]]
printf '%s  %s\n' "$digest" "$archive" | sha256sum --check --status

# Only the unprivileged fixture receives these nonsecret workflow inputs.
environment=()
for key in GITHUB_ACTIONS RUNNER_ENVIRONMENT RUNNER_OS RUNNER_ARCH GITHUB_EVENT_NAME GITHUB_REF \
           GITHUB_REPOSITORY GITHUB_SHA GITHUB_WORKFLOW_SHA GITHUB_WORKSPACE GITHUB_RUN_ID \
           GITHUB_RUN_ATTEMPT RUNNER_TEMP CARGO_HOME CARGO_REGISTRIES_CRATES_IO_PROTOCOL; do
    environment+=("$key=${!key:?}")
done
sudo -n systemd-run --quiet --wait --pipe --collect --unit="$unit" \
    --property=Type=exec --property=RuntimeMaxSec=1570 --property=TimeoutStopSec=15 \
    --property=TemporaryFileSystem=/opt/google/chrome:rw,nodev,size=1G,mode=0755 \
    /bin/bash -ceu '
        set -o pipefail
        root=/opt/google/chrome
        [[ $(findmnt -n -M "$root" -o FSTYPE) == tmpfs ]]
        # Authenticate the bounded private copy before interpreting package bytes.
        head -c "$3" -- "$1" > "$root/archive.deb"
        chmod 0600 "$root/archive.deb"
        [[ $(stat -c %s "$root/archive.deb") == "$3" ]]
        printf "%s  %s\n" "$2" "$root/archive.deb" | sha256sum --check --status
        [[ $(dpkg-deb -f "$root/archive.deb" Package) == google-chrome-stable ]]
        [[ $(dpkg-deb -f "$root/archive.deb" Version) == "$4" && $(dpkg-deb -f "$root/archive.deb" Architecture) == amd64 ]]
        # Only application data is extracted. No maintainer script runs.
        dpkg-deb --fsys-tarfile "$root/archive.deb" | tar -x -C "$root" --strip-components=4 --same-owner --same-permissions ./opt/google/chrome
        rm -- "$root/archive.deb"
        [[ $(stat -c "%u:%g:%a:%s" "$root/chrome") == 0:0:755:309615944 ]]
        [[ $(stat -c "%u:%g:%a" "$root/chrome-sandbox") == 0:0:4755 ]]
        [[ $(stat -c "%u:%g:%a" "$root/google-chrome") == 0:0:755 ]]
        mount -o remount,ro,nodev "$root"
        findmnt -n -M "$root" -O ro > /dev/null
        uid=$5 gid=$6 program=$7
        shift 7
        exec setpriv --reuid="$uid" --regid="$gid" --init-groups /usr/bin/env -i PATH=/usr/bin:/bin LANG=C LC_ALL=C \
            "$@" /bin/bash -ceu '\''/lib64/ld-linux-x86-64.so.2 --list /opt/google/chrome/chrome > /dev/null
            exec /usr/bin/python3 -I -B "$1"'\'' -- "$program"
    ' -- "$archive" "$digest" "$bytes" "$version" "$(id -u)" "$(id -g)" \
    "$GITHUB_WORKSPACE/studio/integration/silex-native-dashboard/crud.py" "${environment[@]}"
