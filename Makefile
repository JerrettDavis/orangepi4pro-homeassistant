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

.PHONY: fleet-up fleet-status
fleet-up:
	$(PYTHON) scripts/paseo-fleet.py provision
	$(PYTHON) scripts/paseo-fleet.py register
	$(PYTHON) scripts/paseo-fleet.py workspaces --repos

fleet-status:
	$(PYTHON) scripts/paseo-fleet.py status
