.PHONY: setup data train seed run test

PYTHON := ./backend/.venv/bin/python
PIP := ./backend/.venv/bin/pip
PYTEST := ./backend/.venv/bin/pytest
UVICORN := ./backend/.venv/bin/uvicorn

setup:
	cd backend && $(PIP) install -r requirements.txt

data:
	cd backend && $(PYTHON) -m app.ml.generate_data

train:
	cd backend && $(PYTHON) -m app.ml.train

seed:
	cd backend && $(PYTHON) -m scripts.seed

run:
	cd backend && $(UVICORN) app.main:app --host 0.0.0.0 --port 8000 --reload

test:
	cd backend && $(PYTEST) -v

