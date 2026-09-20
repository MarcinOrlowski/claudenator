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

.PHONY: help tools clean build check testpypi publish release

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

##################################################################################
#
# The "make release" reads __version__ from the package and creates new tag.
# The tag is what starts the upload to PyPI, and only a tag of the form "vX.Y.Z"
# does, see ".github/workflows/pypi-release.yaml".
#
# Script sits in a "define" block (single shell, no line continuations).
# Make eats a single "$" => so they are written as "$$".
#
##################################################################################

define RELEASE_SCRIPT
set -euo pipefail

VERSION_FILE="claudenator/__init__.py"
RELEASE_BRANCH="master"

fail() {
  echo "*********************************************************"
  echo "* FIXME! $${1}"
  shift
  for msg in "$${@}"; do
    echo "* $${msg}"
  done
  echo "*********************************************************"
  exit 1
}

if ! branch="$$(git symbolic-ref --quiet --short HEAD)"; then
  branch="a detached HEAD"
fi

if [[ "$${branch}" != "$${RELEASE_BRANCH}" ]]; then
  fail "Your working branch is  '$${branch}' but expected '$${RELEASE_BRANCH}'." \
    "" \
    "Switch to correct branch for release:" \
    "" \
    "  git checkout $${RELEASE_BRANCH} && git pull"
fi

if [[ -n "$$(git status --porcelain --untracked-files=no)" ]]; then
  fail "The working tree holds uncommited changes." \
    "" \
    "Commit it, stash or throw away, then run 'make release' again." \
    "" \
    "  git status"
fi

if ! version="$$(
  grep -oE '^__version__[[:space:]]*=[[:space:]]*"[^"]+"' "$${VERSION_FILE}" \
    | grep -oE '"[^"]+"' \
    | tr -d '"'
)"; then
  fail "No __version__ found in $${VERSION_FILE}." \
    "" \
    "The line it looks for is:" \
    "" \
    '  __version__ = "1.2.3"'
fi

if [[ ! "$${version}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$$ ]]; then
  fail "__version__ is '$${version}', which is not a valid format." \
    "" \
    "A release version must be X.Y.Z format:" \
    "" \
    '  __version__ = "1.2.3"' \
    "" \
    "Set it in $${VERSION_FILE}, commit, then run 'make release' again."
fi

tag="v$${version}"

# A version goes out once (no versoin overwrite on PyPI)
for name in "$${tag}" "$${version}"; do
  if git rev-parse --quiet --verify "refs/tags/$${name}" >/dev/null; then
    fail "Tag '$${name}' exists, so $${version} is already taken." \
      "" \
      "Bump __version__ in $${VERSION_FILE}, commit then run 'make release' again." \
      "To drop that local tag instead:" \
      "" \
      "  git tag --delete $${name}"
  fi

  # "--exit-code" 2 == "no such tag"
  found=0
  git ls-remote --exit-code --quiet --tags origin "refs/tags/$${name}" >/dev/null \
    || found="$${?}"

  if [[ "$${found}" -ne 0 && "$${found}" -ne 2 ]]; then
    fail "Could not read the tags of 'origin' (git ls-remote said $${found})."
  fi

  if [[ "$${found}" -eq 0 ]]; then
    fail "Tag '$${name}' is on 'origin' already, so $${version} went out." \
      "" \
      "Bump __version__ in $${VERSION_FILE} and run 'make release' again."
  fi
done

if ! remote_head="$$(
  git ls-remote --exit-code origin "refs/heads/$${RELEASE_BRANCH}" | cut -f1
)"; then
  fail "Could not read '$${RELEASE_BRANCH}' from 'origin'."
fi

head="$$(git rev-parse HEAD)"
if [[ "$${remote_head}" != "$${head}" ]]; then
  fail "'$${RELEASE_BRANCH}' local and on 'origin' are not the same commit." \
    "" \
    "  local : $${head}" \
    "  origin: $${remote_head}" \
    "" \
    "The PyPI upload uses a tag from 'origin/$${RELEASE_BRANCH}', sync repo:" \
    "" \
    "  git pull && git push"
fi

echo "Releasing $${version} from '$${RELEASE_BRANCH}':"
echo "  tag:     $${tag}  (annotated)"
echo "  message: Release $${tag}"
echo "  commit:  $$(git rev-parse --short HEAD)"
echo "  push to: origin"
echo

git tag --annotate "$${tag}" --message "Release $${tag}"

if ! git push origin "refs/tags/$${tag}"; then
  git tag --delete "$${tag}"
  fail "The push of '$${tag}' failed. Tag was dropped here too." \
    "" \
    "No changes on 'origin'. Fix the cause, then run 'make release' again."
fi

echo
echo "Tag $${tag} is on 'origin'."
echo "The 'Release: Publish to PyPI' workflow takes it from here. Watch it"
echo "under 'Actions' on GitHub."
endef
export RELEASE_SCRIPT

release:  ## Tag the version and push that tag which will trigger pypi release
	@bash -c "$$RELEASE_SCRIPT"
