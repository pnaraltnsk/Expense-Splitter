.PHONY: help install backend test

help:
	@echo "Expense Splitter commands:"
	@echo "  make install   Sync backend dependencies with uv"
	@echo "  make backend   Start the FastAPI development server"
	@echo "  make test      Run backend endpoint tests"

install:
	uv --directory backend sync

backend: install
	uv --directory backend run uvicorn app.main:app --reload

test: install
	uv --directory backend run pytest -q
