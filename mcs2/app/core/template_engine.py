import os
from pathlib import Path

from jinja2 import (
    Environment,
    FileSystemLoader,
    BaseLoader,
    select_autoescape
)


def _make_env():
    """Create env pointing at the templates/ folder (created at runtime)."""
    template_dir = Path(__file__).resolve().parents[2] / "templates"
    template_dir.mkdir(parents=True, exist_ok=True)
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"])
    )


def render_template(
    template_name,
    context
):
    env = _make_env()
    template = env.get_template(template_name)
    return template.render(**context)


def render_string_template(
    html_string,
    context
):
    """Render an HTML string directly (used for preview)."""
    env = Environment(
        loader=BaseLoader(),
        autoescape=select_autoescape(["html"])
    )
    template = env.from_string(html_string)
    return template.render(**context)
