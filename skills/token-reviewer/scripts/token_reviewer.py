#!/usr/bin/env python3
"""
Token Reviewer: tokens y coste estimado (USD) de las sesiones de Claude Code.
Token Reviewer: token usage and estimated cost (USD) of Claude Code sessions.

Lee los transcripts .jsonl que Claude Code guarda en ~/.claude/projects
(o en $CLAUDE_CONFIG_DIR/projects). Solo usa la librería estándar; Python 3.8+.

  token_reviewer.py                   interactivo: elige una sesión reciente
  token_reviewer.py --here            sesión más reciente del directorio actual
  token_reviewer.py --session ID      una sesión concreta (id completo o prefijo)
  token_reviewer.py MatchBar          sesión más reciente del proyecto que coincida
  token_reviewer.py --all MatchBar    todas las sesiones del proyecto, sumadas
  token_reviewer.py --all --days 7    todo lo gastado en los últimos 7 días
  token_reviewer.py --list            lista las sesiones recientes

Ejecuta con --help para ver todas las opciones.
"""

from __future__ import annotations

import argparse
import json
import locale
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

__version__ = "2.1.0"

# ── precios ───────────────────────────────────────────────────────────────────
# USD por millón de tokens: (entrada, salida, lectura de caché), precios de lista
# de la API de Anthropic. Las claves son ids sin fecha: "claude-opus-4-5-20251101",
# "anthropic.claude-opus-4-5-20251101-v1:0" o "claude-opus-4-5@20251101" usan
# "claude-opus-4-5".
#
# Esta tabla es la base sin conexión. Cuando aparece un modelo que no está aquí, el
# script descarga la tabla oficial (PRICES_URL, como mucho una vez al día) y la guarda
# en ~/.claude/token-reviewer/prices.json, que también admite modelos añadidos a mano.
# Si aun así no hay precio, se usa el coste que registró Claude Code o se avisa.
PRICES_DATE = "2026-09-28"   # cuándo se revisó esta tabla por última vez
MODEL_PRICES = {
    "claude-fable-5-1":  (10.00, 50.00, 0.25),
    "claude-mythos-5-1": (10.00, 50.00, 0.25),
    "claude-fable-5":    (10.00, 50.00, 1.00),
    "claude-mythos-5":   (10.00, 50.00, 1.00),
    "claude-opus-5-5":   (4.00, 20.00, 0.20),
    "claude-opus-5":     (5.00, 25.00, 0.50),
    "claude-opus-4-8":   (5.00, 25.00, 0.50),
    "claude-opus-4-7":   (5.00, 25.00, 0.50),
    "claude-opus-4-6":   (5.00, 25.00, 0.50),
    "claude-opus-4-5":   (5.00, 25.00, 0.50),
    "claude-opus-4-1":   (15.00, 75.00, 1.50),
    "claude-opus-4":     (15.00, 75.00, 1.50),
    "claude-sonnet-5":   (2.00, 10.00, 0.20),
    "claude-sonnet-4-6": (3.00, 15.00, 0.30),
    "claude-sonnet-4-5": (3.00, 15.00, 0.30),
    "claude-sonnet-4":   (3.00, 15.00, 0.30),
    "claude-haiku-4-5":  (1.00, 5.00, 0.10),
    "claude-3-7-sonnet": (3.00, 15.00, 0.30),
    "claude-3-5-sonnet": (3.00, 15.00, 0.30),
    "claude-3-5-haiku":  (0.80, 4.00, 0.08),
    "claude-3-opus":     (15.00, 75.00, 1.50),
    "claude-3-sonnet":   (3.00, 15.00, 0.30),
    "claude-3-haiku":    (0.25, 1.25, 0.03),
}
CACHE_WRITE_5M = 1.25   # escritura en caché con TTL de 5 min, sobre el precio de entrada
CACHE_WRITE_1H = 2.0    # escritura en caché con TTL de 1 h
# Modo rápido (usage.speed == "fast"): multiplica todas las tarifas del modelo, caché
# incluida. En Opus 4.6 la petición va a velocidad normal y se cobra a tarifa normal.
FAST_MULTIPLIER = {"claude-opus-5-5": 2.0, "claude-opus-5": 2.0, "claude-opus-4-8": 2.0,
                   "claude-opus-4-6": 1.0}
# Inferencia solo en EE. UU. (usage.inference_geo == "us"): 1,1x en modelos 4.6 y posteriores.
GEO_US_MULTIPLIER = 1.1
GEO_EXEMPT = {"claude-opus-4-5", "claude-opus-4-1", "claude-opus-4", "claude-sonnet-4-5",
              "claude-sonnet-4", "claude-haiku-4-5"}
WEB_SEARCH_USD = 0.01   # por búsqueda web (10 USD cada 1.000)

PRICES_URL = os.environ.get("TOKEN_REVIEWER_PRICES_URL",
                            "https://platform.claude.com/docs/en/about-claude/pricing.md")
PRICE_CHECK_INTERVAL = 24 * 3600   # segundos entre descargas automáticas

# ── textos ────────────────────────────────────────────────────────────────────

TEXTS = {
    "es": {
        "title_session": "TOKEN REVIEWER · Análisis de sesión",
        "title_summary": "TOKEN REVIEWER · Resumen de {n} sesiones",
        "lbl_title": "Título",
        "lbl_session": "Sesión",
        "lbl_project": "Proyecto",
        "lbl_start": "Inicio",
        "lbl_duration": "Duración",
        "lbl_turns": "Turnos",
        "lbl_filter": "Filtro",
        "lbl_period": "Desde",
        "lbl_sessions": "Sesiones",
        "api_calls": ("{n} llamada a la API", "{n} llamadas a la API"),
        "col_prompt": "Prompt",
        "col_calls": "Llam.",
        "col_in": "Entr.",
        "col_out": "Sal.",
        "col_cr": "Caché L",
        "col_cw": "Caché E",
        "col_cost": "Coste",
        "col_date": "Fecha",
        "col_id": "ID",
        "col_project": "Proyecto",
        "col_title": "Título",
        "total": "TOTAL",
        "no_prompt": "[sin prompt]",
        "image": "[imagen]",
        "showing_top": "Mostrando los {n} más caros de {total}.",
        "summary": "RESUMEN",
        "by_model": "Por modelo",
        "calls_word": ("llamada", "llamadas"),
        "s_input": "Entrada sin caché",
        "s_output": "Salida",
        "s_thinking": "de ellos {n} de razonamiento",
        "s_cache_read": "Caché leída",
        "s_cache_write": "Caché escrita",
        "s_processed": "Tokens procesados",
        "s_hit": "Acierto de caché",
        "s_web": "Búsquedas web",
        "s_cost": "Coste estimado",
        "s_cc_cost": "Según Claude Code",
        "cc_note": "incluye llamadas internas que no quedan en el transcript, como títulos o compactación",
        "price_note": "Estimación con precios de lista de la API de Anthropic (USD). Con suscripción "
                      "Pro/Max no pagas por token; en Bedrock o Vertex las tarifas cambian.",
        "warn_unpriced": ("Modelo sin precio conocido, excluido del coste: {model} ({n} llamada). "
                          "Prueba --update-prices o añade su precio en {path}.",
                          "Modelo sin precio conocido, excluido del coste: {model} ({n} llamadas). "
                          "Prueba --update-prices o añade su precio en {path}."),
        "warn_fast": "Modo rápido sin tarifa conocida para {model}: se usó la tarifa estándar.",
        "warn_cc_price": "Coste de {model} tomado del registro de Claude Code (el reparto por turnos "
                         "es aproximado).",
        "fetching_prices": "Modelo sin precio en la tabla ({models}): consultando {url}",
        "prices_updated": "Precios actualizados: {n} modelos. Guardados en {path}",
        "prices_new": "Modelos nuevos respecto a la tabla integrada: {models}",
        "prices_failed": "No se pudieron actualizar los precios ({error}).",
        "list_title": "Sesiones de Claude Code",
        "choose": "Elige un número (Enter para cancelar): ",
        "save_q": "¿Guardar reporte JSON? [s/N]: ",
        "saved": "Reporte guardado en: {path}",
        "not_saved": "No guardado.",
        "cancelled": "Cancelado.",
        "invalid_choice": "Opción no válida.",
        "no_projects": "No existe la carpeta de sesiones de Claude Code: {path}",
        "no_sessions": "No se encontraron sesiones.",
        "no_match": "Ninguna sesión coincide con '{q}'.",
        "no_here": "No hay sesiones de Claude Code para {path} ni sus carpetas superiores.",
        "no_file": "No existe: {path}",
        "no_calls": "La sesión no tiene llamadas a la API con datos de uso.",
        "hint_list": "Usa --list para ver las sesiones disponibles.",
        "hint_noninteractive": "Sin terminal interactiva: indica qué analizar (--here, --last, "
                               "--session ID, --all o un nombre de proyecto).",
        "bad_session_id": "Id de sesión no válido ('{sid}'): se usa la sesión más reciente del "
                          "directorio actual.",
        "ambiguous_id": "Varias sesiones empiezan por '{sid}'; se usa la más reciente.",
        "bad_date": "Fecha no válida '{value}': usa el formato AAAA-MM-DD.",
        "yes": ("s", "si", "sí", "y", "yes"),
        "h_desc": "Tokens y coste estimado (USD) de las sesiones de Claude Code.",
        "h_target": "archivo .jsonl, carpeta de proyecto, id de sesión o parte del nombre del proyecto",
        "h_group_select": "qué analizar",
        "h_group_output": "salida",
        "h_session": "sesión por id (completo o prefijo)",
        "h_here": "sesión más reciente del directorio actual (o de sus carpetas superiores)",
        "h_last": "sesión más reciente (de todos los proyectos o de TARGET)",
        "h_all": "suma todas las sesiones (de TARGET, de --here o de todo)",
        "h_list": "lista las sesiones y sale",
        "h_days": "con --all/--list: solo los últimos N días",
        "h_since": "con --all/--list: solo desde esa fecha (AAAA-MM-DD, hora local)",
        "h_limit": "número de sesiones en listados (por defecto: 20)",
        "h_top": "muestra solo las N filas más caras",
        "h_json": "imprime el reporte en JSON",
        "h_save": "guarda el reporte JSON (por defecto en {path})",
        "h_out": "carpeta para --save",
        "h_no_color": "sin colores",
        "h_lang": "idioma de la salida",
        "h_group_prices": "precios",
        "h_update_prices": "descarga la tabla oficial de precios, la guarda y sale",
        "h_offline": "no se conecta a internet para buscar precios de modelos nuevos",
    },
    "en": {
        "title_session": "TOKEN REVIEWER · Session analysis",
        "title_summary": "TOKEN REVIEWER · Summary of {n} sessions",
        "lbl_title": "Title",
        "lbl_session": "Session",
        "lbl_project": "Project",
        "lbl_start": "Started",
        "lbl_duration": "Duration",
        "lbl_turns": "Turns",
        "lbl_filter": "Filter",
        "lbl_period": "Since",
        "lbl_sessions": "Sessions",
        "api_calls": ("{n} API call", "{n} API calls"),
        "col_prompt": "Prompt",
        "col_calls": "Calls",
        "col_in": "In",
        "col_out": "Out",
        "col_cr": "Cache R",
        "col_cw": "Cache W",
        "col_cost": "Cost",
        "col_date": "Date",
        "col_id": "ID",
        "col_project": "Project",
        "col_title": "Title",
        "total": "TOTAL",
        "no_prompt": "[no prompt]",
        "image": "[image]",
        "showing_top": "Showing the {n} most expensive of {total}.",
        "summary": "SUMMARY",
        "by_model": "By model",
        "calls_word": ("call", "calls"),
        "s_input": "Uncached input",
        "s_output": "Output",
        "s_thinking": "{n} of them thinking",
        "s_cache_read": "Cache read",
        "s_cache_write": "Cache write",
        "s_processed": "Tokens processed",
        "s_hit": "Cache hit rate",
        "s_web": "Web searches",
        "s_cost": "Estimated cost",
        "s_cc_cost": "Per Claude Code",
        "cc_note": "includes internal calls missing from the transcript, such as titles or compaction",
        "price_note": "Estimate at Anthropic API list prices (USD). Pro/Max subscribers don't pay "
                      "per token; Bedrock and Vertex rates differ.",
        "warn_unpriced": ("Unknown model price, excluded from the cost: {model} ({n} call). "
                          "Try --update-prices or add its price to {path}.",
                          "Unknown model price, excluded from the cost: {model} ({n} calls). "
                          "Try --update-prices or add its price to {path}."),
        "warn_fast": "No fast-mode rate known for {model}: the standard rate was used.",
        "warn_cc_price": "Cost of {model} taken from Claude Code's own record (the split per turn "
                         "is approximate).",
        "fetching_prices": "Model missing from the price table ({models}): checking {url}",
        "prices_updated": "Prices updated: {n} models. Saved to {path}",
        "prices_new": "Models missing from the built-in table: {models}",
        "prices_failed": "Could not update prices ({error}).",
        "list_title": "Claude Code sessions",
        "choose": "Pick a number (Enter to cancel): ",
        "save_q": "Save JSON report? [y/N]: ",
        "saved": "Report saved to: {path}",
        "not_saved": "Not saved.",
        "cancelled": "Cancelled.",
        "invalid_choice": "Invalid choice.",
        "no_projects": "Claude Code sessions folder not found: {path}",
        "no_sessions": "No sessions found.",
        "no_match": "No session matches '{q}'.",
        "no_here": "No Claude Code sessions for {path} or its parent folders.",
        "no_file": "Not found: {path}",
        "no_calls": "The session has no API calls with usage data.",
        "hint_list": "Use --list to see the available sessions.",
        "hint_noninteractive": "No interactive terminal: say what to analyze (--here, --last, "
                               "--session ID, --all or a project name).",
        "bad_session_id": "Invalid session id ('{sid}'): using the latest session of the current "
                          "directory.",
        "ambiguous_id": "Several sessions start with '{sid}'; using the most recent.",
        "bad_date": "Invalid date '{value}': use the YYYY-MM-DD format.",
        "yes": ("y", "yes"),
        "h_desc": "Token usage and estimated cost (USD) of Claude Code sessions.",
        "h_target": ".jsonl file, project folder, session id or part of the project name",
        "h_group_select": "what to analyze",
        "h_group_output": "output",
        "h_session": "session by id (full or prefix)",
        "h_here": "latest session of the current directory (or its parent folders)",
        "h_last": "latest session (of all projects or of TARGET)",
        "h_all": "add up every session (of TARGET, of --here or of everything)",
        "h_list": "list sessions and exit",
        "h_days": "with --all/--list: only the last N days",
        "h_since": "with --all/--list: only since that date (YYYY-MM-DD, local time)",
        "h_limit": "number of sessions in listings (default: 20)",
        "h_top": "show only the N most expensive rows",
        "h_json": "print the report as JSON",
        "h_save": "save the JSON report (default folder: {path})",
        "h_out": "folder for --save",
        "h_no_color": "disable colors",
        "h_lang": "output language",
        "h_group_prices": "prices",
        "h_update_prices": "download the official price table, save it and exit",
        "h_offline": "never go online to look up prices of new models",
    },
}


class Style:
    lang = "en"
    color = False
    fancy = False
    width = 100


STYLE = Style()

ANSI = {
    "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m", "red": "\033[31m",
    "green": "\033[32m", "yellow": "\033[33m", "blue": "\033[34m", "cyan": "\033[36m",
}
SYMBOLS = {
    True: {"heavy": "━", "light": "─", "sub": "↳ ", "ellipsis": "…"},
    False: {"heavy": "=", "light": "-", "sub": "> ", "ellipsis": "..."},
}


def t(key: str, **kwargs) -> str:
    text = TEXTS[STYLE.lang].get(key, TEXTS["en"][key])
    if isinstance(text, tuple):   # (singular, plural) según n
        text = text[0] if kwargs.get("n") == 1 else text[1]
    return text.format(**kwargs) if kwargs else text


def c(text: str, *styles: str) -> str:
    if not STYLE.color or not styles:
        return text
    return "".join(ANSI[s] for s in styles) + text + ANSI["reset"]


def sym(name: str) -> str:
    return SYMBOLS[STYLE.fancy][name]


def detect_lang() -> str:
    for var in ("TOKEN_REVIEWER_LANG", "LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        value = os.environ.get(var, "")
        if value and value != "POSIX" and not value.startswith("C"):
            return "es" if value.lower().startswith("es") else "en"
    try:
        loc = locale.getlocale()[0] or ""
    except (ValueError, TypeError):
        loc = ""
    if not loc and os.name == "nt":
        try:
            import ctypes
            if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x0A:
                return "es"
        except Exception:
            pass
    return "es" if loc.lower().startswith(("es", "spanish")) else "en"


def enable_windows_ansi() -> bool:
    if os.name != "nt":
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


def configure_streams() -> None:
    """UTF-8 en tuberías (Claude, | less...) y sin errores por caracteres no representables."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                if stream.isatty():
                    stream.reconfigure(errors="replace")
                else:
                    stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def setup_output(args: argparse.Namespace) -> None:
    tty = sys.stdout.isatty()
    STYLE.fancy = tty and (sys.stdout.encoding or "").lower().replace("-", "").startswith("utf")
    STYLE.color = (tty and not args.no_color and "NO_COLOR" not in os.environ
                   and os.environ.get("TERM") != "dumb" and enable_windows_ansi())
    width = shutil.get_terminal_size((100, 24)).columns if tty else 100
    STYLE.width = max(72, min(width, 160))


# ── formato ───────────────────────────────────────────────────────────────────

def fmt_int(n: int) -> str:
    return f"{n:,}"


def fmt_compact(n: int) -> str:
    if n < 1000:
        return str(n)
    for div, suffix in ((1_000_000_000, "G"), (1_000_000, "M"), (1_000, "k")):
        if n >= div:
            value = n / div
            return (f"{value:.1f}" if value < 100 else f"{value:.0f}") + suffix
    return str(n)


def fmt_cost(cost) -> str:
    if cost is None:
        return "?"
    if cost >= 100:
        return f"${cost:,.2f}"
    if cost >= 0.01:
        return f"${cost:.4f}"
    return f"${cost:.5f}"


def cost_color(cost: float) -> str:
    return "green" if cost < 0.05 else "yellow" if cost < 0.5 else "red"


def fmt_duration(seconds) -> str:
    if seconds is None:
        return "?"
    days, rest = divmod(int(seconds), 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    base = f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{days}d {base}" if days else base


def parse_ts(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def fmt_local(value) -> str:
    dt = parse_ts(value)
    return dt.astimezone().strftime("%Y-%m-%d %H:%M") if dt else "?"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def truncate(text: str, width: int) -> str:
    text = " ".join(text.split())
    if len(text) <= width:
        return text
    ellipsis = sym("ellipsis")
    return text[: max(0, width - len(ellipsis))] + ellipsis


def last_component(path) -> str:
    parts = [p for p in re.split(r"[\\/]", path or "") if p]
    return parts[-1] if parts else (path or "")


def normalize_model(model: str) -> str:
    m = (model or "").strip().lower()
    start = m.find("claude-")
    if start > 0:
        m = m[start:]                           # prefijos de Bedrock: "us.anthropic.claude-..."
    m = re.split(r"[@:\[]", m, maxsplit=1)[0]   # "@fecha" de Vertex, ":0" de Bedrock, "[1m]"
    m = re.sub(r"-v\d+$", "", m)
    m = re.sub(r"-(\d{8}|latest)$", "", m)
    return re.sub(r"-0$", "", m)                # "claude-opus-4-0" -> "claude-opus-4"


def short_model(model: str) -> str:
    norm = normalize_model(model)
    return norm[len("claude-"):] if norm.startswith("claude-") else (model or "?")


# ── rutas y sesiones ──────────────────────────────────────────────────────────

def claude_dir() -> Path:
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env).expanduser() if env else Path.home() / ".claude"


def projects_dir() -> Path:
    return claude_dir() / "projects"


def default_reports_dir() -> Path:
    return claude_dir() / "token-reviewer" / "reports"


def encode_project(path: str) -> str:
    """Nombre de carpeta que Claude Code usa para un directorio de trabajo."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def project_dirs() -> list:
    try:
        return [d for d in projects_dir().iterdir() if d.is_dir()]
    except OSError:
        return []


def session_files(dirs) -> list:
    """(ruta, mtime) de los transcripts de esas carpetas, del más reciente al más antiguo."""
    found = []
    for folder in dirs:
        try:
            entries = list(folder.glob("*.jsonl"))
        except OSError:
            continue
        for path in entries:
            try:
                found.append((path, path.stat().st_mtime))
            except OSError:
                pass
    found.sort(key=lambda item: item[1], reverse=True)
    return found


def subagent_files(path: Path) -> list:
    folder = path.with_suffix("") / "subagents"
    try:
        return sorted(folder.glob("*.jsonl")) if folder.is_dir() else []
    except OSError:
        return []


def matches_filter(dirname: str, query: str) -> bool:
    name = dirname.lower()
    return query.lower() in name or encode_project(query).lower() in name


def find_by_id(session_id: str) -> list:
    try:
        found = [(p, p.stat().st_mtime) for p in projects_dir().glob(f"*/{session_id}*.jsonl")]
    except OSError:
        return []
    found.sort(key=lambda item: item[1], reverse=True)
    return found


def find_here_sessions(dirs) -> list:
    """Sesiones del directorio actual o, si no hay, de la carpeta superior más cercana que tenga."""
    by_name = {}
    for folder in dirs:
        by_name.setdefault(folder.name.lower(), []).append(folder)
    starts = []
    for candidate in (os.getcwd(), os.path.realpath(os.getcwd())):
        candidate = os.path.abspath(candidate)
        if candidate not in starts:
            starts.append(candidate)
    for start in starts:
        current = start
        while True:
            found = session_files(by_name.get(encode_project(current).lower(), []))
            if found:
                return found
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
    # Claude Code acorta los nombres de rutas muy largas: se compara el cwd guardado.
    targets = {os.path.normcase(s) for s in starts}
    return [(p, m) for p, m in session_files(dirs)[:500]
            if os.path.normcase(read_session_info(p)["cwd"] or "") in targets]


# ── lectura de transcripts ────────────────────────────────────────────────────

def parse_line(raw):
    try:
        row = json.loads(raw)
    except ValueError:
        return None
    return row if isinstance(row, dict) else None


def load_rows(path: Path, assistant_only: bool = False) -> list:
    rows = []
    try:
        with open(path, "rb") as handle:
            for raw in handle:
                if assistant_only and b'"assistant"' not in raw and b'"cost-state"' not in raw:
                    continue
                if raw.strip():
                    row = parse_line(raw)
                    if row is not None:
                        rows.append(row)
    except OSError as exc:
        print(c(str(exc), "red"), file=sys.stderr)
    return rows


_DROP_TAGS = ("system-reminder", "ide_opened_file", "ide_selection", "ide_diagnostics",
              "local-command-caveat", "local-command-stdout", "local-command-stderr",
              "command-message", "bash-stdout", "bash-stderr", "user-prompt-submit-hook")
_DROP_RE = re.compile(r"<(%s)\b[^>]*>.*?</\1>" % "|".join(map(re.escape, _DROP_TAGS)), re.S)
_COMMAND_NAME_RE = re.compile(r"<command-name>(.*?)</command-name>", re.S)
_COMMAND_ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.S)
_BASH_INPUT_RE = re.compile(r"<bash-input>(.*?)</bash-input>", re.S)


def clean_prompt(text: str) -> str:
    command = _COMMAND_NAME_RE.search(text)
    if command and command.group(1).strip():
        name = command.group(1).strip()
        name = name if name.startswith("/") else "/" + name
        args = _COMMAND_ARGS_RE.search(text)
        return " ".join(f"{name} {args.group(1) if args else ''}".split())
    bash = _BASH_INPUT_RE.search(text)
    if bash:
        return "!" + " ".join(bash.group(1).split())
    return " ".join(_DROP_RE.sub(" ", text).split())


def prompt_text(row: dict):
    """Texto del prompt si la fila es un mensaje escrito por el usuario; None si no lo es."""
    if row.get("type") != "user" or row.get("isMeta") or row.get("isCompactSummary"):
        return None
    content = (row.get("message") or {}).get("content")
    has_attachment = False
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "tool_result":
                return None
            if kind == "text":
                parts.append(str(block.get("text") or ""))
            elif kind in ("image", "document"):
                has_attachment = True
        text = "\n".join(parts)
    else:
        return None
    text = clean_prompt(text)
    if text.startswith("[Request interrupted"):
        return None
    if not text:
        return t("image") if has_attachment else None
    return text


def read_session_info(path: Path) -> dict:
    """cwd, título y primer prompt leyendo solo el principio y el final del archivo."""
    info = {"cwd": None, "title": None, "first_prompt": None}
    chunk = 256 * 1024
    try:
        with open(path, "rb") as handle:
            head = handle.read(chunk)
            size = handle.seek(0, os.SEEK_END)
            tail = b""
            if size > len(head):
                handle.seek(max(len(head), size - chunk))
                tail = handle.read()
    except OSError:
        return info
    for raw in head.splitlines():
        if info["cwd"] and info["first_prompt"]:
            break
        if b'"cwd"' not in raw:
            continue
        row = parse_line(raw)
        if row:
            info["cwd"] = info["cwd"] or row.get("cwd")
            info["first_prompt"] = info["first_prompt"] or prompt_text(row)
    last_prompt = None
    for block in (tail, head):
        for raw in reversed(block.splitlines()):
            if b'"ai-title"' in raw:
                row = parse_line(raw)
                if row and row.get("aiTitle"):
                    info["title"] = row["aiTitle"]
                    return info
            elif last_prompt is None and b'"last-prompt"' in raw:
                row = parse_line(raw)
                if row and row.get("lastPrompt"):
                    last_prompt = row["lastPrompt"]
    info["title"] = last_prompt or info["first_prompt"]
    return info


# ── uso y coste ───────────────────────────────────────────────────────────────

TOKEN_FIELDS = ("input", "output", "thinking", "cache_read", "cache_write_5m", "cache_write_1h",
                "web_searches")


def _num(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def usage_tokens(usage: dict) -> dict:
    created = _num(usage.get("cache_creation_input_tokens"))
    detail = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else {}
    write_1h = _num(detail.get("ephemeral_1h_input_tokens"))
    write_5m = _num(detail.get("ephemeral_5m_input_tokens"))
    write_5m += max(0, created - write_1h - write_5m)   # sin desglose: se asume TTL de 5 min
    output_detail = usage.get("output_tokens_details")
    server_tools = usage.get("server_tool_use")
    return {
        "input": _num(usage.get("input_tokens")),
        "output": _num(usage.get("output_tokens")),
        "thinking": _num(output_detail.get("thinking_tokens")) if isinstance(output_detail, dict) else 0,
        "cache_read": _num(usage.get("cache_read_input_tokens")),
        "cache_write_5m": write_5m,
        "cache_write_1h": write_1h,
        "web_searches": _num(server_tools.get("web_search_requests")) if isinstance(server_tools, dict) else 0,
    }


# ── tabla de precios ──────────────────────────────────────────────────────────

PRICE_FIELDS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")


def prices_file() -> Path:
    return claude_dir() / "token-reviewer" / "prices.json"


def _full_price(entry) -> dict:
    input_price, output_price, read_price = entry
    return {"input": input_price, "output": output_price, "cache_read": read_price,
            "cache_write_5m": input_price * CACHE_WRITE_5M,
            "cache_write_1h": input_price * CACHE_WRITE_1H}


def _valid_price(entry) -> bool:
    return isinstance(entry, dict) and all(
        isinstance(entry.get(field), (int, float)) and entry[field] >= 0 for field in PRICE_FIELDS)


class PriceBook:
    """Tabla integrada más ~/.claude/token-reviewer/prices.json (descargado o editado a mano)."""

    def __init__(self):
        self.models = {key: _full_price(entry) for key, entry in MODEL_PRICES.items()}
        self.fast = dict(FAST_MULTIPLIER)
        self.local = {}
        self.refreshed = False   # ya se intentó descargar en esta ejecución
        self.load_local()

    def load_local(self) -> None:
        try:
            data = json.loads(prices_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        self.local = data
        # Si la descarga es más reciente que la tabla integrada, manda la descarga; si no,
        # del fichero solo se toman los modelos que la tabla no tiene.
        newer = str(data.get("fetched_at") or "")[:10] >= PRICES_DATE
        models = data.get("models") if isinstance(data.get("models"), dict) else {}
        for key, entry in models.items():
            key = normalize_model(key)
            if _valid_price(entry) and (newer or key not in self.models):
                self.models[key] = {field: float(entry[field]) for field in PRICE_FIELDS}
        fast = data.get("fast_multiplier") if isinstance(data.get("fast_multiplier"), dict) else {}
        for key, value in fast.items():
            key = normalize_model(key)
            if isinstance(value, (int, float)) and value > 0 and (newer or key not in self.fast):
                self.fast[key] = float(value)

    def due_for_check(self) -> bool:
        last = self.local.get("checked_at")
        last = last if isinstance(last, (int, float)) else 0
        return not self.refreshed and time.time() - last >= PRICE_CHECK_INTERVAL

    def info(self) -> dict:
        return {
            "currency": "USD",
            "source": "Anthropic API list prices",
            "builtin_table_date": PRICES_DATE,
            "local_file": str(prices_file()) if self.local else None,
            "local_fetched_at": self.local.get("fetched_at"),
            "web_search_usd": WEB_SEARCH_USD,
        }


_PRICE_BOOK = None


def price_book() -> PriceBook:
    global _PRICE_BOOK
    if _PRICE_BOOK is None:
        _PRICE_BOOK = PriceBook()
    return _PRICE_BOOK


_MONEY_RE = re.compile(r"\$\s*([0-9]+(?:\.[0-9]+)?)")
_SEPARATOR_RE = re.compile(r":?-{3,}:?")
_MODEL_NAME_RE = re.compile(r"claude ([a-z]+) (\d+(?:\.\d+)?)$")


def model_keys_from_name(name: str) -> list:
    """Clave de un nombre de la tabla oficial: "Claude Opus 4.1 (retired)" da "claude-opus-4-1".
    La generación 3 usaba otro orden en sus ids: "Claude Haiku 3.5" da "claude-3-5-haiku"."""
    name = re.sub(r"<sup>.*?</sup>|\[\^\w+\]", "", name)   # notas al pie
    name = re.sub(r"<[^>]+>", "", name).split("(")[0].replace("*", "")
    match = _MODEL_NAME_RE.search(" ".join(name.lower().split()))
    if not match:
        return []
    family, version = match.group(1), match.group(2).replace(".", "-")
    if version.startswith("3"):
        return [f"claude-{version}-{family}"]
    return [f"claude-{family}-{version}"]


def _markdown_tables(text: str) -> list:
    """[(título de la sección en minúsculas, filas)] de las tablas markdown del texto."""
    tables, rows, heading = [], [], ""
    for line in text.splitlines() + [""]:
        stripped = line.strip()
        if len(stripped) > 1 and stripped.startswith("|") and stripped.endswith("|"):
            cells = [cell.strip() for cell in stripped[1:-1].split("|")]
            if not all(_SEPARATOR_RE.fullmatch(cell) for cell in cells if cell):
                rows.append(cells)
            continue
        if rows:
            tables.append((heading, rows))
            rows = []
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip().lower()
    return tables


def parse_price_page(text: str):
    """(precios por modelo, multiplicadores del modo rápido) de la página oficial en markdown."""
    columns = {"base input": "input", "5m": "cache_write_5m", "1h": "cache_write_1h",
               "cache hit": "cache_read", "output": "output"}
    models, fast_rates = {}, {}
    for heading, rows in _markdown_tables(text):
        header = [cell.lower() for cell in rows[0]]
        found = {}
        for i, title in enumerate(header):
            for needle, field in columns.items():
                if needle in title and field not in found:
                    found[field] = i
                    break
        if len(found) == len(columns):
            for row in rows[1:]:
                values = {}
                for field, i in found.items():
                    match = _MONEY_RE.search(row[i]) if i < len(row) else None
                    if match:
                        values[field] = float(match.group(1))
                if len(values) == len(columns):
                    for key in model_keys_from_name(row[0]):
                        models.setdefault(key, values)
        elif "fast" in heading and len(header) >= 2 and "input" in header[1]:
            for row in rows[1:]:
                match = _MONEY_RE.search(row[1]) if len(row) > 1 else None
                if match:
                    for part in row[0].split("/"):
                        for key in model_keys_from_name(part):
                            fast_rates[key] = float(match.group(1))
    fast = {key: round(rate / models[key]["input"], 4)
            for key, rate in fast_rates.items() if key in models and models[key]["input"]}
    return models, fast


def _write_local_prices(data: dict) -> None:
    path = prices_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        pass


def update_prices():
    """Descarga la tabla oficial y la guarda. Devuelve (nº de modelos, modelos que no están en
    la tabla integrada). Si falla, anota el intento para no repetirlo hasta el día siguiente."""
    import urllib.request

    book = price_book()
    book.refreshed = True
    data = dict(book.local)
    data["checked_at"] = time.time()
    try:
        request = urllib.request.Request(PRICES_URL,
                                         headers={"User-Agent": f"token-reviewer/{__version__}"})
        with urllib.request.urlopen(request, timeout=10) as response:
            text = response.read().decode("utf-8", errors="replace")
        models, fast = parse_price_page(text)
        if len(models) < 5:
            raise ValueError("unrecognized price page format")
    except Exception:
        _write_local_prices(data)
        raise
    merged = dict(data.get("models") or {})
    merged.update(models)
    merged_fast = dict(data.get("fast_multiplier") or {})
    merged_fast.update(fast)
    data.update(source=PRICES_URL, fetched_at=now_iso(), models=merged,
                fast_multiplier=merged_fast)
    _write_local_prices(data)
    book.load_local()
    return len(models), sorted(key for key in models if key not in MODEL_PRICES)


# ── coste ─────────────────────────────────────────────────────────────────────

def call_cost(model: str, tokens: dict, fast: bool, geo_us: bool = False):
    """(coste en USD o None si el modelo no tiene precio, True si faltó la tarifa rápida)."""
    book = price_book()
    key = normalize_model(model)
    price = book.models.get(key)
    if price is None:
        return None, False
    multiplier, fast_unpriced = 1.0, False
    if fast:
        multiplier = book.fast.get(key, 1.0)
        fast_unpriced = key not in book.fast
    if geo_us and key not in GEO_EXEMPT and not key.startswith("claude-3"):
        multiplier *= GEO_US_MULTIPLIER
    cost = sum(tokens[field] * price[field] for field in PRICE_FIELDS) * multiplier / 1_000_000
    return cost + tokens["web_searches"] * WEB_SEARCH_USD, fast_unpriced


class Tally:
    __slots__ = TOKEN_FIELDS + ("calls", "cost", "unpriced_calls")

    def __init__(self):
        for field in TOKEN_FIELDS:
            setattr(self, field, 0)
        self.calls = 0
        self.cost = 0.0
        self.unpriced_calls = 0

    def add(self, tokens: dict, cost) -> None:
        for field in TOKEN_FIELDS:
            setattr(self, field, getattr(self, field) + tokens[field])
        self.calls += 1
        if cost is None:
            self.unpriced_calls += 1
        else:
            self.cost += cost

    def to_dict(self) -> dict:
        cache_write = self.cache_write_5m + self.cache_write_1h
        prompt_side = self.input + self.cache_read + cache_write
        return {
            "api_calls": self.calls,
            "tokens": {
                "input": self.input,
                "output": self.output,
                "thinking": self.thinking,
                "cache_read": self.cache_read,
                "cache_write_5m": self.cache_write_5m,
                "cache_write_1h": self.cache_write_1h,
                "cache_write": cache_write,
                "total": prompt_side + self.output,
            },
            "cache_hit_ratio": round(self.cache_read / prompt_side, 4) if prompt_side else None,
            "web_searches": self.web_searches,
            "cost_usd": round(self.cost, 6),
            "unpriced_api_calls": self.unpriced_calls,
        }


def assign_costs(calls: list) -> None:
    for call in calls:
        call["cost"], call["fast_unpriced"] = call_cost(
            call["model"], call["tokens"], call["fast"], call["geo_us"])
        call["cost_source"] = "price" if call["cost"] is not None else None


def price_calls(calls: list, allow_fetch: bool) -> None:
    """Pone precio a cada llamada; si falta algún modelo, intenta actualizar la tabla."""
    assign_costs(calls)
    unknown = sorted({normalize_model(call["model"]) for call in calls if call["cost"] is None})
    if not unknown or not allow_fetch or not price_book().due_for_check():
        return
    note(t("fetching_prices", models=", ".join(unknown), url=PRICES_URL))
    try:
        update_prices()
    except Exception as exc:   # sin red, proxy, SSL, página cambiada...: se sigue sin conexión
        note(t("prices_failed", error=exc))
        return
    assign_costs(calls)


def _weight(tokens: dict) -> float:
    """Peso relativo de una llamada con las proporciones de precio habituales."""
    return (tokens["input"] + 5 * tokens["output"] + 0.1 * tokens["cache_read"]
            + CACHE_WRITE_5M * tokens["cache_write_5m"] + CACHE_WRITE_1H * tokens["cache_write_1h"])


def apply_reported_costs(calls: list, model_usage) -> None:
    """Reparte el coste que registró Claude Code entre las llamadas de modelos sin precio."""
    if not isinstance(model_usage, dict):
        return
    reported = {normalize_model(name): usage["costUSD"] for name, usage in model_usage.items()
                if isinstance(usage, dict) and isinstance(usage.get("costUSD"), (int, float))}
    groups = {}
    for call in calls:
        if call["cost"] is None:
            groups.setdefault(normalize_model(call["model"]), []).append(call)
    for key, group in groups.items():
        if key not in reported:
            continue
        weights = [_weight(call["tokens"]) for call in group]
        total = sum(weights)
        for call, weight in zip(group, weights):
            call["cost"] = reported[key] * (weight / total if total else 1 / len(group))
            call["cost_source"] = "claude-code"


def tally_calls(calls: list):
    total, by_model = Tally(), {}
    for call in calls:
        total.add(call["tokens"], call["cost"])
        by_model.setdefault(call["model"], Tally()).add(call["tokens"], call["cost"])
    models = [dict(model=model, **tally.to_dict()) for model, tally in by_model.items()]
    models.sort(key=lambda m: m["cost_usd"], reverse=True)
    return total, models


def call_warnings(calls: list) -> list:
    unpriced, reported, fast = {}, set(), set()
    for call in calls:
        if call["cost"] is None:
            unpriced[call["model"]] = unpriced.get(call["model"], 0) + 1
        elif call["cost_source"] == "claude-code":
            reported.add(call["model"])
        if call["fast_unpriced"]:
            fast.add(call["model"])
    return ([t("warn_unpriced", model=m, n=n, path=prices_file()) for m, n in sorted(unpriced.items())]
            + [t("warn_cc_price", model=m) for m in sorted(reported)]
            + [t("warn_fast", model=m) for m in sorted(fast)])


# ── análisis ──────────────────────────────────────────────────────────────────

def _update_meta(meta: dict, row: dict) -> None:
    for meta_key, row_key in (("session_id", "sessionId"), ("cwd", "cwd"), ("version", "version")):
        if not meta.get(meta_key) and row.get(row_key):
            meta[meta_key] = row[row_key]
    stamp = row.get("timestamp")
    if isinstance(stamp, str) and stamp:
        if not meta.get("start") or stamp < meta["start"]:
            meta["start"] = stamp
        if not meta.get("end") or stamp > meta["end"]:
            meta["end"] = stamp
    kind = row.get("type")
    if kind == "ai-title" and row.get("aiTitle"):
        meta["title"] = row["aiTitle"]
    elif kind == "cost-state":
        if isinstance(row.get("totalCostUSD"), (int, float)):
            meta["cost_state"] = row["totalCostUSD"]
        if isinstance(row.get("modelUsage"), dict):
            meta["cost_state_models"] = row["modelUsage"]


def _scan_file(path: Path, data: dict, seen: dict, subagent_file: bool, detailed: bool) -> None:
    rows = load_rows(path, assistant_only=not detailed)
    file_id = str(path)
    by_uuid = {r["uuid"]: r for r in rows if isinstance(r.get("uuid"), str)} if detailed else {}
    owner = {}   # uuid -> uuid del prompt que originó esa rama de la conversación

    def owner_prompt(uuid):
        chain, visited, result = [], set(), None
        while uuid and uuid not in visited:
            if uuid in owner:
                result = owner[uuid]
                break
            row = by_uuid.get(uuid)
            if row is None:
                break
            visited.add(uuid)
            chain.append(uuid)
            text = prompt_text(row)
            if text is not None:
                result = uuid
                data["prompts"][(file_id, uuid)] = (row.get("timestamp") or "", text)
                break
            # Tras compactar, la rama sigue por logicalParentUuid.
            uuid = row.get("parentUuid") or row.get("logicalParentUuid")
        for item in chain:
            owner[item] = result
        return result

    for row in rows:
        if not subagent_file:
            _update_meta(data["meta"], row)
        if row.get("type") != "assistant":
            continue
        message = row.get("message")
        usage = message.get("usage") if isinstance(message, dict) else None
        if not isinstance(usage, dict):
            continue
        model = str(message.get("model") or "?")
        if model == "<synthetic>":
            continue
        tokens = usage_tokens(usage)
        # Claude Code escribe una línea por bloque (thinking, text, tool_use) de la misma
        # respuesta, todas con el mismo message.id y el mismo usage: se cuenta una vez.
        key = message.get("id") or row.get("requestId") or row.get("uuid") or f"{file_id}#{len(seen)}"
        previous = seen.get(key)
        if previous is not None:
            if tokens["output"] > previous["tokens"]["output"]:
                previous["tokens"] = tokens
            continue
        call = {
            "ts": row.get("timestamp") or "",
            "model": model,
            "tokens": tokens,
            "fast": usage.get("speed") == "fast",
            "geo_us": str(usage.get("inference_geo") or "").lower() == "us",
            "subagent": subagent_file or bool(row.get("isSidechain")),
            "turn": (file_id, owner_prompt(row.get("uuid"))) if detailed else None,
        }
        seen[key] = call
        data["calls"].append(call)


def scan_session(path: Path, detailed: bool = True, seen=None) -> dict:
    data = {"meta": {}, "calls": [], "prompts": {}}
    seen = {} if seen is None else seen
    _scan_file(path, data, seen, subagent_file=False, detailed=detailed)
    for sub in subagent_files(path):
        _scan_file(sub, data, seen, subagent_file=True, detailed=detailed)
    return data


def build_turns(data: dict) -> list:
    turns = {}
    for call in data["calls"]:
        key = call["turn"]
        turn = turns.get(key)
        if turn is None:
            stamp, text = data["prompts"].get(key, (call["ts"], None))
            turn = turns[key] = {"timestamp": stamp or call["ts"], "prompt": text,
                                 "subagent": call["subagent"], "models": [], "tally": Tally()}
        turn["tally"].add(call["tokens"], call["cost"])
        if call["model"] not in turn["models"]:
            turn["models"].append(call["model"])
    ordered = sorted(turns.values(), key=lambda item: item["timestamp"] or "")
    return [dict(index=i, timestamp=turn["timestamp"], prompt=turn["prompt"],
                 subagent=turn["subagent"], models=turn["models"], **turn["tally"].to_dict())
            for i, turn in enumerate(ordered, 1)]


def session_report(path: Path, allow_fetch: bool = True) -> dict:
    data = scan_session(path)
    meta = data["meta"]
    price_calls(data["calls"], allow_fetch)
    apply_reported_costs(data["calls"], meta.get("cost_state_models"))
    total, models = tally_calls(data["calls"])
    start, end = parse_ts(meta.get("start")), parse_ts(meta.get("end"))
    cost_state = meta.get("cost_state")
    return {
        "tool": "token-reviewer",
        "tool_version": __version__,
        "kind": "session",
        "session_id": meta.get("session_id") or path.stem,
        "title": meta.get("title"),
        "project": meta.get("cwd"),
        "file": str(path),
        "claude_code_version": meta.get("version"),
        "analyzed_at": now_iso(),
        "session_start": meta.get("start"),
        "session_end": meta.get("end"),
        "duration_seconds": int((end - start).total_seconds()) if start and end else None,
        "pricing": price_book().info(),
        "turns": build_turns(data),
        "by_model": models,
        "totals": total.to_dict(),
        "claude_code_reported_cost_usd": round(cost_state, 6) if cost_state is not None else None,
        "warnings": call_warnings(data["calls"]),
    }


def aggregate_report(entries: list, label, since_iso, allow_fetch: bool = True) -> dict:
    seen, scanned = {}, []
    # De la más antigua a la más reciente: si una sesión reanudada copia mensajes de otra,
    # esas llamadas se quedan en la sesión original.
    for path, _mtime in sorted(entries, key=lambda item: item[1]):
        data = scan_session(path, detailed=False, seen=seen)
        if data["calls"]:
            scanned.append((path, data))
    price_calls([call for _path, data in scanned for call in data["calls"]], allow_fetch)
    sessions, all_calls = [], []
    for path, data in scanned:
        apply_reported_costs(data["calls"], data["meta"].get("cost_state_models"))
        calls = [call for call in data["calls"] if not since_iso or call["ts"] >= since_iso]
        if not calls:
            continue
        total, _models = tally_calls(calls)
        all_calls.extend(calls)
        meta = data["meta"]
        sessions.append(dict(
            session_id=meta.get("session_id") or path.stem,
            title=read_session_info(path)["title"],
            project=meta.get("cwd"),
            file=str(path),
            session_start=meta.get("start"),
            session_end=meta.get("end"),
            **total.to_dict()))
    sessions.sort(key=lambda s: s["session_start"] or "", reverse=True)
    total, models = tally_calls(all_calls)
    return {
        "tool": "token-reviewer",
        "tool_version": __version__,
        "kind": "summary",
        "filter": label,
        "since": since_iso,
        "analyzed_at": now_iso(),
        "pricing": price_book().info(),
        "sessions": sessions,
        "by_model": models,
        "totals": total.to_dict(),
        "warnings": call_warnings(all_calls),
    }


# ── salida de texto ───────────────────────────────────────────────────────────

def rule(kind: str = "heavy") -> str:
    return sym(kind) * STYLE.width


def print_header(title: str, fields: list) -> None:
    fields = [(label, value) for label, value in fields if value not in (None, "")]
    width = max((len(label) for label, _ in fields), default=0)
    print()
    print(c(rule(), "cyan", "bold"))
    print(c("  " + title, "cyan", "bold"))
    print(c(rule(), "cyan", "bold"))
    for label, value in fields:
        print(f"  {c(label.ljust(width), 'dim')} : {value}")
    print(c(rule(), "cyan", "bold"))
    print()


def table_row(specs: list, cells: list) -> str:
    out = []
    for (_title, width, align), cell in zip(specs, cells):
        text, color = cell if isinstance(cell, tuple) else (cell, None)
        text = truncate(text, width) if align == "<" else text
        padded = text.ljust(width) if align == "<" else text.rjust(width)
        out.append(c(padded, color) if color else padded)
    return ("  " + "  ".join(out)).rstrip()


def print_table(specs: list, rows: list, total=None) -> None:
    print(c(table_row(specs, [title for title, _w, _a in specs]), "bold", "blue"))
    print(c("  " + rule("light")[: STYLE.width - 2], "dim"))
    for row in rows:
        print(table_row(specs, row))
    if total is not None:
        print(c("  " + rule("light")[: STYLE.width - 2], "dim"))
        print(c(table_row(specs, total), "bold"))


def token_cells(item: dict) -> list:
    tokens = item["tokens"]
    return [fmt_compact(tokens["input"]), fmt_compact(tokens["output"]),
            fmt_compact(tokens["cache_read"]), fmt_compact(tokens["cache_write"])]


def cost_cell(item: dict):
    if item["api_calls"] and item["unpriced_api_calls"] == item["api_calls"]:
        return ("?", "yellow")
    return (fmt_cost(item["cost_usd"]), cost_color(item["cost_usd"]))


def pick_rows(items: list, top) -> list:
    if top and len(items) > top:
        return sorted(items, key=lambda item: item["cost_usd"], reverse=True)[:top]
    return items


def print_summary(totals: dict, models: list, warnings: list, reported_cost=None) -> None:
    print()
    print(c(rule(), "cyan", "bold"))
    print(c("  " + t("summary"), "bold"))
    print(c(rule(), "cyan", "bold"))
    if models:
        print(f"  {t('by_model')}:")
        name_width = max(len(short_model(m["model"])) for m in models)
        for m in models:
            cost = "?" if m["unpriced_api_calls"] == m["api_calls"] else fmt_cost(m["cost_usd"])
            print(f"    {short_model(m['model']).ljust(name_width)}  "
                  f"{m['api_calls']:>6} {t('calls_word', n=m['api_calls']):<8}  {cost:>10}")
        print()
    tokens = totals["tokens"]
    output = fmt_int(tokens["output"])
    if tokens["thinking"]:
        output += f" ({t('s_thinking', n=fmt_int(tokens['thinking']))})"
    cache_write = fmt_int(tokens["cache_write"])
    if tokens["cache_write"]:
        cache_write += (f" (5 min: {fmt_int(tokens['cache_write_5m'])}, "
                        f"1 h: {fmt_int(tokens['cache_write_1h'])})")
    lines = [
        (t("s_input"), fmt_int(tokens["input"])),
        (t("s_output"), output),
        (t("s_cache_read"), fmt_int(tokens["cache_read"])),
        (t("s_cache_write"), cache_write),
        (t("s_processed"), fmt_int(tokens["total"])),
    ]
    if totals["cache_hit_ratio"] is not None:
        lines.append((t("s_hit"), f"{totals['cache_hit_ratio'] * 100:.1f} %"))
    if totals["web_searches"]:
        lines.append((t("s_web"), fmt_int(totals["web_searches"])))
    width = max(len(label) for label in [l for l, _ in lines] + [t("s_cost"), t("s_cc_cost")])
    for label, value in lines:
        print(f"  {label.ljust(width)} : {c(value, 'bold')}")
    print(f"  {c(t('s_cost').ljust(width), 'bold')} : "
          f"{c(fmt_cost(totals['cost_usd']), 'green', 'bold')}")
    if reported_cost is not None:
        print(f"  {t('s_cc_cost').ljust(width)} : {fmt_cost(reported_cost)}  "
              f"{c('(' + t('cc_note') + ')', 'dim')}")
    print(c(rule(), "cyan", "bold"))
    for warning in warnings:
        print(c("  ! " + warning, "yellow"))
    print(c("  " + t("price_note"), "dim"))
    print()


def print_session(report: dict, top=None) -> None:
    totals = report["totals"]
    print_header(t("title_session"), [
        (t("lbl_title"), report["title"]),
        (t("lbl_session"), report["session_id"]),
        (t("lbl_project"), report["project"]),
        (t("lbl_start"), fmt_local(report["session_start"])),
        (t("lbl_duration"), fmt_duration(report["duration_seconds"])),
        (t("lbl_turns"), f"{len(report['turns'])} ({t('api_calls', n=totals['api_calls'])})"),
    ])
    fixed = 4 + 5 + 6 + 6 + 7 + 7 + 9 + 2 * 7 + 2
    specs = [("#", 4, ">"), (t("col_prompt"), max(12, STYLE.width - fixed), "<"),
             (t("col_calls"), 5, ">"), (t("col_in"), 6, ">"), (t("col_out"), 6, ">"),
             (t("col_cr"), 7, ">"), (t("col_cw"), 7, ">"), (t("col_cost"), 9, ">")]
    shown = pick_rows(report["turns"], top)
    rows = []
    for turn in shown:
        prompt = turn["prompt"] or t("no_prompt")
        if turn["subagent"]:
            prompt = sym("sub") + prompt
        rows.append([str(turn["index"]), prompt, str(turn["api_calls"])]
                    + token_cells(turn) + [cost_cell(turn)])
    total_row = ["", t("total"), str(totals["api_calls"])] + token_cells(totals) + [cost_cell(totals)]
    print_table(specs, rows, total_row)
    if len(shown) < len(report["turns"]):
        print(c("  " + t("showing_top", n=len(shown), total=len(report["turns"])), "dim"))
    print_summary(totals, report["by_model"], report["warnings"],
                  report["claude_code_reported_cost_usd"])


def print_aggregate(report: dict, top=None) -> None:
    totals = report["totals"]
    print_header(t("title_summary", n=len(report["sessions"])), [
        (t("lbl_filter"), report["filter"]),
        (t("lbl_period"), fmt_local(report["since"]) if report["since"] else None),
        (t("lbl_sessions"), f"{len(report['sessions'])} ({t('api_calls', n=totals['api_calls'])})"),
    ])
    fixed = 4 + 16 + 18 + 6 + 10 + 2 * 5 + 2
    specs = [("#", 4, ">"), (t("col_date"), 16, "<"), (t("col_project"), 18, "<"),
             (t("col_title"), max(12, STYLE.width - fixed), "<"),
             (t("col_calls"), 6, ">"), (t("col_cost"), 10, ">")]
    numbered = [dict(session, index=i) for i, session in enumerate(report["sessions"], 1)]
    shown = pick_rows(numbered, top)
    rows = [[str(s["index"]), fmt_local(s["session_start"]), last_component(s["project"]) or "?",
             s["title"] or "", str(s["api_calls"]), cost_cell(s)] for s in shown]
    total_row = ["", "", "", t("total"), str(totals["api_calls"]), cost_cell(totals)]
    print_table(specs, rows, total_row)
    if len(shown) < len(numbered):
        print(c("  " + t("showing_top", n=len(shown), total=len(numbered)), "dim"))
    print_summary(totals, report["by_model"], report["warnings"])


def print_session_list(entries: list) -> None:
    print()
    print(c("  " + t("list_title"), "bold", "cyan"))
    fixed = 3 + 16 + 8 + 20 + 2 * 4 + 2
    specs = [("#", 3, ">"), (t("col_date"), 16, "<"), (t("col_id"), 8, "<"),
             (t("col_project"), 20, "<"), (t("col_title"), max(12, STYLE.width - fixed), "<")]
    rows = []
    for i, (path, mtime) in enumerate(entries, 1):
        info = read_session_info(path)
        project = last_component(info["cwd"]) if info["cwd"] else path.parent.name
        date = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
        rows.append([str(i), date, path.stem[:8], project, info["title"] or ""])
    print_table(specs, rows)
    print()


# ── interacción ───────────────────────────────────────────────────────────────

def ask(prompt: str):
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None


def error(message: str) -> None:
    print(c(message, "red"), file=sys.stderr)


def note(message: str) -> None:
    print(c(message, "dim"), file=sys.stderr)


def choose(entries: list):
    print_session_list(entries)
    answer = ask(c("  " + t("choose"), "bold"))
    if not answer:
        print(c("  " + t("cancelled"), "dim"))
        return None
    try:
        index = int(answer) - 1
    except ValueError:
        index = -1
    if 0 <= index < len(entries):
        return entries[index][0]
    error("  " + t("invalid_choice"))
    return None


def save_report(report: dict, out_dir) -> Path:
    folder = Path(out_dir).expanduser() if out_dir else default_reports_dir()
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if report["kind"] == "session":
        name = f"session_{report['session_id'][:8]}_{stamp}.json"
    else:
        slug = re.sub(r"[^A-Za-z0-9]+", "-", report["filter"] or "all").strip("-")[:40] or "all"
        name = f"summary_{slug}_{stamp}.json"
    path = folder / name
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def emit(report: dict, args: argparse.Namespace, interactive: bool) -> None:
    if args.json:
        # ASCII puro: se lee bien aunque la consola no use UTF-8.
        sys.stdout.write(json.dumps(report, ensure_ascii=True, indent=2) + "\n")
    elif report["kind"] == "session":
        print_session(report, args.top)
    else:
        print_aggregate(report, args.top)
    stream = sys.stderr if args.json else sys.stdout
    if args.save:
        path = save_report(report, args.out)
        print(c("  " + t("saved", path=path), "green"), file=stream)
    elif interactive:
        answer = ask(c("  " + t("save_q"), "bold"))
        if answer and answer.lower() in TEXTS[STYLE.lang]["yes"]:
            path = save_report(report, args.out)
            print(c("  " + t("saved", path=path), "green"))
        elif answer is not None:
            print(c("  " + t("not_saved"), "dim"))


# ── selección de sesiones ─────────────────────────────────────────────────────

def since_cutoff(args: argparse.Namespace):
    """Instante de corte de --days/--since como (epoch, ISO UTC), o (None, None)."""
    cutoff = None
    if args.days:
        cutoff = time.time() - args.days * 86400
    if args.since:
        start = datetime.strptime(args.since, "%Y-%m-%d").timestamp()
        cutoff = max(cutoff or start, start)
    if cutoff is None:
        return None, None
    iso = datetime.fromtimestamp(cutoff, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return cutoff, iso


def select_many(args: argparse.Namespace, cutoff):
    target = Path(args.target).expanduser() if args.target else None
    if target is not None and target.is_dir():
        entries = session_files([target])
    elif args.here:
        entries = find_here_sessions(project_dirs())
    elif args.target:
        entries = session_files([d for d in project_dirs() if matches_filter(d.name, args.target)])
    else:
        entries = session_files(project_dirs())
    if cutoff is not None:
        entries = [(path, mtime) for path, mtime in entries if mtime >= cutoff]
    if not entries:
        if args.here:
            error(t("no_here", path=os.getcwd()))
        elif args.target:
            error(t("no_match", q=args.target))
        else:
            error(t("no_sessions"))
    return entries


def select_one(args: argparse.Namespace, interactive: bool):
    """Ruta de la sesión a analizar, o None (el motivo ya se ha mostrado)."""
    if args.session:
        session_id = args.session.strip()
        if re.fullmatch(r"[A-Za-z0-9_-]{4,}", session_id):
            found = find_by_id(session_id)
            if not found:
                error(t("no_match", q=session_id))
                note(t("hint_list"))
                return None
            if len(found) > 1 and found[0][0].stem != session_id:
                note(t("ambiguous_id", sid=session_id))
            return found[0][0]
        # Por ejemplo, un "${CLAUDE_SESSION_ID}" que no se sustituyó.
        note(t("bad_session_id", sid=session_id))
        args.here = True
    if args.here:
        found = find_here_sessions(project_dirs())
        if not found:
            error(t("no_here", path=os.getcwd()))
            return None
        return found[0][0]
    if args.target:
        target = Path(args.target).expanduser()
        if target.is_file():
            return target
        if target.is_dir():
            found = session_files([target])
            if not found:
                error(t("no_sessions"))
                return None
            if interactive and len(found) > 1 and not args.last:
                return choose(found[: args.limit])
            return found[0][0]
        if re.fullmatch(r"[0-9a-fA-F-]{6,}", args.target):
            found = find_by_id(args.target)
            if found:
                return found[0][0]
        found = session_files([d for d in project_dirs() if matches_filter(d.name, args.target)])
        if found:
            return found[0][0]
        looks_like_path = args.target.endswith(".jsonl") or "/" in args.target or "\\" in args.target
        error(t("no_file", path=target) if looks_like_path else t("no_match", q=args.target))
        note(t("hint_list"))
        return None
    found = session_files(project_dirs())
    if not found:
        error(t("no_sessions"))
        return None
    if args.last:
        return found[0][0]
    if interactive:
        return choose(found[: args.limit])
    print_session_list(found[: args.limit])
    note(t("hint_noninteractive"))
    return None


# ── main ──────────────────────────────────────────────────────────────────────

def parse_args(argv) -> argparse.Namespace:
    lang = None
    for i, arg in enumerate(argv):
        if arg.startswith("--lang="):
            lang = arg.split("=", 1)[1]
        elif arg == "--lang" and i + 1 < len(argv):
            lang = argv[i + 1]
    STYLE.lang = lang if lang in TEXTS else detect_lang()

    parser = argparse.ArgumentParser(
        prog="token_reviewer.py", description=t("h_desc"),
        epilog="token_reviewer.py --here | --session ID | MatchBar | --all --days 7 | --list")
    parser.add_argument("target", nargs="?", metavar="TARGET", help=t("h_target"))
    select = parser.add_argument_group(t("h_group_select"))
    select.add_argument("--session", metavar="ID", help=t("h_session"))
    select.add_argument("--here", action="store_true", help=t("h_here"))
    select.add_argument("--last", action="store_true", help=t("h_last"))
    select.add_argument("--all", action="store_true", help=t("h_all"))
    select.add_argument("--list", action="store_true", help=t("h_list"))
    select.add_argument("--days", type=float, metavar="N", help=t("h_days"))
    select.add_argument("--since", metavar="YYYY-MM-DD", help=t("h_since"))
    select.add_argument("--limit", type=int, default=20, metavar="N", help=t("h_limit"))
    output = parser.add_argument_group(t("h_group_output"))
    output.add_argument("--top", type=int, metavar="N", help=t("h_top"))
    output.add_argument("--json", action="store_true", help=t("h_json"))
    output.add_argument("--save", action="store_true", help=t("h_save", path=default_reports_dir()))
    output.add_argument("--out", metavar="DIR", help=t("h_out"))
    output.add_argument("--no-color", action="store_true", help=t("h_no_color"))
    output.add_argument("--lang", choices=sorted(TEXTS), help=t("h_lang"))
    prices = parser.add_argument_group(t("h_group_prices"))
    prices.add_argument("--update-prices", action="store_true", help=t("h_update_prices"))
    prices.add_argument("--offline", action="store_true", help=t("h_offline"))
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)
    if args.since:
        try:
            datetime.strptime(args.since, "%Y-%m-%d")
        except ValueError:
            parser.error(t("bad_date", value=args.since))
    return args


def main(argv=None) -> int:
    configure_streams()
    args = parse_args(sys.argv[1:] if argv is None else argv)
    setup_output(args)
    interactive = sys.stdin.isatty() and sys.stdout.isatty() and not args.json
    allow_fetch = not args.offline and os.environ.get("TOKEN_REVIEWER_OFFLINE", "") in ("", "0")

    if args.update_prices:
        try:
            count, new = update_prices()
        except Exception as exc:
            error(t("prices_failed", error=exc))
            return 1
        print(t("prices_updated", n=count, path=prices_file()))
        if new:
            print(t("prices_new", models=", ".join(new)))
        return 0

    target_exists = bool(args.target) and Path(args.target).expanduser().exists()
    if not projects_dir().is_dir() and not target_exists:
        error(t("no_projects", path=projects_dir()))
        return 1

    if args.list or args.all:
        cutoff, since_iso = since_cutoff(args)
        entries = select_many(args, cutoff)
        if not entries:
            return 1
        if args.list:
            print_session_list(entries[: args.limit])
            return 0
        label = args.target or (os.getcwd() if args.here else None)
        emit(aggregate_report(entries, label, since_iso, allow_fetch), args, interactive)
        return 0

    path = select_one(args, interactive)
    if path is None:
        return 1
    report = session_report(path, allow_fetch)
    if not report["turns"]:
        error(t("no_calls"))
        return 1
    emit(report, args, interactive)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)
    except BrokenPipeError:
        # La salida se cortó (por ejemplo, con | head): no es un error.
        try:
            sys.stdout = open(os.devnull, "w")
        except OSError:
            pass
        sys.exit(0)
