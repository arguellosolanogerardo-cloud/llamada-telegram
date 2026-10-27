@echo off
chcp 65001 > nul
title Desinstalador - Tarea Programada (Centinela YouTube)
echo Eliminando tarea programada CentinelaYouTube...
schtasks /delete /tn "CentinelaYouTube" /f
echo Tarea eliminada.
pause
