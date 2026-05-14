.PHONY: help venv lock install lint format type test check clean

PY := .venv/bin/python
PIP := .venv/bin/pip
RUFF := .venv/bin/ruff
MYPY := .venv/bin/mypy
PYTEST := .venv/bin/pytest

help:
	@echo "Available targets:"
	@echo "  venv     - Create Python 3.14 venv in .venv/"
	@echo "  lock     - Re-generate requirements-dev.txt from .in (pip-compile)"
	@echo "  install  - Install pinned, hash-verified dev dependencies"
	@echo "  lint     - Run ruff linter"
	@echo "  format   - Run ruff format"
	@echo "  type     - Run mypy strict"
	@echo "  test     - Run pytest"
	@echo "  check    - lint + type + test"
	@echo "  clean    - Remove .venv and caches"

venv:
	python3.14 -m venv .venv
	$(PIP) install --upgrade pip pip-tools

lock:
	$(PY) -m piptools compile --generate-hashes --output-file=requirements-dev.txt requirements-dev.in

install:
	$(PIP) install --require-hashes -r requirements-dev.txt

lint:
	$(RUFF) check .

format:
	$(RUFF) format .

type:
	$(MYPY)

test:
	$(PYTEST)

check: lint type test

clean:
	rm -rf .venv .pytest_cache .mypy_cache .ruff_cache __pycache__
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
