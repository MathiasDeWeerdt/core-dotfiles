---
description: "Use when adding new files, refactoring, creating build steps, or working on the project structure. Covers source layout, the build system, asset injection, Makefile targets, and install conventions."
applyTo: "**"
---

# Project Structure & Build System

## Source Layout

All development happens under `src/`. The `dist/` folder is build output only — never edit files there directly.

```
src/
├── globals.sh              # Top-level variables (VERSION, PORT, MODE, …)
├── lib/
│   ├── colors.sh           # Terminal color detection
│   ├── helpers.sh          # log, die, _mktmp, cleanup, traps
│   ├── usage.sh            # usage()
│   ├── args.sh             # Argument parsing
│   ├── validate.sh         # Input validation + pre-flight checks
│   ├── banner.sh           # Startup banner
│   └── serve.sh            # Runtime serve logic (contains @@INJECT@@ markers)
└── assets/
    ├── handler.sh          # socat per-connection HTTP handler
    ├── upload.py           # Multipart upload processor
    ├── server.py           # Python HTTP directory server
    └── web/
        ├── upload.html     # HTML skeleton (inject markers: @@CSS@@ / @@JS@@)
        ├── upload.css      # All styles — edited here, injected at build time
        └── upload.js       # All client JS — edited here, injected at build time
```

## Build System

The build process is: `build.sh` → `dist/<tool>` → `make install` → `/usr/local/bin/<tool>`.

**Never manually concatenate** source files. Always use `build.sh` to assemble.

```
make build      # runs build.sh → dist/expose
make install    # build + sudo install -m 755 dist/expose /usr/local/bin/expose
make uninstall  # sudo rm -f /usr/local/bin/expose
make clean      # rm -rf dist/
make run        # build + ./dist/expose $(ARGS)
```

Install target is always `/usr/local/bin/<tool>` (never `/usr/bin` or `~/.local/bin` unless explicitly requested).

## Asset Injection Markers

Assets are embedded verbatim into the built binary via marker substitution in `build.sh`.

### In `src/lib/serve.sh` (inside heredoc bodies):
```sh
cat > "$_UPLOAD_HTML" << 'UPLOADHTML'
@@INJECT:assets/web/upload.html@@
UPLOADHTML
```

### In `src/assets/web/upload.html` (within tags):
```html
<style>@@CSS@@</style>
<script>@@JS@@</script>
```

`build.sh` uses Python `str.replace()` to substitute markers — safe for multi-line content, no escaping needed.

## Adding a New Asset

1. Create the file under `src/assets/`
2. Add an `@@INJECT:assets/your-file@@` marker inside the relevant heredoc in `serve.sh`
3. `build.sh` resolves it automatically — no other changes needed

## Adding a New Source Module

1. Create `src/lib/newmodule.sh`
2. Add it to the assembly order in `build.sh` (the `for f in ...` loop), before `serve.sh`

## dist/ and .gitignore

`dist/` is always gitignored. The built binary is never committed. Commit `src/`, `build.sh`, and `Makefile`.

## build.sh Conventions

- Written in `bash` with `set -uo pipefail`
- Uses Python 3 (inline `python3 - args << 'PY'` pattern) for marker substitution
- Outputs a single executable at `dist/<tool>`, `chmod +x`
- Print `Building dist/<tool> …` at start, `  OK  dist/<tool>  (N bytes)` on success

## Makefile Conventions

```makefile
INSTALL_DIR ?= /usr/local/bin
BINARY      := expose
DIST        := dist/$(BINARY)

.DEFAULT_GOAL := build

.PHONY: build install uninstall clean run

# Usage: make run ARGS='"hello world"'
run: build
	./$(DIST) $(ARGS)
```

Always declare all targets as `.PHONY`. Default goal is `build`.
