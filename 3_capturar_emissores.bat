@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ---------------------------------------------------------------------
REM  Captura o dashboard uma vez POR EMISSOR, gerando uma planilha para
REM  cada um em vez de tudo misturado.
REM
REM      3_capturar_emissores.bat                      usa a lista abaixo
REM      3_capturar_emissores.bat 1234 5678            usa os codigos passados
REM      3_capturar_emissores.bat 1234 --from 01/06     (a partir do 2o arg,
REM                                                    tudo vai para o coletor)
REM
REM  Cada execucao filtra por @org via a template variable codigoEmissor,
REM  e o codigo entra no nome do arquivo.
REM ---------------------------------------------------------------------

chcp 65001 >nul 2>&1
set "PYTHONIOENCODING=utf-8"

REM A raiz precisa ser guardada ANTES do shift do parsing: o shift desloca
REM tambem o %0, e a partir dai %~dp0 nao aponta mais para este script.
set "RAIZ=%~dp0"
cd /d "%RAIZ%"

REM Emissores vem de config\emissores.txt (ignorado pelo git). Copie o
REM .example e ajuste conforme a sua carteira.
REM
REM ATENCAO ao formato do codigo: a origem pode gravar @org de duas formas -
REM com zero a esquerda ('1234') e sem ('234') - em etapas diferentes do
REM funil. Filtrar so por uma delas pega parte dos eventos e perde o resto,
REM sem nenhum erro aparecer. Por isso cada emissor e consultado como
REM '(1234 OR 234)'.
set "ARQUIVO=%RAIZ%config\emissores.txt"
set "PADRAO="
if exist "%ARQUIVO%" (
    for /f "usebackq eol=# tokens=1 delims==" %%L in ("%ARQUIVO%") do (
        if not "%%L"=="" set "PADRAO=!PADRAO! %%L"
    )
)

REM Separa os argumentos: so-digitos viram emissores, o resto e repassado ao
REM coletor. O label precisa ficar FORA de qualquer bloco entre parenteses -
REM dentro de um `if (...)` o batch nao o enxerga.
set "EMISSORES="
set "EXTRA="

:PARSE
if "%~1"=="" goto :PARSE_FIM
echo(%~1|findstr /r "^[0-9][0-9]*$" >nul
if errorlevel 1 (
    set "EXTRA=!EXTRA! %1"
) else (
    set "EMISSORES=!EMISSORES! %~1"
)
shift
goto :PARSE

:PARSE_FIM
if not defined EMISSORES set "EMISSORES=%PADRAO%"
if not defined EMISSORES goto :SEM_LISTA

echo.
echo ============================================================
echo   Captura por emissor
echo ============================================================
echo   Emissores:%EMISSORES%
if defined EXTRA echo   Repassado:%EXTRA%
echo.

set "FALHAS=0"
for %%E in (%EMISSORES%) do (
    REM Tira o zero a esquerda para montar a alternativa: 1234 -> 234.
    set "CURTO=%%E"
    if "!CURTO:~0,1!"=="0" set "CURTO=!CURTO:~1!"

    if "!CURTO!"=="%%E" (
        set "ALVO=%%E"
    ) else (
        set "ALVO=(%%E OR !CURTO!)"
    )

    echo ------------------------------------------------------------
    echo   Emissor %%E   filtro @org:!ALVO!
    echo ------------------------------------------------------------
    call "%RAIZ%ddcapture.bat" --var "codigoEmissor=!ALVO!" --rotulo %%E!EXTRA!
    if errorlevel 1 (
        echo   [FALHOU] emissor %%E
        set /a FALHAS+=1
    )
    echo.
)

if %FALHAS% GTR 0 (
    echo %FALHAS% emissor^(es^) com falha. Veja as mensagens acima.
    exit /b 1
)

echo ============================================================
echo   Concluido. Uma planilha por emissor em out\
echo ============================================================
exit /b 0


:SEM_LISTA
echo.
echo   [ERRO] Nenhum emissor definido.
echo.
echo   Crie a lista uma vez:
echo       copy config\emissores.txt.example config\emissores.txt
echo.
echo   e preencha com os codigos da sua carteira. Ou passe direto:
echo       3_capturar_emissores.bat 1234 5678
echo.
exit /b 2
