#!/usr/bin/env bash
# Download the AWS icons listed in icons.tsv into ../icons/aws/<name>.svg.
# Skips icons already on disk, so it is cheap to run again. Needs network once.
# Usage: fetch-icons.sh   (add a service by adding a line to icons.tsv)
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
dest="$here/../icons/aws"
base="https://icons.terrastruct.com/aws%2F"
mkdir -p "$dest"

failed=0
while IFS=$'\t' read -r name path; do
  [ -n "$name" ] || continue
  [ -s "$dest/$name.svg" ] && continue
  tmp="$dest/$name.tmp"
  if curl -fsS "$base$path.svg" -o "$tmp" 2>/dev/null && head -c 400 "$tmp" | grep -q '<svg'; then
    mv "$tmp" "$dest/$name.svg"
  else
    rm -f "$tmp"; echo "failed: $name ($path)" >&2; failed=1
  fi
done < "$here/icons.tsv"

echo "icons in $dest: $(find "$dest" -name '*.svg' | wc -l | tr -d ' ')"
exit "$failed"
