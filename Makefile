SHELL := /bin/bash
.DEFAULT_GOAL := help

VENV    := .venv
BEHALF  := $(VENV)/bin/behalf
PERSONA ?=

.PHONY: help setup install index who note curate chat search preread agent \
        publish test up down logs clean nuke docker-build

help:
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk -F':.*?## ' '{printf "  \033[1m%-13s\033[0m %s\n", $$1, $$2}'

.env:
	@cp -n .env.example .env && echo "created .env — add your provider key"

$(VENV)/bin/activate: pyproject.toml
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip >/dev/null
	$(VENV)/bin/pip install -e ".[all,dev]"
	@touch $(VENV)/bin/activate

install: $(VENV)/bin/activate ## Create the venv and install behalf

setup: .env install index ## Clone to working store in one command
	@echo
	@$(BEHALF) who
	@echo
	@echo 'Ready. Try:  make note TEXT="batch three slipped a week"'

index: install ## Build or refresh the vector index
	@$(BEHALF) index

who: install ## Show the room, the turn order and who you are
	@$(BEHALF) who

note: install ## Capture an update:  make note TEXT="..."
	@$(BEHALF) note $(TEXT)

curate: install ## Fold pending captures into your ledger
	@$(BEHALF) curate

chat: install ## Interactive capture and lookup
	@$(BEHALF) chat

search: install ## Search your store:  make search Q="launch date"
	@$(BEHALF) search $(Q)

preread: install ## Print the current one-pager
	@$(BEHALF) preread

agent: install ## Join the room as one person:  make agent PERSONA=priya
	@$(BEHALF) agent $(if $(PERSONA),--persona $(PERSONA),) $(if $(SHARE),--share $(SHARE),)

publish: install ## Push the current pre-read to the shared Google Doc
	@$(BEHALF) publish $(if $(SHARE),--share $(SHARE),)

test: install ## Run the test suite
	@$(VENV)/bin/pytest -q

docker-build: .env ## Build the image
	docker compose build

up: .env ## Run your agent in a container:  make up PERSONA=priya
	PERSONA=$(PERSONA) docker compose up --build agent

down: ## Stop containers
	docker compose down --remove-orphans

logs: ## Follow container logs
	docker compose logs -f

clean: ## Remove generated state and output, keep the ledger
	rm -rf state out $(VENV) .pytest_cache
	find . -name __pycache__ -prune -exec rm -rf {} +

nuke: down clean ## Full reset including the image
	docker image rm behalf:local 2>/dev/null || true
