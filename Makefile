.PHONY: install test preview docs

install:
	cd apps/portal && uv sync --locked --extra test --no-install-project --no-build
	cd apps/portal && npm ci

preview: install
	cd apps/portal && npm run build
	cd apps/portal && PYTHONPATH=tests:../../sandbox-images/common-tools PORTAL_PREVIEW_ORIGIN=http://127.0.0.1:4193 uv run --locked --no-sync uvicorn preview:app --host 127.0.0.1 --port 4193

test: install
	python3 scripts/check-export.py
	cd apps/portal && uv run --locked --no-sync python -m unittest discover -s ../../scripts/tests
	helm dependency build charts/caipe-sandbox --skip-refresh
	cd apps/portal && uv run --locked --no-sync python -m pytest -q
	cd apps/portal && npm test && npm run build

docs:
	cd docs && npm ci --ignore-scripts && npm test && npm run build
