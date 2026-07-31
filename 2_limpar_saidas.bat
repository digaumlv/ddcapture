@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ---------------------------------------------------------------------
REM  Apaga o que o processo gera, preservando o que e fonte.
REM
REM      2_limpar_saidas.bat            mostra o que sera apagado e confirma
REM      2_limpar_saidas.bat --sim      apaga sem perguntar (para scripts)
REM      2_limpar_saidas.bat --tudo     inclui o precos.sqlite
REM
REM  APAGA:
REM      out\*                     capturas (JSON, XLSX, CSV, SQLite)
REM      analise_custos_*.xlsx     planilhas de analise
REM      precos.sqlite             somente com --tudo
REM
REM  NUNCA TOCA:
REM      .env, config\*            credenciais e configuracao
REM      *.csv na raiz             tabelas de preco transcritas a mao
REM      *.jpeg, *.png             imagens de origem
REM      qualquer arquivo do codigo
REM ---------------------------------------------------------------------

chcp 65001 >nul 2>&1

REM Guardada antes de qualquer shift: o shift desloca tambem o %0.
set "RAIZ=%~dp0"
cd /d "%RAIZ%"

set "SEM_PERGUNTAR="
set "INCLUIR_BANCO="
:PARSE
if "%~1"=="" goto :PARSE_FIM
if /i "%~1"=="--sim" set "SEM_PERGUNTAR=1"
if /i "%~1"=="-y" set "SEM_PERGUNTAR=1"
if /i "%~1"=="--tudo" set "INCLUIR_BANCO=1"
shift
goto :PARSE
:PARSE_FIM

REM --- Inventario do que sera apagado ----------------------------------
set /a N_OUT=0
if exist "%RAIZ%out" (
    for %%F in ("%RAIZ%out\*") do set /a N_OUT+=1
)
set /a N_ANALISE=0
for %%F in ("%RAIZ%analise_custos_*.xlsx") do set /a N_ANALISE+=1

set /a N_BANCO=0
if defined INCLUIR_BANCO if exist "%RAIZ%precos.sqlite" set /a N_BANCO=1

set /a TOTAL=N_OUT+N_ANALISE+N_BANCO

echo.
echo ============================================================
echo   Limpar saidas
echo ============================================================
echo.
echo   out\                    !N_OUT! arquivo^(s^)
echo   analise_custos_*.xlsx   !N_ANALISE! arquivo^(s^)
if defined INCLUIR_BANCO echo   precos.sqlite           !N_BANCO! arquivo^(s^)
echo.

if %TOTAL%==0 (
    echo   Nada a apagar - ja esta limpo.
    echo.
    goto :FIM_OK
)

echo   Preservados: .env, config\, *.csv, *.jpeg e o codigo.
echo.

if defined SEM_PERGUNTAR goto :APAGAR

REM Sem stdin (duplo clique com redirecionamento) o choice falha; nesse
REM caso o padrao e NAO apagar - o silencio nao deve destruir arquivo.
choice /c SN /n /m "   Apagar %TOTAL% arquivo(s)? (S/N): "
if errorlevel 2 goto :CANCELADO
if errorlevel 1 goto :APAGAR
goto :CANCELADO


:APAGAR
echo.
if exist "%RAIZ%out" del /q "%RAIZ%out\*" >nul 2>&1
del /q "%RAIZ%analise_custos_*.xlsx" >nul 2>&1
if defined INCLUIR_BANCO del /q "%RAIZ%precos.sqlite" >nul 2>&1

REM Confere o resultado em vez de confiar no del.
set /a RESTOU=0
if exist "%RAIZ%out" (
    for %%F in ("%RAIZ%out\*") do set /a RESTOU+=1
)
for %%F in ("%RAIZ%analise_custos_*.xlsx") do set /a RESTOU+=1

if !RESTOU! GTR 0 (
    echo   [ATENCAO] !RESTOU! arquivo^(s^) nao foram apagados.
    echo   Verifique se estao abertos no Excel e tente de novo.
    goto :FIM_ERRO
)

echo   %TOTAL% arquivo^(s^) apagado^(s^).
echo.
echo   Para gerar de novo: processo_completo.bat
echo.
goto :FIM_OK


:CANCELADO
echo.
echo   Cancelado - nada foi apagado.
echo.
goto :FIM_OK


:FIM_OK
if not defined SEM_PERGUNTAR pause
exit /b 0

:FIM_ERRO
if not defined SEM_PERGUNTAR pause
exit /b 1
