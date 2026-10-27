@echo off
chcp 65001 > nul
title Instalador - Tarea Programada de Windows (Centinela YouTube)
echo ================================================================
echo   INSTALANDO TAREA PROGRAMADA DE WINDOWS: CentinelaYouTube
echo ================================================================
echo.
echo Se configurara la ejecucion automatica cada 15 minutos en segundo
echo plano para precargar los audios apenas salgan en YouTube.
echo.

schtasks /create /tn "CentinelaYouTube" /tr "\"C:\Users\INGENIERO\AppData\Local\Programs\Python\Python313\python.exe\" \"E:\DEVELOPER\AI\FACTORY SOFTWARE\TESTING\bot_llamadas_telegram\centinela_youtube.py\"" /sc minute /mo 15 /f

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ================================================================
    echo   [OK] Tarea programada instalada exitosamente en Windows.
    echo   Tu PC revisara cada 15 minutos de forma silenciosa.
    echo ================================================================
) else (
    echo.
    echo ================================================================
    echo   [ERROR] No se pudo crear la tarea. Si pide permisos, ejecuta
    echo   este archivo haciendo clic derecho -> "Ejecutar como administrador".
    echo ================================================================
)
echo.
pause
