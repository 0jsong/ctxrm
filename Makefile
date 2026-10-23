PREFIX ?= $(HOME)/.local
PYTHON ?= python3

.PHONY: install test

install:
	install -d "$(DESTDIR)$(PREFIX)/bin"
	install -m 0755 kubectl-ctxrm "$(DESTDIR)$(PREFIX)/bin/kubectl-ctxrm"

test:
	$(PYTHON) -m pytest -q
