---
description: "Source layout, build outputs, asset injection, installation, and tests."
applyTo: "**"
---

# Source and build conventions

Read `expose/AGENTS.md` for architecture and security boundaries. Develop in
`src/`; never hand-edit generated executables.

- `globals.sh`: defaults and version.
- `lib/operator.sh`: existing-instance CLI dispatch before `args.sh`; embeds
  `assets/operator.py`. Other modules handle argument parsing, validation,
  banners, cleanup, and serving.
- `assets/server.py`: shared HTTP backend, authentication, and local descriptors.
- `assets/consoles.py`: connector sessions, tickets, SOCKS, and callbacks.
- `connector/`: native Go PTY/ConPTY connector and security tests.
- `assets/web/`: self-contained UI sources and pinned terminal vendor assets.
- `expose-online.sh`: private configuration and SSH reverse-tunnel wrapper.
- `tests/`: tunnel, feature, integration, and operator CLI tests.
- `playground/` and `playground.sh`: isolated Docker tests and interactive lab.

`build.sh` assembles modules and resolves `@@INJECT:assets/<path>@@` markers in
both operator and serve modules. HTML markers inline CSS, JavaScript, and terminal
assets. New modules must be added to the assembly order explicitly. Failed builds
must preserve the last good output; unchanged builds must preserve file contents.

```bash
make build                     # dist/expose and dist/expose-online
make install                   # both scripts; INSTALL_DIR defaults /usr/local/bin
make install-console-clients    # six targets; requires Go 1.26+
make console-clients test       # full expose suite
./playground.sh test            # non-root, offline Docker suite
make uninstall                 # both installed scripts
make clean                     # generated dist/ only
```

`dist/` is ignored. The parent dotfiles repository intentionally tracks generated
copies under `local-bin/.local/bin/`. Refresh those from successful builds via
its deployment helper or `install -C -m755`. The parent installs and verifies
`/usr/local/bin` too, preventing an older system copy from shadowing it.
Optional installation directories are supported; keep make targets `.PHONY`.

The Docker build context is deny-by-default. Never add host home directories,
credentials, Docker socket mounts, published ports, or external networking to the
playground. Runtime tickets, cookies, private descriptors, and request captures
remain outside Git. Keep legacy `old_expose` unchanged as a reference.
