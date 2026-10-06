"""
mejorar_audio.py (v2) — Ecualizador automático de voz para llamada-telegram.

Qué hace
--------
1. ANALIZA cada audio (ruido/estática y cuánta energía hay fuera de la banda de
   la voz) y elige solo un ajuste: AjusteEQ(voz, musica, limpieza) de 0 a 3.
2. PROCESA con FFmpeg: mezcla centrada a mono, filtros, reducción de ruido,
   EQ de voz, compresión y normalización a -16 LUFS.
3. (Opcional) Con Demucs instalado separa voz y música y las vuelve a mezclar
   con la música baja: es la única forma REAL de bajar la música sin dañar la voz.
4. Permite re-procesar con otros niveles (comando /eq) y recortar el audio
   desde un segundo dado para cambiar el stream sin empezar de cero.

Todo es "a prueba de fallos": si algo falla se devuelve el audio original.

Variables de entorno
--------------------
AUDIO_MEJORA_ACTIVA=0   apaga todo el procesado
AUDIO_LUFS=-16          sonoridad objetivo
AUDIO_DEMUCS=1          permite separar voz/música (requiere `pip install demucs`)
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace


# --------------------------------------------------------------------------- #
# Configuración y ajustes
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ConfigAudio:
    lufs_objetivo: float = float(os.environ.get("AUDIO_LUFS", "-16"))
    true_peak_db: float = -1.5
    lra: float = 11.0
    piso_ruido_db: float = -35.0
    corte_graves_hz: int = 90
    sample_rate: int = 48000
    bitrate: str = "192k"
    timeout_s: int = 900
    timeout_demucs_s: int = 2400


@dataclass(frozen=True)
class AjusteEQ:
    """Niveles de 0 a 3. 0 = suave (valor base), 3 = máximo."""
    voz: int = 0        # más presencia y volumen relativo de la voz
    musica: int = 0     # más atenuación de la música de fondo
    limpieza: int = 0   # más reducción de ruido/estática
    separar: bool = False  # separar voz/música con Demucs (si está disponible)

    def con(self, **cambios) -> "AjusteEQ":
        a = replace(self, **cambios)
        return replace(a, voz=max(0, min(3, a.voz)),
                       musica=max(0, min(3, a.musica)),
                       limpieza=max(0, min(3, a.limpieza)))

    def etiqueta(self) -> str:
        return f"v{self.voz}m{self.musica}l{self.limpieza}{'s' if self.separar else ''}"


def describir_ajuste(a: AjusteEQ) -> str:
    sep = " · ✂️ Separación voz/música: ON" if a.separar else ""
    return (f"🎙️ Voz {a.voz}/3 · 🎵 Atenuar música {a.musica}/3 · "
            f"🔇 Limpieza {a.limpieza}/3{sep}")


class ErrorProcesamientoAudio(RuntimeError):
    """Error interno controlado del procesado de audio."""


def _log(msg: str) -> None:
    try:
        print(f"[mejorar_audio] {msg}", flush=True)
    except UnicodeEncodeError:
        safe = msg.encode("ascii", "replace").decode("ascii")
        print(f"[mejorar_audio] {safe}", flush=True)


def demucs_disponible() -> bool:
    return (os.environ.get("AUDIO_DEMUCS", "0") == "1"
            and importlib.util.find_spec("demucs") is not None)


# --------------------------------------------------------------------------- #
# FFmpeg
# --------------------------------------------------------------------------- #
def _bin(nombre: str) -> str:
    ruta = shutil.which(nombre)
    if not ruta:
        raise ErrorProcesamientoAudio(f"No se encontró '{nombre}' en el PATH")
    return ruta


def _ejecutar(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, errors="replace")
    except subprocess.TimeoutExpired as e:
        raise ErrorProcesamientoAudio(f"Excedió {timeout}s: {cmd[0]}") from e
    except OSError as e:
        raise ErrorProcesamientoAudio(f"No se pudo ejecutar {cmd[0]}: {e}") from e


def _duracion(ruta: str) -> float:
    res = _ejecutar([_bin("ffprobe"), "-v", "error", "-show_entries",
                     "format=duration", "-of", "default=nw=1:nk=1", ruta], 60)
    try:
        return float(res.stdout.strip())
    except ValueError as e:
        raise ErrorProcesamientoAudio(f"Audio ilegible o corrupto: {ruta}") from e


# --------------------------------------------------------------------------- #
# Análisis automático
# --------------------------------------------------------------------------- #
def _astats(ruta: str, ss: float, t: float, filtro: str = "") -> dict:
    pre = f"{filtro}," if filtro else ""
    cmd = [_bin("ffmpeg"), "-hide_banner", "-nostdin", "-ss", str(ss), "-t", str(t),
           "-i", ruta, "-af",
           pre + "astats=measure_perchannel=none:measure_overall=RMS_level+Noise_floor",
           "-f", "null", "-"]
    res = _ejecutar(cmd, 120)

    def num(clave: str) -> float:
        m = re.findall(clave + r":\s*(-?inf|-?[\d.]+)", res.stderr)
        if not m or "inf" in m[-1]:
            return -90.0
        return float(m[-1])

    return {"rms": num("RMS level dB"), "ruido": num("Noise floor dB")}


def analizar_audio(ruta: str) -> AjusteEQ:
    """Elige niveles según el ruido y la energía fuera de la banda de la voz."""
    try:
        dur = _duracion(ruta)
        t = min(90.0, dur)
        ss = max(0.0, dur / 2 - t / 2)  # muestra del centro del audio
        total = _astats(ruta, ss, t)
        banda = _astats(ruta, ss, t, "highpass=f=300,lowpass=f=3400")
        fuera = banda["rms"] - total["rms"]   # cercano a 0 => casi todo es voz
        ruido = total["ruido"]

        limpieza = 3 if ruido > -38 else 2 if ruido > -45 else 1 if ruido > -55 else 0
        musica = 3 if fuera < -9 else 2 if fuera < -6 else 1 if fuera < -3.5 else 0
        voz = 0 if musica == 0 else 1 if musica < 3 else 2
        aj = AjusteEQ(voz=voz, musica=musica, limpieza=limpieza,
                      separar=demucs_disponible() and musica >= 2)
        _log(f"Análisis: ruido={ruido:.1f} dB, energía fuera de voz={fuera:.1f} dB "
             f"-> {describir_ajuste(aj)}")
        return aj
    except ErrorProcesamientoAudio as e:
        _log(f"Análisis falló ({e}); se usan niveles base.")
        return AjusteEQ()


# --------------------------------------------------------------------------- #
# Separación voz/música (opcional)
# --------------------------------------------------------------------------- #
def _mezcla_separada(ruta: str, aj: AjusteEQ, cfg: ConfigAudio) -> str | None:
    """Demucs -> voz + (música * peso). Devuelve un wav temporal o None."""
    if not demucs_disponible():
        return None
    base = os.path.splitext(os.path.basename(ruta))[0]
    raiz = os.path.join(os.path.dirname(os.path.abspath(ruta)), "demucs_cache")
    carpeta = os.path.join(raiz, "htdemucs", base)
    voz = os.path.join(carpeta, "vocals.wav")
    resto = os.path.join(carpeta, "no_vocals.wav")
    if not (os.path.exists(voz) and os.path.exists(resto)
            and os.path.getmtime(voz) >= os.path.getmtime(ruta)):
        _log("Separando voz y música con Demucs (puede tardar varios minutos)...")
        res = _ejecutar([sys.executable, "-m", "demucs.separate", "--two-stems=vocals",
                         "-n", "htdemucs", "-o", raiz, ruta], cfg.timeout_demucs_s)
        if res.returncode != 0 or not os.path.exists(voz):
            raise ErrorProcesamientoAudio(f"Demucs falló: {res.stderr[-300:]}")
    peso = (0.5, 0.3, 0.18, 0.1)[aj.musica]
    salida = os.path.join(carpeta, f"mezcla_{aj.musica}.wav")
    res = _ejecutar([_bin("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-i", voz,
                     "-i", resto, "-filter_complex",
                     f"[1:a]volume={peso}[m];[0:a][m]amix=inputs=2:normalize=0:duration=longest",
                     salida], cfg.timeout_s)
    if res.returncode != 0:
        raise ErrorProcesamientoAudio(f"Mezcla voz/música falló: {res.stderr[-300:]}")
    return salida


# --------------------------------------------------------------------------- #
# Procesado
# --------------------------------------------------------------------------- #
def _cadena(aj: AjusteEQ, separado: bool) -> str:
    graves = 14000
    lp_ruido = (14000, 12000, 10000, 8500)[aj.limpieza]
    lp_musica = graves if separado else (14000, 12000, 10000, 8500)[aj.musica]
    hp = ConfigAudio.corte_graves_hz + (0 if separado else 30 * aj.musica)
    dip = -2 - (0 if separado else aj.musica)
    f = [
        "aformat=channel_layouts=stereo", "pan=mono|c0=0.5*c0+0.5*c1",
        f"highpass=f={hp}:poles=2",
        f"afftdn=nr={8 + 4 * aj.limpieza}:nf={ConfigAudio.piso_ruido_db}:tn=1",
        f"lowpass=f={min(lp_ruido, lp_musica)}",
        f"equalizer=f=250:t=q:w=1.0:g={dip}",
        f"equalizer=f=3000:t=q:w=0.9:g={3 + 1.5 * aj.voz}",
    ]
    if aj.voz >= 1:
        f.append(f"speechnorm=e={3 + aj.voz}:r=0.0001:l=1")
    f.append("acompressor=threshold=-20dB:ratio=3:attack=10:release=120:makeup=2")
    return ",".join(f)


def _medir(fuente: str, cadena: str, cfg: ConfigAudio) -> dict:
    filtro = (f"{cadena},loudnorm=I={cfg.lufs_objetivo}:TP={cfg.true_peak_db}"
              f":LRA={cfg.lra}:print_format=json")
    res = _ejecutar([_bin("ffmpeg"), "-hide_banner", "-nostdin", "-i", fuente,
                     "-af", filtro, "-f", "null", "-"], cfg.timeout_s)
    if res.returncode != 0:
        raise ErrorProcesamientoAudio(f"Medición falló: {res.stderr[-300:]}")
    bloques = re.findall(r"\{[^{}]*\}", res.stderr, re.DOTALL)
    try:
        datos = json.loads(bloques[-1])
        for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
            float(datos[k])
        return datos
    except (IndexError, ValueError, KeyError) as e:
        raise ErrorProcesamientoAudio("Medición inválida (¿audio en silencio?)") from e


def _procesar(entrada: str, salida: str, aj: AjusteEQ, cfg: ConfigAudio,
              dos_pasadas: bool) -> None:
    dur_in = _duracion(entrada)
    if dur_in < 1:
        raise ErrorProcesamientoAudio("Audio demasiado corto")

    fuente = entrada
    separado = False
    if aj.separar:
        try:
            m = _mezcla_separada(entrada, aj, cfg)
            if m:
                fuente, separado = m, True
        except ErrorProcesamientoAudio as e:
            _log(f"Sin separación voz/música ({e}); se usa solo EQ.")

    cadena = _cadena(aj, separado)
    ln = f"loudnorm=I={cfg.lufs_objetivo}:TP={cfg.true_peak_db}:LRA={cfg.lra}"
    if dos_pasadas:
        m = _medir(fuente, cadena, cfg)
        ln += (f":measured_I={m['input_i']}:measured_TP={m['input_tp']}"
               f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
               f":offset={m['target_offset']}:linear=true")
    filtro = f"{cadena},{ln},aresample={cfg.sample_rate}"

    tmp = salida + ".tmp.mp3"
    try:
        res = _ejecutar([_bin("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-i", fuente,
                         "-vn", "-map_metadata", "-1", "-af", filtro,
                         "-ar", str(cfg.sample_rate), "-ac", "1",
                         "-c:a", "libmp3lame", "-b:a", cfg.bitrate, tmp], cfg.timeout_s)
        if res.returncode != 0 or not os.path.exists(tmp):
            raise ErrorProcesamientoAudio(f"Render falló: {res.stderr[-300:]}")
        if os.path.getsize(tmp) < 5000:
            raise ErrorProcesamientoAudio("Salida sospechosamente pequeña")
        dur_out = _duracion(tmp)
        if abs(dur_out - dur_in) > max(2.0, dur_in * 0.01):
            raise ErrorProcesamientoAudio(f"Duración alterada ({dur_in:.1f}s -> {dur_out:.1f}s)")
        os.replace(tmp, salida)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


# --------------------------------------------------------------------------- #
# API pública
# --------------------------------------------------------------------------- #
def mejorar_audio(ruta_entrada: str, ruta_salida: str | None = None,
                  ajuste: AjusteEQ | None = None, forzar: bool = False,
                  dos_pasadas: bool = True, cfg: ConfigAudio | None = None) -> str:
    """
    Devuelve la ruta del audio mejorado, o `ruta_entrada` si algo falla.
    `ajuste=None` => análisis automático. El resultado se cachea por ajuste.
    """
    if os.environ.get("AUDIO_MEJORA_ACTIVA", "1") == "0":
        return ruta_entrada
    if not ruta_entrada or not os.path.exists(ruta_entrada) \
            or os.path.getsize(ruta_entrada) < 5000:
        _log(f"Entrada inexistente o muy pequeña, se omite: {ruta_entrada}")
        return ruta_entrada
    cfg = cfg or ConfigAudio()
    try:
        aj = ajuste if ajuste is not None else analizar_audio(ruta_entrada)
        if ruta_salida is None:
            base, _ = os.path.splitext(ruta_entrada)
            ruta_salida = f"{base}_mejorado_{aj.etiqueta()}.mp3"
        if (not forzar and os.path.exists(ruta_salida)
                and os.path.getsize(ruta_salida) > 5000
                and os.path.getmtime(ruta_salida) >= os.path.getmtime(ruta_entrada)):
            _log(f"Usando versión ya procesada: {ruta_salida}")
            return ruta_salida
        _log(f"Procesando {os.path.basename(ruta_entrada)} [{aj.etiqueta()}] ...")
        _procesar(ruta_entrada, ruta_salida, aj, cfg, dos_pasadas)
        _log(f"Listo -> {ruta_salida}")
        return ruta_salida
    except ErrorProcesamientoAudio as e:
        _log(f"No se pudo mejorar el audio, se usa el original. Motivo: {e}")
    except Exception as e:  # red de seguridad: nunca romper la llamada
        _log(f"Error inesperado, se usa el original: {type(e).__name__}: {e}")
    return ruta_entrada


def recortar_desde(ruta: str, segundos: float, salida: str) -> str:
    """Copia `ruta` desde `segundos` (sin re-codificar). Devuelve `ruta` si falla."""
    try:
        if segundos <= 1:
            return ruta
        res = _ejecutar([_bin("ffmpeg"), "-hide_banner", "-nostdin", "-y",
                         "-ss", f"{segundos:.2f}", "-i", ruta, "-c", "copy", salida], 120)
        if res.returncode == 0 and os.path.exists(salida) and os.path.getsize(salida) > 5000:
            return salida
        _log(f"Recorte falló: {res.stderr[-200:]}")
    except ErrorProcesamientoAudio as e:
        _log(f"Recorte falló: {e}")
    return ruta


async def mejorar_audio_async(ruta: str, ajuste: AjusteEQ | None = None,
                              forzar: bool = False, dos_pasadas: bool = True) -> str:
    """Igual que mejorar_audio pero SIN bloquear el bucle de asyncio del bot."""
    return await asyncio.to_thread(mejorar_audio, ruta, None, ajuste, forzar, dos_pasadas)


async def analizar_audio_async(ruta: str) -> AjusteEQ:
    return await asyncio.to_thread(analizar_audio, ruta)


async def recortar_desde_async(ruta: str, segundos: float, salida: str) -> str:
    return await asyncio.to_thread(recortar_desde, ruta, segundos, salida)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Mejora un audio de voz.")
    p.add_argument("entrada")
    p.add_argument("salida", nargs="?")
    p.add_argument("--analizar", action="store_true", help="solo mostrar el ajuste automático")
    for n in ("voz", "musica", "limpieza"):
        p.add_argument(f"--{n}", type=int, default=None)
    p.add_argument("--separar", action="store_true")
    a = p.parse_args()
    if a.analizar:
        print(describir_ajuste(analizar_audio(a.entrada)))
        sys.exit(0)
    aj = None
    if any(v is not None for v in (a.voz, a.musica, a.limpieza)) or a.separar:
        aj = AjusteEQ(a.voz or 0, a.musica or 0, a.limpieza or 0, a.separar)
    print(mejorar_audio(a.entrada, a.salida, aj, forzar=True))
