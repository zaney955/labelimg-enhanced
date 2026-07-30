# ex: set ts=8 noet:

all: resources test build

test:
	QT_QPA_PLATFORM=offscreen PYTHONPATH=src python tools/run_tests.py

resources:
	pyrcc5 -o src/labelimg/resources.py resources.qrc

build:
	python -m pip wheel . --no-deps --no-build-isolation

clean:
	rm -rf dist build src/*.egg-info

.PHONY: all test resources build clean
