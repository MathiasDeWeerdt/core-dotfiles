#!/usr/bin/env bash
# Disposable, offline runtime playground. Never mounts host files or the Docker socket.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
IMAGE=expose-playground:local
NAME=expose-playground
isolation=(--network none --cap-drop ALL --security-opt no-new-privileges
    --read-only --pids-limit 128 --memory 256m --cpus 1
    --tmpfs '/tmp:rw,exec,nosuid,nodev,size=64m'
    --tmpfs '/home/playground:rw,nosuid,nodev,uid=1000,gid=1000,size=64m')
build() {
    bash "$ROOT/build.sh"
    make -C "$ROOT" console-clients
    docker build --file "$ROOT/playground/Dockerfile" --tag "$IMAGE" "$ROOT"
}
case "${1:-help}" in
    build) build ;;
    test)
        build
        test_name="$NAME-test-$$"
        trap 'docker rm -f "$test_name" >/dev/null 2>&1 || true' EXIT
        docker run --rm --name "$test_name" "${isolation[@]}" "$IMAGE" --verbose ;;
    up)
        if docker inspect --format '{{.State.Running}}' "$NAME" 2>/dev/null | grep -qx true; then
            echo 'Playground is already running; existing shells were preserved.'
            exit 0
        fi
        if docker inspect "$NAME" >/dev/null 2>&1; then
            echo 'A stopped playground exists. Run playground.sh down before recreating it.' >&2
            exit 1
        fi
        docker image inspect "$IMAGE" >/dev/null 2>&1 || build
        docker run --detach --name "$NAME" "${isolation[@]}" "$IMAGE"
        ready=false
        for _ in {1..60}; do
            if docker exec "$NAME" expose sessions --json 2>/dev/null | grep -q '"connected": true'; then
                ready=true
                break
            fi
            sleep .25
        done
        $ready || { echo 'Playground startup failed; inspect ./playground.sh logs.' >&2; exit 1; }
        echo 'Use ./playground.sh sessions, then ./playground.sh attach. Ctrl+] detaches.' ;;
    attach) docker exec -it "$NAME" expose attach ;;
    sessions) docker exec "$NAME" expose sessions ;;
    proxychains) shift; docker exec "$NAME" expose proxychains -- "$@" ;;
    down)
        if docker inspect "$NAME" >/dev/null 2>&1; then
            docker rm -f "$NAME"
        else
            echo 'Playground is already stopped.'
        fi ;;
    logs) docker logs --tail 30 "$NAME" ;;
    *) printf 'Usage: ./playground.sh {build|test|up|sessions|attach|proxychains COMMAND|logs|down}\n' ;;
esac
