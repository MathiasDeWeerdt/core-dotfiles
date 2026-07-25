INSTALL_DIR ?= /usr/local/bin
BINARY      := expose
DIST        := dist/$(BINARY)
ONLINE      := dist/expose-online

.DEFAULT_GOAL := build

.PHONY: build install uninstall clean run test

build:
	@bash build.sh

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
	@bash tests/integration.sh
