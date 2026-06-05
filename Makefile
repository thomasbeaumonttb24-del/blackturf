# BlackTurf — Makefile
# Usage: make [target]

.PHONY: up down dev test test-ml seed-model logs clean

## ─── Infrastructure ──────────────────────────────────────────────────────────

up:
	docker-compose up -d --build

down:
	docker-compose down

dev:
	docker-compose up db redis api frontend

logs:
	docker-compose logs -f api

## ─── Tests ───────────────────────────────────────────────────────────────────

test:
	docker-compose exec api pytest tests/ -v --tb=short

test-ml:
	docker-compose exec api pytest tests/test_ml_units.py -v --tb=short

test-health:
	docker-compose exec api pytest tests/test_health.py -v

## ─── ML ──────────────────────────────────────────────────────────────────────

seed-model:
	docker-compose exec api python scripts/seed_model.py --samples 5000 --deploy

seed-model-local:
	cd backend && python scripts/seed_model.py --samples 3000 --deploy

## ─── DB ──────────────────────────────────────────────────────────────────────

migrate:
	docker-compose exec api alembic upgrade head

migrate-down:
	docker-compose exec api alembic downgrade -1

## ─── Frontend ────────────────────────────────────────────────────────────────

frontend-dev:
	cd frontend && npm run dev

frontend-build:
	cd frontend && npm run build

## ─── Cleanup ──────────────────────────────────────────────────────────────────

clean:
	docker-compose down -v --remove-orphans
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true

## ─── Helpers ──────────────────────────────────────────────────────────────────

help:
	@echo ""
	@echo "  BlackTurf — Commandes disponibles"
	@echo "  ─────────────────────────────────────────────"
	@echo "  make up           → Lancer tous les services"
	@echo "  make dev          → Lancer en mode développement (db/redis/api/frontend)"
	@echo "  make test         → Tous les tests"
	@echo "  make test-ml      → Tests ML unitaires uniquement"
	@echo "  make seed-model   → Entraîner le modèle initial (données synthétiques)"
	@echo "  make migrate      → Appliquer les migrations DB"
	@echo "  make logs         → Logs de l'API"
	@echo "  make clean        → Nettoyage complet"
	@echo ""
