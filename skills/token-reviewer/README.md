# token-reviewer

Tokens y coste estimado (USD) de tus sesiones de Claude Code, turno a turno. *English below.*

Lee los transcripts que Claude Code guarda en tu equipo (`~/.claude/projects/`) y te dice cuánto ha costado cada cosa que le pediste:

- **Por turno:** el prompt, cuántas llamadas a la API generó, los tokens de entrada, salida, caché leída y caché escrita, y su coste.
- **Por modelo:** si en una sesión usas varios modelos, cada llamada se cobra con su tarifa y el resumen los separa.
- **Totales:** tokens procesados, porcentaje de acierto de caché, búsquedas web y coste estimado, junto al coste que registró el propio Claude Code para comparar.
- **Sesiones, proyectos o periodos:** la sesión actual, una anterior, todas las de un proyecto o todo lo gastado en los últimos N días.

Cuenta cada respuesta de la API una sola vez (el transcript la guarda en varias líneas), incluye subagentes, distingue la caché de 5 minutos de la de 1 hora y aplica el modo rápido y la inferencia en EE. UU. Los totales coinciden con los que calcula Claude Code.

## Uso con Claude

Pregunta con naturalidad:

- "¿Cuánto me ha costado esta sesión?"
- "¿Qué prompts han sido los más caros?"
- "¿Cuánto he gastado esta semana en el proyecto MatchBar?"

O invócala con `/token-reviewer`, con argumentos opcionales: `here`, `last`, `all`, `list`, un nombre de proyecto, un id de sesión o `--days N`.

## Uso desde la terminal

El script funciona sin Claude. En Windows usa `python` o `py -3` en lugar de `python3`.

```bash
python3 scripts/token_reviewer.py                    # menú: elige una sesión reciente
python3 scripts/token_reviewer.py --here             # última sesión del directorio actual
python3 scripts/token_reviewer.py MatchBar           # última sesión de un proyecto
python3 scripts/token_reviewer.py --all MatchBar     # todas las sesiones del proyecto, sumadas
python3 scripts/token_reviewer.py --all --days 7     # todo lo de los últimos 7 días
python3 scripts/token_reviewer.py --list             # sesiones disponibles
python3 scripts/token_reviewer.py --help             # todas las opciones
```

| Opción | Para qué |
|---|---|
| `--session ID` | Una sesión concreta (id completo o sus primeros caracteres) |
| `--top N` | Muestra solo las N filas más caras (los totales siguen siendo completos) |
| `--since AAAA-MM-DD` / `--days N` | Limita `--all` y `--list` a un periodo |
| `--json` | Salida en JSON, para procesarla con otras herramientas |
| `--save` / `--out DIR` | Guarda el reporte JSON (por defecto en `~/.claude/token-reviewer/reports/`) |
| `--lang es\|en` | Idioma de la salida (por defecto, el del sistema) |
| `--update-prices` / `--offline` | Ver [Precios](#precios) |

Los reportes JSON incluyen el texto completo de tus prompts: revísalos antes de compartirlos.

## Precios

El coste es una estimación con los precios de lista de la API de Anthropic. Con una suscripción Pro o Max no pagas por token, y en Bedrock o Vertex las tarifas son otras.

La skill no se queda anticuada cuando sale un modelo nuevo. Si encuentra uno que no está en su tabla:

1. Descarga la [tabla oficial de precios](https://platform.claude.com/docs/en/about-claude/pricing), como mucho una vez al día, y la guarda en `~/.claude/token-reviewer/prices.json`.
2. Si no hay conexión, usa el coste que registró el propio Claude Code para ese modelo.
3. Si tampoco lo hay, lo avisa y lo deja fuera del total, en lugar de inventarse un precio.

`--update-prices` fuerza la descarga y `--offline` (o `TOKEN_REVIEWER_OFFLINE=1`) evita cualquier conexión. En `prices.json` puedes añadir modelos a mano; ese fichero no se pierde al actualizar el plugin.

## Requisitos

- Claude Code en tu equipo (la skill lee sus transcripts locales; no funciona en el chat de claude.ai).
- Python 3.8 o superior. Solo usa la librería estándar.
- Windows, macOS o Linux.

## Mantenimiento

- Tabla de precios base: `MODEL_PRICES` al principio de `scripts/token_reviewer.py`. Al revisarla, actualiza también `PRICES_DATE`.
- Al publicar cambios, sube la versión en `__version__` del script y en la entrada de `.claude-plugin/marketplace.json`.

---

## English

Token usage and estimated cost (USD, Anthropic API list prices) of your Claude Code sessions, turn by turn, with the split by model, cache and subagents. It reads the local transcripts in `~/.claude/projects/` and its totals match the cost Claude Code records.

Ask Claude "how much did this session cost?" or "which prompts were the most expensive?", or run `/token-reviewer`. From a terminal: `python3 scripts/token_reviewer.py --help`. The output follows your locale (English or Spanish; force it with `--lang en`).

When a model is missing from the built-in price table, the script downloads the official pricing page (at most once a day) into `~/.claude/token-reviewer/prices.json`, falls back to the cost recorded by Claude Code, and otherwise warns instead of guessing. `--offline` disables any network access.

Requires Claude Code on your machine and Python 3.8+ (standard library only).
