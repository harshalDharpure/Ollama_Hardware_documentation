"""Figure and table extraction utilities."""

from __future__ import annotations

from pathlib import Path

from src.models import ExtractedFigure


def save_figure_image(
    image_bytes: bytes,
    output_dir: Path,
    page: int,
    index: int,
    caption: str = "",
    section_ref: str = "",
) -> ExtractedFigure:
    output_dir.mkdir(parents=True, exist_ok=True)
    fig_id = f"fig_{page}_{index}"
    path = output_dir / f"{fig_id}.png"
    path.write_bytes(image_bytes)

    from PIL import Image
    import io

    img = Image.open(io.BytesIO(image_bytes))
    w, h = img.size

    return ExtractedFigure(
        id=fig_id,
        path=str(path),
        page=page,
        caption=caption,
        section_ref=section_ref,
        width=w,
        height=h,
    )
