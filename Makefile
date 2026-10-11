# Top-level developer commands.
#   make test         C++ unit tests + quick perft + Python unit tests   (a couple of minutes: the C++ part takes seconds, the ~900 Python unit tests most of the time)
#   make test-all     everything, incl. verified perft and Python integration tests against the real engine (about 5 minutes)
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
