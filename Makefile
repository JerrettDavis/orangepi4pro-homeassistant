PYTHON ?= python3
.PHONY: test smoke scan package

test:
	./scripts/test.sh -q

smoke:
	./scripts/docker-smoke.sh

scan:
	$(PYTHON) scripts/scan-public.py

package: test scan
	$(PYTHON) scripts/package.py --output dist
