#!/bin/bash
# Update Homebrew formula with new release details, then commit and push.
# Usage: VERSION=1.0.0 URL=https://... SHA256=abc123 bash update_formula.sh

set -euo pipefail

VERSION="${VERSION:?VERSION is required}"
URL="${URL:?URL is required}"
SHA256="${SHA256:?SHA256 is required}"

FORMULA="Formula/cerebrofy.rb"

echo "Updating ${FORMULA} to v${VERSION}..."

sed -i.bak \
  -e "s|__VERSION__|${VERSION}|g" \
  -e "s|__URL__|${URL}|g" \
  -e "s|__SHA256__|${SHA256}|g" \
  "${FORMULA}"

rm -f "${FORMULA}.bak"

git add "${FORMULA}"
git commit -m "cerebrofy ${VERSION}"
git push origin HEAD

echo "Formula updated and pushed."
