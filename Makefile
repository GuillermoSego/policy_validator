.PHONY: install lint format test run oracle ablation crossmodel baseline evaluate viewer demo all

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

crossmodel:
	uv run validator crossmodel

baseline:
	uv run validator baseline

evaluate:
	uv run validator evaluate

viewer:
	uv run streamlit run app/viewer.py

demo:
	uv run validator demo tour

all: run oracle baseline evaluate
