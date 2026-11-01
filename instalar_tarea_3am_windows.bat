@echo off
chcp 65001 > nul
title Instalador - Tarea Programada 3 AM (Publicar Tarea Diaria)
echo ================================================================
echo   INSTALANDO TAREA PROGRAMADA DE WINDOWS: PublicarTarea3AM
echo ================================================================
echo.
echo Se configurara la ejecucion automatica diaria a las 03:00 AM
echo (con control estricto de maximo 2 publicaciones por dia).
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "$action = New-ScheduledTaskAction -Execute 'C:\Users\INGENIERO\AppData\Local\Programs\Python\Python313\python.exe' -Argument 'schedule_meditaciones.py' -WorkingDirectory '%~dp0'; $trigger = New-ScheduledTaskTrigger -Daily -At 03:00; Register-ScheduledTask -TaskName 'PublicarTarea3AM' -Action $action -Trigger $trigger -Force"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ================================================================
    echo   [OK] Tarea programada 3 AM instalada exitosamente en Windows.
    echo ================================================================
) else (
    echo.
    echo ================================================================
    echo   [ERROR] No se pudo crear la tarea. Ejecuta este .bat como
    echo   Administrador (clic derecho -> Ejecutar como administrador).
    echo ================================================================
)
echo.
pause
