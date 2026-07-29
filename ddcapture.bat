@echo off
setlocal EnableExtensions

REM ---------------------------------------------------------------------
REM  Atalho para rodar o coletor sem precisar lembrar do caminho do venv.
REM
REM      ddcapture.bat --validar
REM      ddcapture.bat --buscar "parte do titulo"
REM      ddcapture.bat --dashboard-id abc-def-ghi --dry-run
REM      ddcapture.bat --dashboard-id abc-def-ghi --from -1h
REM
REM  SOMENTE LEITURA: nada e criado, alterado ou apagado no Datadog.
REM ---------------------------------------------------------------------

REM Codepage UTF-8: sem isso os acentos da saida (Visao Geral, Latencia)
REM saem embaralhados no console do Windows.
chcp 65001 >nul 2>&1
set "PYTHONIOENCODING=utf-8"

REM Roda sempre a partir da pasta do projeto, mesmo se chamado de outro lugar.
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"

REM Sem argumentos = provavelmente duplo clique no Explorer. So nesse caso
REM vale pausar no fim, senao o console fecharia antes de dar para ler.
set "PAUSAR="
if "%~1"=="" set "PAUSAR=1"

if not exist "%PY%" goto :SEM_VENV
if not exist "%~dp0.env" goto :SEM_ENV

REM Sem argumentos, main.py decide: roda o dashboard do settings.local.yaml
REM se houver um configurado, ou mostra a ajuda se nao houver.
"%PY%" main.py %*
set "CODIGO=%ERRORLEVEL%"
if defined PAUSAR pause
exit /b %CODIGO%


:SEM_VENV
echo [ERRO] Ambiente virtual nao encontrado em .venv
echo.
echo Crie com:
echo     python -m venv .venv
echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
echo.
if defined PAUSAR pause
exit /b 2


:SEM_ENV
echo [ERRO] Arquivo .env nao encontrado.
echo.
echo Copie o template e preencha as chaves:
echo     copy .env.example .env
echo.
echo Precisa de DD_API_KEY, DD_APP_KEY e DD_SITE.
echo.
if defined PAUSAR pause
exit /b 2


