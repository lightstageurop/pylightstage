# Contributing

## Install (dev) and test

```shell
# Install as editable, and install dev dependencies (eg. pytest)
pip install -e ".[dev]"
# Run default tests
pytest
# Run tests with real lsserver,
pytest -m "integration"
# Or, run all tests
pytest -m ""
```
