import os

from jinja2 import (
    Environment,
    FileSystemLoader,
    BaseLoader,
    select_autoescape
)


def _make_env():
    """Create env pointing at the templates/ folder (created at runtime)."""
    os.makedirs("templates", exist_ok=True)
    return Environment(
        loader=FileSystemLoader("templates"),
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
