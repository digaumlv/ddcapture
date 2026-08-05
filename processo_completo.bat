@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ---------------------------------------------------------------------
REM  Processo completo, de ponta a ponta:
REM
REM     1. captura o dashboard, uma vez por emissor
REM     2. carrega as tabelas de preco dos CSV e precifica cada emissor
REM
REM      processo_completo.bat
REM      processo_completo.bat --limpar
REM      processo_completo.bat --from 01/06/2026 --to 30/06/2026
REM      processo_completo.bat --limpar --from 01/06/2026 --to 30/06/2026
REM
REM  --limpar apaga out\ e as planilhas de precificacao antes de comecar.
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

REM A precificacao carrega as tarifas dos CSV. Sem eles nao ha o que
REM carregar - melhor parar agora do que depois da captura.
if not exist "%RAIZ%tabela_precos_sic.csv" goto :SEM_PRECOS
if not exist "%RAIZ%tabela_piso_canais.csv" goto :SEM_PRECOS
if not exist "%RAIZ%tabela_valores_fixos.csv" goto :SEM_PRECOS

if defined LIMPAR (
    echo [0/2] Limpando saidas anteriores...
    if exist "%RAIZ%out" del /q "%RAIZ%out\*" >nul 2>&1
    del /q "%RAIZ%precificacao_*.xlsx" >nul 2>&1
    echo       out\ e precificacao_*.xlsx limpos
    echo.
)

REM --- 1/2  Captura -----------------------------------------------------
echo [1/2] Capturando o dashboard por emissor...
echo       ^(alguns minutos: sao ~145 queries por emissor^)
call "%RAIZ%3_capturar_emissores.bat"!EXTRA!
if errorlevel 1 goto :ERRO_CAPTURA

REM --- 2/2  Precificacao ------------------------------------------------
REM Carrega as tabelas de preco dos CSV e precifica cada emissor. A carga
REM ficou dentro do modulo: separa-la em um passo proprio so criava a
REM chance de precificar com tarifa velha.
echo [2/2] Precificando...
"%PY%" -m precificacao
if errorlevel 1 goto :ERRO_PRECIFICACAO

echo.
echo ============================================================
echo   Processo concluido
echo ============================================================
echo.
echo   Capturas       : out\
echo   Precificacao   : precificacao_^<codigo^>.xlsx
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
echo   [ERRO] Faltam os CSV com as tabelas de preco na raiz do projeto:
echo       tabela_precos_sic.csv
echo       tabela_piso_canais.csv
echo       tabela_valores_fixos.csv
echo.
echo   Sao a fonte das tarifas - nenhum valor fica no codigo.
goto :FIM_ERRO

:ERRO_CAPTURA
echo.
echo   [ERRO] A captura falhou. Veja as mensagens acima.
echo   Nada foi precificado - os dados estariam incompletos.
goto :FIM_ERRO

:ERRO_PRECIFICACAO
echo.
echo   [ERRO] Falha na precificacao.
echo   As capturas em out\ estao intactas.
goto :FIM_ERRO


:FIM_OK
pause
exit /b 0

:FIM_ERRO
echo.
pause
exit /b 1
