.PHONY: install lint format test run oracle ablation baseline evaluate viewer all

install:
	uv sync

lint:
	uv run ruff check . && uv run ruff format --check .

format:
	uv run ruff format . && uv run ruff check --fix .

test:
	uv run pytest -q

run:
	uv run validator run

oracle:
	uv run validator oracle

ablation:
	uv run validator ablation

baseline:
	uv run validator baseline

evaluate:
	uv run validator evaluate

viewer:
	uv run streamlit run app/viewer.py

all: run oracle baseline evaluate
