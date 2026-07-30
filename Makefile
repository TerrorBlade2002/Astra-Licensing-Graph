# Cross-platform convenience targets (mirrors scripts/*.ps1 for Windows users).
.PHONY: db install migrate seed run worker scheduler test lint type fmt check import-prototype

db:
	docker compose up -d db

install:
	pip install -e ".[dev]"

migrate:
	python -m alembic upgrade head

seed:
	python -m app.cli.seed_dev

run:
	uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

worker:
	python -m app.workers.runner --queues subscriptions,sync,ingestion

scheduler:
	python -m app.workers.scheduling

test:
	pytest --cov=app --cov-fail-under=63

lint:
	ruff format --check .
	ruff check .

type:
	mypy app

fmt:
	ruff format .
	ruff check --fix .

check: lint type test

import-prototype:
	python -m app.cli.import_prototype --root ./prototype-data --mailbox astralicensing@astraglobal.com
