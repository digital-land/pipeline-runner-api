# =============================
# Utils
# =============================

server::
	python -m uvicorn application.app:app --reload --port=8080

# build docker image

# =============================
# Dependencies
# =============================

init::
	python -m pip install pip-tools
	make piptool-compile
	make dependencies
	make pre-commit-install

piptool-compile::
	python -m piptools compile --output-file=requirements/requirements.txt requirements/requirements.in
	python -m piptools compile --output-file=requirements/dev-requirements.txt requirements/dev-requirements.in

dependencies::
	pip-sync requirements/requirements.txt  requirements/dev-requirements.txt

pre-commit-install::
	pre-commit install

# =============================
# Linting
# =============================

lint:
	make black ./application
	python3 -m flake8 ./application
	make jslint

black-check:
	black --check .

black:
	python3 -m black .

jslint::
	npx eslint --ext .html,.js ./

jslint-fix::
	npx eslint --ext .html,.js ./ --fix

# =============================
# Testing
# =============================

test-acceptance:
	python -m playwright install chromium
	python -m pytest --md-report --md-report-color=never -p no:warnings tests/acceptance

test: test-unit test-integration

test-unit:
	python -m pytest --md-report --md-report-color=never --md-report-output=unit-tests.md tests/unit

test-integration:
	python -m pytest --md-report --md-report-color=never --md-report-output=integration-tests.md tests/integration

test-integration-docker:
	docker-compose run web python -m pytest tests/integration --junitxml=.junitxml/integration.xml $(PYTEST_RUNTIME_ARGS)

# Security
