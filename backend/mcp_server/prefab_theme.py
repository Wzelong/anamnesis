"""Anamnesis Prefab theme — our exact web-app OKLCH tokens + component polish.

The Prefab renderer uses the same token vocabulary as our frontend
(--background, --card, --primary, --border, --muted-foreground, --accent,
--border-radius), so dropping our values in matches the web workspace 1:1.
`css` overrides .pf-* component classes for the denser, designed look.
"""
from prefab_ui.themes.base import Theme

_LIGHT = """
--background: oklch(1 0 0);
--foreground: oklch(0.141 0.005 285.823);
--card: oklch(1 0 0);
--card-foreground: oklch(0.141 0.005 285.823);
--popover: oklch(1 0 0);
--popover-foreground: oklch(0.141 0.005 285.823);
--primary: oklch(0.21 0.006 285.885);
--primary-foreground: oklch(0.985 0 0);
--secondary: oklch(0.967 0.001 286.375);
--secondary-foreground: oklch(0.21 0.006 285.885);
--muted: oklch(0.967 0.001 286.375);
--muted-foreground: oklch(0.552 0.016 285.938);
--accent: oklch(0.967 0.001 286.375);
--accent-foreground: oklch(0.21 0.006 285.885);
--destructive: oklch(0.55 0.14 25);
--border: oklch(0.92 0.004 286.32);
--input: oklch(0.92 0.004 286.32);
--ring: oklch(0.705 0.015 286.067);
--border-radius: 0.625rem;
""".strip()

_DARK = """
--background: oklch(0.21 0.01 286);
--foreground: oklch(0.985 0 0);
--card: oklch(0.21 0.006 285.885);
--card-foreground: oklch(0.985 0 0);
--popover: oklch(0.21 0.006 285.885);
--popover-foreground: oklch(0.985 0 0);
--primary: oklch(0.92 0.004 286.32);
--primary-foreground: oklch(0.21 0.006 285.885);
--secondary: oklch(0.274 0.006 286.033);
--secondary-foreground: oklch(0.985 0 0);
--muted: oklch(0.274 0.006 286.033);
--muted-foreground: oklch(0.705 0.015 286.067);
--accent: oklch(0.274 0.006 286.033);
--accent-foreground: oklch(0.985 0 0);
--destructive: oklch(0.65 0.12 25);
--border: oklch(1 0 0 / 10%);
--input: oklch(1 0 0 / 15%);
--ring: oklch(0.552 0.016 285.938);
""".strip()

# Component polish: tighter density, brand green accents, refined cards/badges,
# a subtle header gradient, and the amber citation highlight.
_CSS = """
.pf-app-root { padding: 0; font-family: var(--font-sans, ui-sans-serif, system-ui, sans-serif); }
.pf-card { border-radius: var(--border-radius); border: 1px solid var(--border); box-shadow: 0 1px 2px rgb(0 0 0 / 0.04); }
.pf-badge { font-size: 11px; font-weight: 600; letter-spacing: 0.01em; }
.pf-badge-variant-success { background: oklch(0.96 0.02 145); color: oklch(0.50 0.10 145); border-color: oklch(0.86 0.03 145); }
.pf-badge-variant-warning { background: oklch(0.97 0.03 85); color: oklch(0.55 0.12 85); border-color: oklch(0.88 0.04 85); }
.pf-badge-variant-destructive { background: oklch(0.97 0.03 25); color: oklch(0.53 0.14 25); border-color: oklch(0.88 0.04 25); }
.pf-button { border-radius: calc(var(--border-radius) - 2px); font-weight: 500; }
.pf-alert-variant-warning { background: oklch(0.97 0.03 85); border-color: oklch(0.88 0.04 85); }
.anamnesis-hl { background: oklch(0.90 0.09 85); border-radius: 3px; padding: 0 2px; }
.anamnesis-queue-item { border-left: 3px solid transparent; transition: background 0.12s, border-color 0.12s; }
.anamnesis-queue-item:hover { background: var(--accent); }
.anamnesis-header { background: linear-gradient(180deg, color-mix(in oklch, var(--primary) 4%, var(--background)), var(--background)); }
""".strip()


def anamnesis_theme() -> Theme:
    return Theme(
        light_css=_LIGHT,
        dark_css=_DARK,
        css=_CSS,
        accent="oklch(0.45 0.04 145)",  # brand green
        font="Geist, ui-sans-serif, system-ui, sans-serif",
        gradient=False,
    )
