INSTALL_DIR ?= /usr/local/bin
BINARY      := expose
DIST        := dist/$(BINARY)

.DEFAULT_GOAL := build

.PHONY: build install uninstall clean run

build:
	@bash build.sh

install: build
	sudo install -m 755 $(DIST) $(INSTALL_DIR)/$(BINARY)
	@echo "Installed to $(INSTALL_DIR)/$(BINARY)"

uninstall:
	sudo rm -f $(INSTALL_DIR)/$(BINARY)
	@echo "Removed $(INSTALL_DIR)/$(BINARY)"

clean:
	rm -rf dist/
	@echo "Cleaned dist/"

# Usage: make run ARGS='"hello world"'
run: build
	./$(DIST) $(ARGS)
