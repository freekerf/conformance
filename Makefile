# FreeKerf conformance suite (LaserGRBL characterization). Run from the repository root.
# Artifacts live in ~/.cache/freekerf-conformance (override with LASERGRBL_BUILD_DIR / LASERGRBL_COV_DIR).

BUILD_DIR ?= $(HOME)/.cache/freekerf-conformance/build
COV_DIR   ?= $(HOME)/.cache/freekerf-conformance/coverage
export LASERGRBL_BUILD_DIR := $(BUILD_DIR)
export LASERGRBL_COV_DIR   := $(COV_DIR)
PYTEST_ARGS ?=
REPORT_DIR ?= coverage-report

.PHONY: all setup build test test-rust coverage coverage-report golden clean

all: test

setup:
	uv sync

build:
	./scripts/build_lasergrbl.sh

test: build
	uv run pytest $(PYTEST_ARGS)

# FreeKerf (Rust): the portable layers against `freekerf` (FREEKERF_BIN, default on the PATH).
# Needs neither Mono nor LASERGRBL_REPO.
test-rust:
	LASERGRBL_HOST=rust uv run pytest tests/protocol tests/golden/test_golden.py $(PYTEST_ARGS)

# build -> instrument (AltCover) -> pytest on the instrumented exe -> report filtered to scope.toml
coverage: build
	./scripts/instrument.sh
	cp $(COV_DIR)/coverage.pristine.xml $(COV_DIR)/coverage.xml
	LASERGRBL_BIN_DIR=$(COV_DIR)/instr LASERGRBL_COVERAGE=1 uv run pytest $(PYTEST_ARGS)
	$(MAKE) coverage-report

coverage-report:
	python3 scripts/coverage_report.py $(COV_DIR)/coverage.xml $(REPORT_DIR) --uncovered

golden: build
	uv run pytest tests/golden --update-golden

clean:
	rm -rf $(BUILD_DIR) $(COV_DIR) $(REPORT_DIR) .pytest_cache
