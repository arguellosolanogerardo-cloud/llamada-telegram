@echo off
chcp 65001 > nul
title Instalador - Tarea Programada de Windows (Centinela YouTube)
echo ================================================================
echo   INSTALANDO TAREA PROGRAMADA DE WINDOWS: CentinelaYouTube
echo ================================================================
echo.
echo Se configurara la ejecucion automatica cada 15 minutos en segundo
echo plano con el directorio de trabajo correcto.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "$action = New-ScheduledTaskAction -Execute 'C:\Users\INGENIERO\AppData\Local\Programs\Python\Python313\python.exe' -Argument 'centinela_youtube.py' -WorkingDirectory '%~dp0'; $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 15); Register-ScheduledTask -TaskName 'CentinelaYouTube' -Action $action -Trigger $trigger -Force"

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
