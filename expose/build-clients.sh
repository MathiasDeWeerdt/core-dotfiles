#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p dist/console-clients
for target in linux/amd64 linux/arm64 darwin/amd64 darwin/arm64 windows/amd64 windows/arm64; do
  target_os=${target%/*}
  target_arch=${target#*/}
  name="$target_os-$target_arch"
  [[ "$target_os" != windows ]] || name+=.exe
  echo "Building console connector: $name"
  (cd src/connector && CGO_ENABLED=0 GOOS="$target_os" GOARCH="$target_arch" go build -trimpath -ldflags='-s -w' -o "../../dist/console-clients/$name" .)
done
