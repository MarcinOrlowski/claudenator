##################################################################################
#
# Claudenator by Marcin Orlowski
# The only Claude Code session manager you need.
#
# @author    Marcin Orlowski <mail@marcinOrlowski.com>
# Copyright  ©2026 Marcin Orlowski <MarcinOrlowski.com>
# @link      https://github.com/MarcinOrlowski/claudenator
#
##################################################################################

PYTHON ?= python3
# For a "uv" managed venv, which has no pip, use: make tools PIP="uv pip"
PIP ?= $(PYTHON) -m pip

.DEFAULT_GOAL := help

# The targets run in order even with "make -j".
.NOTPARALLEL:

.PHONY: help tools clean build check testpypi publish

help:  ## Show this help
	@grep -E '^[a-z][a-z-]*:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

tools:  ## Install the build and release tools
	$(PIP) install --upgrade -e ".[release]"

clean:  ## Remove the build artifacts
	rm -rf build/ dist/ *.egg-info/

build: clean  ## Build the sdist and the wheel into "dist/"
	$(PYTHON) -m build

check:  ## Validate the artifacts in "dist/"
	$(PYTHON) -m twine check --strict dist/*

testpypi: build check  ## Build, then upload to TestPyPI
	$(PYTHON) -m twine upload --repository testpypi dist/*

publish: build check  ## Build, then upload to PyPI
	$(PYTHON) -m twine upload dist/*
