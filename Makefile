SHELL := /bin/bash
.DEFAULT_GOAL := help

VENV    := .venv
PY      := $(VENV)/bin/python
BEHALF  := $(VENV)/bin/behalf
AGENTS  ?= 3

.PHONY: help setup install index roster note chat curate search agent scale \
        up down logs clean nuke test docker-build docker-scale

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk -F':.*?## ' '{printf "  \033[1m%-14s\033[0m %s\n", $$1, $$2}'

.env:
	@cp -n .env.example .env && echo "created .env — add a key if you have one"

$(VENV)/bin/activate: pyproject.toml
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip >/dev/null
	$(VENV)/bin/pip install -e ".[all,dev]"
	@touch $(VENV)/bin/activate

install: $(VENV)/bin/activate ## Create the venv and install behalf

setup: .env install index ## One command from clone to working store
	@echo
	@$(BEHALF) roster
	@echo
	@echo "Ready. Try:  make note TEXT=\"batch three slipped a week\""

index: install ## Build or refresh the vector index
	@$(BEHALF) index

roster: install ## Show the configured room and agents
	@$(BEHALF) roster

note: install ## Capture an update:  make note TEXT="..."
	@$(BEHALF) note $(TEXT)

curate: install ## Fold pending captures into the ledger
	@$(BEHALF) curate

chat: install ## Interactive capture and lookup
	@$(BEHALF) chat

search: install ## Search the store:  make search Q="launch date"
	@$(BEHALF) search $(Q)

preread: install ## Print the current one-page pre-read
	@$(BEHALF) preread

agent: install ## Run just your own agent (the `me` key in config.yaml)
	@$(BEHALF) agent

scale: install ## Local scaling test:  make scale AGENTS=5
	@$(BEHALF) scale --agents $(AGENTS)

test: install ## Run the test suite
	@$(VENV)/bin/pytest -q

docker-build: .env ## Build the image
	docker compose build

up: .env ## Run the room in containers:  make up AGENTS=5
	docker compose up --build --scale agent=$(AGENTS) --abort-on-container-exit

down: ## Stop containers and remove the state volume
	docker compose down --volumes --remove-orphans

logs: ## Follow container logs
	docker compose logs -f

clean: ## Remove generated state and output, keep the ledger
	rm -rf state out $(VENV) .pytest_cache
	find . -name __pycache__ -prune -exec rm -rf {} +

nuke: down clean ## Full reset including containers and volumes
	docker image rm behalf:local 2>/dev/null || true
