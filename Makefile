.PHONY: setup install clean

# Python version and venv directory
VENV := .venv
PYTHON := python3
PIP := $(VENV)/bin/pip
PYTHON_VENV := $(VENV)/bin/python

setup:
	$(PYTHON) -m venv $(VENV)
	$(PYTHON_VENV) -m pip install -r requirements.txt

clean:
	rm -rf $(VENV)
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

run:
	$(PYTHON_VENV) bot.py

# This is obsolete since we can use the Developer token to get the access token, so we don't need an OAuth flow
run-oauth-callback-api:
	$(PYTHON_VENV) oauth_server.py
