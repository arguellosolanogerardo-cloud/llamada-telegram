@echo off
chcp 65001 > nul
title Centinela YouTube - Precarga de Audios Limpios
echo ========================================================
echo   CENTINELA YOUTUBE - PRECARGA AUTOMATICA DE AUDIOS
echo ========================================================
echo.
echo Escaneando canales de YouTube y sincronizando con Render...
echo.
python centinela_youtube.py
echo.
echo ========================================================
echo Proceso finalizado. Puedes cerrar esta ventana.
echo ========================================================
pause
