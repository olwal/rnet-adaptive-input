@echo off
REM Windows shim. The implementation is cross-platform Python in tools/rnet.py.
python "%~dp0tools\rnet.py" %*
