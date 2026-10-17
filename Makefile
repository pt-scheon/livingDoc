.PHONY: install dev run test e2e docker notes pack

install:
	pip install -r backend/requirements.txt

dev:
	pip install -r backend/requirements-dev.txt

run:
	cd backend && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

test:
	cd backend && python -m app.engine && python -m pytest -q tests

e2e:
	pip install playwright && playwright install chromium && python e2e/browser_smoke.py

docker:
	docker compose up -d --build

notes:
	python scripts/export_feedback.py

pack:
	python scripts/pack_frontend.py
