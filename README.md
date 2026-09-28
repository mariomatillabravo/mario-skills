# mario-skills

Colección de skills para [Claude Code](https://code.claude.com). Cada skill se instala por separado como plugin. *English below.*

## Skills

| Skill | Descripción | Requisitos |
|-------|-------------|------------|
| [token-reviewer](skills/token-reviewer/) | Tokens y coste estimado de tus sesiones de Claude Code, turno a turno. | Python 3.8+ |

### [token-reviewer](skills/token-reviewer/)

Te dice cuánto ha costado cada cosa que le pides a Claude Code. Lee los transcripts que Claude Code guarda en tu equipo y muestra, para cada prompt, las llamadas a la API que generó, los tokens (entrada, salida y caché) y su coste estimado en dólares. También suma proyectos enteros o periodos, como "esta semana".

- Desglose por turno, por modelo y por sesión, subagentes incluidos.
- Totales que coinciden con los que calcula el propio Claude Code.
- Se mantiene al día sola: si aparece un modelo nuevo, descarga los precios oficiales.
- Salida en español o inglés, en tabla o en JSON.

Pregúntale a Claude: *"¿cuánto me ha costado esta sesión?"*, *"¿qué prompts han sido los más caros?"* o *"¿cuánto he gastado esta semana en este proyecto?"*.

```
/plugin install token-reviewer@mario-skills
```

[Documentación completa](skills/token-reviewer/README.md)

## Instalación

Añade este repositorio como marketplace una sola vez, desde Claude Code:

```
/plugin marketplace add mariomatillabravo/mario-skills
```

Después instala las skills que quieras:

```
/plugin install <skill>@mario-skills
```

Desde la terminal, lo mismo con `claude plugin marketplace add mariomatillabravo/mario-skills` y `claude plugin install <skill>@mario-skills`. Para recibir versiones nuevas: `/plugin marketplace update mario-skills`.

**A mano:** copia la carpeta de la skill en `~/.claude/skills/` (todos tus proyectos) o en `.claude/skills/` dentro de un proyecto.

macOS / Linux:

```bash
git clone https://github.com/mariomatillabravo/mario-skills.git
cp -r mario-skills/skills/token-reviewer ~/.claude/skills/
```

Windows (PowerShell):

```powershell
git clone https://github.com/mariomatillabravo/mario-skills.git
Copy-Item -Recurse mario-skills\skills\token-reviewer "$HOME\.claude\skills\"
```

## Estructura

```
mario-skills/
├── .claude-plugin/
│   └── marketplace.json      # catálogo: una entrada por skill
├── README.md                 # este fichero
└── skills/
    └── <skill>/              # cada skill es un plugin independiente
        ├── SKILL.md          # instrucciones para Claude
        ├── README.md         # documentación para personas
        └── scripts/          # código que usa la skill (opcional)
```

## Añadir una skill

1. Crea `skills/<nombre>/` con su `SKILL.md` (con `name` y `description` en el frontmatter) y un `README.md`.
2. Añade una entrada en `.claude-plugin/marketplace.json` con `"name": "<nombre>"` y `"source": "./skills/<nombre>"`.
3. Añádela a la tabla y a la lista de este README.
4. Comprueba que todo es válido con `claude plugin validate .`

Al publicar cambios en una skill, sube su `version` en `marketplace.json`: así les llega la actualización a quienes la tienen instalada.

---

## English

A collection of skills for Claude Code. Each skill installs separately as a plugin.

| Skill | Description | Requires |
|-------|-------------|----------|
| [token-reviewer](skills/token-reviewer/) | Token usage and estimated cost of your Claude Code sessions, turn by turn, by model and by project. Keeps its prices up to date on its own. | Python 3.8+ |

Install from Claude Code:

```
/plugin marketplace add mariomatillabravo/mario-skills
/plugin install token-reviewer@mario-skills
```

Or copy a skill folder into `~/.claude/skills/`. Each skill's own README has the details.
