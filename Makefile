# Top-level developer commands.
#   make test         C++ unit tests + quick perft + Python unit tests   (fast, a few seconds)
#   make test-all     everything, incl. verified perft and Python integration tests against the real engine (~1.5 min)
#   make test-deep    deep perft suite (~600M nodes)
PY ?= .venv/bin/python

test:
	$(MAKE) -C engine test
	$(PY) -m pytest tests/unit -q -m "not slow"

test-all:
	$(MAKE) -C engine test test-verify
	$(PY) -m pytest -q

test-deep:
	$(MAKE) -C engine test-deep

.PHONY: test test-all test-deep
