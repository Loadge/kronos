.PHONY: install test lint format seed migrate revision run build up down logs shell clean

PY ?= python
PIP ?= pip
APP_PORT ?= 8765

## install — install dev dependencies into the current environment
install:
	$(PIP) install -r requirements-dev.txt

## test — run the full pytest suite
test:
	pytest

## lint — ruff check + format --check
lint:
	ruff check .
	ruff format --check .

## format — apply ruff autoformat
format:
	ruff format .
	ruff check --fix .

## seed — populate the DB with ~3 months of sample data
seed:
	$(PY) backend/seed.py

## migrate — apply Alembic migrations up to head
migrate:
	alembic upgrade head

## revision — create a new Alembic revision: make revision MSG="add foo column"
revision:
	alembic revision --autogenerate -m "$(MSG)"

## run — start the dev server with hot reload on localhost:$(APP_PORT)
run:
	$(PY) -m uvicorn app.main:app --reload --host 0.0.0.0 --port $(APP_PORT) --app-dir backend

## build / up / down / logs — Docker compose helpers
build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

shell:
	docker compose exec kronos /bin/bash

## clean — remove caches and pyc files (keeps data/)
clean:
	rm -rf .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
