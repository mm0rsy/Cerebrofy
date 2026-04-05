#!/bin/bash
# Build a self-contained macOS binary tarball for Homebrew distribution.
# Usage: VERSION=1.0.0 bash build_bottle.sh

set -euo pipefail

VERSION="${VERSION:-$(python3 -c 'import cerebrofy; print(cerebrofy.__version__)')}"
ARTIFACT="cerebrofy-${VERSION}-macos.tar.gz"

echo "Building macOS binary for cerebrofy v${VERSION}..."

pip install pyinstaller "cerebrofy[mcp]"

pyinstaller \
  --onefile \
  --name cerebrofy \
  --add-data "src/cerebrofy/queries:cerebrofy/queries" \
  src/cerebrofy/__main__.py

echo "Packaging tarball: ${ARTIFACT}"
tar czf "${ARTIFACT}" -C dist cerebrofy

SHA256=$(shasum -a 256 "${ARTIFACT}" | awk '{print $1}')
echo "${SHA256}  ${ARTIFACT}" > "${ARTIFACT}.sha256"

echo "Build complete: ${ARTIFACT}"
echo "SHA-256: ${SHA256}"
