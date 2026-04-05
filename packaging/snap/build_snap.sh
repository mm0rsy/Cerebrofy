#!/bin/bash
# Build the cerebrofy Snap package.
# Produces: cerebrofy-linux-amd64.snap

set -euo pipefail

echo "Building Linux Snap package..."

snapcraft

SNAP_FILE=$(ls cerebrofy_*.snap 2>/dev/null | head -1)
if [ -z "${SNAP_FILE}" ]; then
  echo "Error: no .snap file produced." >&2
  exit 1
fi

ARTIFACT="cerebrofy-linux-amd64.snap"
mv "${SNAP_FILE}" "${ARTIFACT}"

sha256sum "${ARTIFACT}" > "${ARTIFACT}.sha256"

echo "Build complete: ${ARTIFACT}"
echo "SHA-256: $(cat ${ARTIFACT}.sha256)"
