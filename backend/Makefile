.PHONY: setup data train seed run test

PYTHON := ./.venv/bin/python
PIP := ./.venv/bin/pip
PYTEST := ./.venv/bin/pytest
UVICORN := ./.venv/bin/uvicorn

setup:
	$(PIP) install -r requirements.txt

data:
	$(PYTHON) -m app.ml.generate_data

train:
	$(PYTHON) -m app.ml.train

seed:
	$(PYTHON) -m scripts.seed

run:
	$(UVICORN) app.main:app --host 0.0.0.0 --port 8000 --reload

test:
	$(PYTEST) -v

