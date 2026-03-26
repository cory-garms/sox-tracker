"""
Chart export helpers — PNG and HTML.

Day 5 implementation target.
"""

from __future__ import annotations

from pathlib import Path


def save_html(fig, path: Path) -> Path:
    """Write a Plotly figure to a self-contained HTML file."""
    fig.write_html(str(path), include_plotlyjs="cdn", full_html=True)
    return path


def save_png(fig, path: Path, width: int = 1200, height: int = 600, scale: int = 2) -> Path:
    """
    Write a Plotly figure to a high-resolution PNG.
    Requires kaleido: pip install kaleido
    """
    fig.write_image(str(path), width=width, height=height, scale=scale)
    return path


def save_all(figures: dict[str, "go.Figure"], output_dir: Path, fmt: str = "html") -> list[Path]:
    """
    Save a dict of {name: figure} to output_dir.
    fmt: "html", "png", or "both"
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, fig in figures.items():
        if fmt in ("html", "both"):
            written.append(save_html(fig, output_dir / f"{name}.html"))
        if fmt in ("png", "both"):
            written.append(save_png(fig, output_dir / f"{name}.png"))
    return written
