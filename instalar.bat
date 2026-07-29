@echo off
setlocal EnableExtensions

REM ---------------------------------------------------------------------
REM  Prepara o ambiente do ddcapture do zero.
REM
REM      instalar.bat              instala (reaproveita o .venv se ja existir)
REM      instalar.bat --recriar    apaga o .venv e refaz do zero
REM
REM  Idempotente: rodar de novo nao estraga nada e nunca sobrescreve o .env.
REM ---------------------------------------------------------------------

chcp 65001 >nul 2>&1
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "RECRIAR="
if /i "%~1"=="--recriar" set "RECRIAR=1"

echo.
echo ============================================================
echo   Instalacao do ddcapture
echo ============================================================
echo.

REM --- [1/5] Localizar um Python utilizavel -----------------------------
echo [1/5] Procurando Python...

set "PY_BASE="
py -3 --version >nul 2>&1
if not errorlevel 1 (
    set "PY_BASE=py -3"
    goto :PYTHON_ENCONTRADO
)
python --version >nul 2>&1
if not errorlevel 1 (
    set "PY_BASE=python"
    goto :PYTHON_ENCONTRADO
)
goto :SEM_PYTHON

:PYTHON_ENCONTRADO
for /f "delims=" %%v in ('%PY_BASE% --version 2^>^&1') do set "PY_VERSAO=%%v"

REM O projeto usa sintaxe de tipos de 3.10+ (X ^| Y). Barrar aqui e melhor
REM do que deixar estourar um SyntaxError no meio do primeiro uso.
%PY_BASE% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 goto :PYTHON_ANTIGO

echo       %PY_VERSAO%  ^(ok^)
echo.

REM --- [2/5] Ambiente virtual ------------------------------------------
echo [2/5] Ambiente virtual...

if defined RECRIAR (
    if exist ".venv" (
        echo       --recriar: removendo o .venv atual
        rmdir /s /q ".venv"
    )
)

if exist ".venv\Scripts\python.exe" (
    echo       .venv ja existe, reaproveitando
) else (
    echo       criando .venv ...
    %PY_BASE% -m venv .venv
    if errorlevel 1 goto :ERRO_VENV
    echo       .venv criado
)

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" goto :ERRO_VENV
echo.

REM --- [3/5] Dependencias ----------------------------------------------
echo [3/5] Instalando dependencias ^(pode levar um minuto^)...

"%PY%" -m pip install --quiet --upgrade pip
if errorlevel 1 goto :ERRO_PIP

"%PY%" -m pip install --quiet -r requirements.txt
if errorlevel 1 goto :ERRO_PIP

"%PY%" -c "import requests, yaml, openpyxl, dotenv, pytest" 2>nul
if errorlevel 1 goto :ERRO_PIP

echo       requests, PyYAML, openpyxl, python-dotenv, pytest
echo.

REM --- [4/5] Arquivo .env ----------------------------------------------
echo [4/5] Configuracao...

set "ENV_NOVO="
if exist ".env" (
    echo       .env ja existe, preservado
) else (
    copy /y ".env.example" ".env" >nul
    if errorlevel 1 goto :ERRO_ENV
    set "ENV_NOVO=1"
    echo       .env criado a partir do template
)

REM Uma linha "DD_API_KEY=" sem nada depois significa nao preenchido.
findstr /r /c:"^DD_API_KEY=." ".env" >nul 2>&1
if errorlevel 1 set "ENV_NOVO=1"
findstr /r /c:"^DD_APP_KEY=." ".env" >nul 2>&1
if errorlevel 1 set "ENV_NOVO=1"
echo.

REM --- [5/5] Testes -----------------------------------------------------
echo [5/5] Rodando os testes ^(sem rede^)...
"%PY%" -m pytest -q --no-header
if errorlevel 1 goto :ERRO_TESTES
echo.

if defined ENV_NOVO goto :FALTA_CONFIGURAR

REM Credenciais ja preenchidas: confirma que funcionam de verdade.
echo ------------------------------------------------------------
echo   Validando as credenciais do .env
echo ------------------------------------------------------------
"%PY%" main.py --validar
if errorlevel 1 goto :CREDENCIAL_RUIM

echo.
echo ============================================================
echo   Instalacao concluida.
echo ============================================================
echo.
echo   Proximo passo:
echo       ddcapture.bat --buscar "parte do titulo"
echo.
goto :FIM_OK


:FALTA_CONFIGURAR
echo ============================================================
echo   Ambiente pronto - falta preencher as credenciais.
echo ============================================================
echo.
echo   Abra o arquivo .env e preencha:
echo.
echo       DD_API_KEY   Organization Settings ^> API Keys
echo       DD_APP_KEY   Organization Settings ^> Application Keys
echo                    ^(escopo dashboards_read; para logs/SLO adicione
echo                     logs_read_data, slos_read e monitors_read^)
echo       DD_SITE      datadoghq.com, us3.datadoghq.com, datadoghq.eu, ...
echo.
echo   Depois confirme com:
echo       ddcapture.bat --validar
echo.
goto :FIM_OK


:SEM_PYTHON
echo.
echo   [ERRO] Python nao encontrado no PATH.
echo.
echo   Instale a versao 3.10 ou superior em https://python.org/downloads
echo   e marque "Add Python to PATH" durante a instalacao.
echo.
goto :FIM_ERRO


:PYTHON_ANTIGO
echo.
echo   [ERRO] Python muito antigo: %PY_VERSAO%
echo.
echo   O projeto precisa de 3.10 ou superior.
echo.
goto :FIM_ERRO


:ERRO_VENV
echo.
echo   [ERRO] Nao foi possivel criar o ambiente virtual em .venv
echo.
echo   Tente rodar manualmente para ver a mensagem completa:
echo       %PY_BASE% -m venv .venv
echo.
goto :FIM_ERRO


:ERRO_PIP
echo.
echo   [ERRO] Falha ao instalar as dependencias.
echo.
echo   Normalmente e rede ^(proxy ou firewall bloqueando o PyPI^).
echo   Rode sem o --quiet para ver o erro completo:
echo       .venv\Scripts\python.exe -m pip install -r requirements.txt
echo.
goto :FIM_ERRO


:ERRO_ENV
echo.
echo   [ERRO] Nao foi possivel criar o .env a partir do .env.example
echo   Verifique se o .env.example existe nesta pasta.
echo.
goto :FIM_ERRO


:ERRO_TESTES
echo.
echo   [ERRO] Os testes falharam - a instalacao ficou inconsistente.
echo   Rode para ver o detalhe:
echo       .venv\Scripts\python.exe -m pytest
echo.
goto :FIM_ERRO


:CREDENCIAL_RUIM
echo.
echo   As dependencias estao ok, mas as credenciais do .env foram
echo   rejeitadas. Corrija o .env e rode:
echo       ddcapture.bat --validar
echo.
goto :FIM_ERRO


:FIM_OK
pause
exit /b 0

:FIM_ERRO
pause
exit /b 1
