"""Formateo de transcripciones a texto con marcas de tiempo y a SRT.

Modulo puro y sin dependencias: no importa Qt, faster-whisper ni nada pesado. Eso
permite probarlo sin instalar el stack completo, y evita que estos formatos se
dupliquen entre el progreso parcial y el resultado final.

Un "segmento" es un dict {start: float, end: float, text: str}.
"""

SECONDS_PER_HOUR = 3600


def format_srt_timestamp(seconds):
    """Segundos -> '00:00:00,000' (formato SRT)."""
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms >= 1000:
        # El redondeo puede llegar a 1000; SRT solo admite 3 digitos.
        ms = 999
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(segments):
    """Construye un archivo SRT completo a partir de los segmentos."""
    lines = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(
            f"{format_srt_timestamp(seg['start'])} --> {format_srt_timestamp(seg['end'])}"
        )
        lines.append(seg["text"].strip())
        lines.append("")
    return "\n".join(lines)


def format_segments_with_timestamps(segments):
    """Devuelve '[MM:SS] texto' por linea.

    Pasa a '[HH:MM:SS]' si el audio supera la hora, para que las marcas no queden
    ambiguas en grabaciones largas.
    """
    if not segments:
        return ""
    use_hours = max((s["end"] for s in segments), default=0) >= SECONDS_PER_HOUR
    lines = []
    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue
        total = max(0, int(seg["start"]))
        m, s = divmod(total, 60)
        h, m = divmod(m, 60)
        stamp = f"{h:02d}:{m:02d}:{s:02d}" if use_hours else f"{m:02d}:{s:02d}"
        lines.append(f"[{stamp}] {text}")
    return "\n".join(lines)
