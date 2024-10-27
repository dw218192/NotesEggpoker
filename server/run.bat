@echo off

pushd %~dp0

:: Run the server using the poetry script defined in pyproject.toml
poetry run waitress-serve --port=8081 --url-scheme=https main:app

popd