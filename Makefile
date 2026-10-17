.PHONY: db-check

db-check:
	@echo "==> Validating single Alembic migration head..."
	python scripts/check_migrations.py
	@echo "==> Running migration integrity pytest..."
	pytest tests/test_alembic_single_head.py -q
	@echo "==> Checking schema drift with alembic check..."
	alembic check
	@echo "==> Running live DB metadata comparison test..."
	pytest tests/test_migrations_match_models.py -q
	@echo "==> All database checks passed successfully!"
