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

powershell -NoProfile -ExecutionPolicy Bypass -Command "$cands = @(\"$env:LOCALAPPDATA\Programs\Python\Python314\python.exe\", (Get-Command python.exe -ErrorAction SilentlyContinue).Source, \"$env:LOCALAPPDATA\Programs\Python\Python313\python.exe\", \"$env:LOCALAPPDATA\Programs\Python\Python312\python.exe\", 'C:\Program Files\Python314\python.exe', 'C:\Program Files\Python313\python.exe', 'C:\Program Files\Python312\python.exe'); $py = $null; foreach ($c in $cands) { if ($c -and (Test-Path $c)) { $py = $c; break } }; if (-not $py) { Write-Host '[ERROR] No se detecto python.exe en el sistema' -ForegroundColor Red; exit 1 }; Write-Host \"Detectado Python en: $py\"; $action = New-ScheduledTaskAction -Execute $py -Argument 'centinela_youtube.py' -WorkingDirectory '%~dp0'; $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 15); Register-ScheduledTask -TaskName 'CentinelaYouTube' -Action $action -Trigger $trigger -Force"

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
