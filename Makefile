# ex: set ts=8 noet:

all: resources test build

test:
	QT_QPA_PLATFORM=offscreen PYTHONPATH=src python tools/run_tests.py

resources:
	pyrcc5 -o src/labelimg/ui/generated_resources.py resources.qrc

build: clean-build
	python -m pip wheel . --no-deps --no-build-isolation

clean-build:
	rm -rf build src/*.egg-info

clean: clean-build
	rm -rf dist

.PHONY: all test resources build clean-build clean
