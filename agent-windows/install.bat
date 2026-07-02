@echo off
REM Endpoint Central Agent — Windows installer
REM Run as Administrator

SET INSTALL_DIR=C:\ProgramData\EndpointCentral
SET AGENT_DIR=%INSTALL_DIR%\agent

echo [*] Creating install directory...
mkdir "%AGENT_DIR%" 2>nul
mkdir "%INSTALL_DIR%\logs" 2>nul

echo [*] Copying agent files...
copy agent.py "%AGENT_DIR%\agent.py"
copy requirements.txt "%AGENT_DIR%\requirements.txt"
copy agent_config.env "%AGENT_DIR%\agent_config.env" 2>nul

echo [*] Installing Python dependencies...
pip install -r "%AGENT_DIR%\requirements.txt"

echo [*] Installing Windows Service...
cd "%AGENT_DIR%"
python agent.py install

echo [*] Starting service...
net start EndpointCentralAgent

echo [+] Endpoint Central Agent installed and started.
pause
