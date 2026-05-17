.PHONY: install test compile notebook-validate build clean
install:
	python -m pip install -e .[dev,notebook]
test:
	PYTHONPATH=src python -m pytest -q
compile:
	PYTHONPATH=src python -m compileall src
notebook-validate:
	python -c "import nbformat; p='notebooks/camera_discovery_live_test.ipynb'; nb=nbformat.read(p, as_version=4); nbformat.validate(nb); print('Notebook validation passed:', p)"
build:
	python -m pip install build
	python -m build
clean:
	rm -rf build dist *.egg-info .pytest_cache
