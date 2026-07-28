#!/usr/bin/env bash
set -euo pipefail

rootfs=${1:?usage: sign_sandbox_rootfs.sh ROOTFS [BUNDLE]}
bundle=${2:-"${rootfs}.bundle.json"}
digest_file="${rootfs}.sha256"

sha256sum "$rootfs" > "$digest_file"
if [[ -n "${COSIGN_KEY:-}" ]]; then
  cosign sign-blob --yes --key "$COSIGN_KEY" --bundle "$bundle" "$rootfs"
else
  cosign sign-blob --yes --bundle "$bundle" "$rootfs"
fi

printf 'rootfs=%s\nbundle=%s\nsha256=%s\n' "$rootfs" "$bundle" "$digest_file"
