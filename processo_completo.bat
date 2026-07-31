@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ---------------------------------------------------------------------
REM  Processo completo, de ponta a ponta:
REM
REM     1. importa as tabelas de preco (CSV) para precos.sqlite
REM     2. captura o dashboard, uma vez por emissor
REM     3. gera a analise de custo, uma planilha por emissor
REM
REM      processo_completo.bat
REM      processo_completo.bat --limpar
REM      processo_completo.bat --from 01/06/2026 --to 30/06/2026
REM      processo_completo.bat --limpar --from 01/06/2026 --to 30/06/2026
REM
REM  --limpar apaga out\ e as planilhas de analise antes de comecar.
REM  Os demais argumentos vao para o coletor.
REM ---------------------------------------------------------------------

chcp 65001 >nul 2>&1
set "PYTHONIOENCODING=utf-8"

REM A raiz precisa ser guardada ANTES de qualquer shift: o shift desloca
REM tambem o %0, e a partir dai %~dp0 nao aponta mais para este script.
set "RAIZ=%~dp0"
cd /d "%RAIZ%"

set "PY=%RAIZ%.venv\Scripts\python.exe"

REM Separa --limpar do resto; o resto e repassado a captura.
set "LIMPAR="
set "EXTRA="
:PARSE
if "%~1"=="" goto :PARSE_FIM
if /i "%~1"=="--limpar" (
    set "LIMPAR=1"
) else (
    set "EXTRA=!EXTRA! %1"
)
shift
goto :PARSE
:PARSE_FIM

echo.
echo ============================================================
echo   Processo completo
echo ============================================================
echo.

REM --- Pre-requisitos, antes de gastar minutos na captura --------------
if not exist "%PY%" goto :SEM_VENV
if not exist "%RAIZ%.env" goto :SEM_ENV
if not exist "%RAIZ%config\emissores.txt" goto :SEM_EMISSORES

REM A analise precisa do banco de precos. Se nao ha banco nem CSV para
REM gerar um, melhor parar agora do que depois da captura.
if not exist "%RAIZ%precos.sqlite" (
    if not exist "%RAIZ%tabela_precos_sic.csv" goto :SEM_PRECOS
)

if defined LIMPAR (
    echo [0/3] Limpando saidas anteriores...
    if exist "%RAIZ%out" del /q "%RAIZ%out\*" >nul 2>&1
    del /q "%RAIZ%analise_custos_*.xlsx" >nul 2>&1
    echo       out\ e analise_custos_*.xlsx limpos
    echo.
)

REM --- 1/3  Precos ------------------------------------------------------
echo [1/3] Importando tabelas de preco...
if exist "%RAIZ%tabela_precos_sic.csv" (
    "%PY%" importar_precos.py
    if errorlevel 1 goto :ERRO_PRECOS
) else (
    echo       CSV nao encontrado - mantendo o precos.sqlite existente
)
echo.

REM --- 2/3  Captura -----------------------------------------------------
echo [2/3] Capturando o dashboard por emissor...
echo       ^(alguns minutos: sao ~145 queries por emissor^)
call "%RAIZ%3_capturar_emissores.bat"!EXTRA!
if errorlevel 1 goto :ERRO_CAPTURA

REM --- 3/3  Analise -----------------------------------------------------
echo [3/3] Gerando a analise de custo...
"%PY%" analise_custos.py
if errorlevel 1 goto :ERRO_ANALISE

echo.
echo ============================================================
echo   Processo concluido
echo ============================================================
echo.
echo   Capturas          : out\
echo   Analise de custo  : analise_custos_^<codigo^>.xlsx
echo.
goto :FIM_OK


:SEM_VENV
echo   [ERRO] Ambiente virtual nao encontrado.
echo   Rode primeiro: 1_instalar.bat
goto :FIM_ERRO

:SEM_ENV
echo   [ERRO] Arquivo .env nao encontrado.
echo   Copie .env.example para .env e preencha as chaves.
goto :FIM_ERRO

:SEM_EMISSORES
echo   [ERRO] config\emissores.txt nao encontrado.
echo.
echo   Crie a lista uma vez:
echo       copy config\emissores.txt.example config\emissores.txt
echo.
echo   e preencha com os codigos da sua carteira.
goto :FIM_ERRO

:SEM_PRECOS
echo   [ERRO] Sem precos: nao existe precos.sqlite nem tabela_precos_sic.csv.
echo.
echo   A analise de custo precisa das tabelas de preco. Gere os CSVs
echo   e rode: .venv\Scripts\python.exe importar_precos.py
goto :FIM_ERRO

:ERRO_PRECOS
echo.
echo   [ERRO] Falha ao importar as tabelas de preco.
goto :FIM_ERRO

:ERRO_CAPTURA
echo.
echo   [ERRO] A captura falhou. Veja as mensagens acima.
echo   Nenhuma analise foi gerada - os dados estariam incompletos.
goto :FIM_ERRO

:ERRO_ANALISE
echo.
echo   [ERRO] Falha ao gerar a analise de custo.
echo   As capturas em out\ estao intactas.
goto :FIM_ERRO


:FIM_OK
pause
exit /b 0

:FIM_ERRO
echo.
pause
exit /b 1
