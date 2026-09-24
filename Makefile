PYTHON ?= python3
.PHONY: test validate-images smoke scan package

test:
	./scripts/test.sh

validate-images:
	./scripts/test.sh --images

smoke:
	./scripts/docker-smoke.sh

scan:
	$(PYTHON) scripts/scan-public.py

package: test scan
	$(PYTHON) scripts/package.py --output dist
