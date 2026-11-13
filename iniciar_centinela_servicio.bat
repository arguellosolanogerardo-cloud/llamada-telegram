@echo off
chcp 65001 > nul
title Centinela YouTube - Servicio Continuo
echo ================================================================
echo   CENTINELA YOUTUBE - MODO SERVICIO EN SEGUNDO PLANO
echo ================================================================
echo.
echo Monitoreando canales oficiales de YouTube cada 15 minutos...
echo Cuando ALANISO o Mario Carrillo suban video, se descargara y
echo sincronizara con Render automaticamente.
echo.
echo Para detener el servicio, presiona Ctrl + C o cierra esta ventana.
echo.
if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" centinela_youtube.py --daemon --intervalo 15
) else if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" centinela_youtube.py --daemon --intervalo 15
) else (
    python centinela_youtube.py --daemon --intervalo 15
)
pause
