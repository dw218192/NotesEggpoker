@echo off

:: Change to the directory where pyproject.toml is located
cd /d "C:\Users\Administrator\Desktop\servers\NotesEggpoker\server"

:: Run the server using the poetry script defined in pyproject.toml
poetry run waitress-serve --port=8081 --url-scheme=https main:app
