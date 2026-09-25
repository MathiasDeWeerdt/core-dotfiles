INSTALL_DIR ?= /usr/local/bin
BINARY      := expose
DIST        := dist/$(BINARY)
ONLINE      := dist/expose-online
PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
CLIENT_INSTALL_DIR ?= $(HOME)/.local/share/expose/clients

.DEFAULT_GOAL := build

.PHONY: build install uninstall clean run test console-clients install-console-clients

build:
	@bash build.sh

console-clients:
	@bash build-clients.sh

install-console-clients: console-clients
	@mkdir -p "$(CLIENT_INSTALL_DIR)"
	@cp dist/console-clients/* "$(CLIENT_INSTALL_DIR)/"

install: build
	sudo install -m 755 $(DIST) $(INSTALL_DIR)/$(BINARY)
	sudo install -m 755 $(ONLINE) $(INSTALL_DIR)/expose-online
	@echo "Installed expose and expose-online to $(INSTALL_DIR)"

uninstall:
	sudo rm -f $(INSTALL_DIR)/$(BINARY)
	sudo rm -f $(INSTALL_DIR)/expose-online
	@echo "Removed expose and expose-online from $(INSTALL_DIR)"

clean:
	rm -rf dist/
	@echo "Cleaned dist/"

# Usage: make run ARGS='"hello world"'
run: build
	./$(DIST) $(ARGS)

test: build
	@bash tests/tunnel-status.sh
	@bash tests/integration.sh
	@$(PYTHON) tests/features.py
