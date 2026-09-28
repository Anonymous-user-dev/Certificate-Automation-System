"""Regenerate the small, deterministic PDF geometry fixtures in this folder."""

from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject, RectangleObject


ROOT = Path(__file__).parent
FIXTURES = {
    "portrait.pdf": ((200, 300, (0, 0, 200, 300), 0),),
    "landscape.pdf": ((300, 200, (0, 0, 300, 200), 0),),
    "cropped-rotated.pdf": ((200, 300, (10, 20, 190, 270), 90),),
    "multi-page.pdf": (
        (200, 300, (0, 0, 200, 300), 0),
        (300, 200, (10, 10, 290, 190), 0),
    ),
}

for filename, definitions in FIXTURES.items():
    writer = PdfWriter()
    for width, height, crop, rotation in definitions:
        page = writer.add_blank_page(width=width, height=height)
        page.cropbox = RectangleObject(crop)
        if rotation:
            page.rotate(rotation)
        # A thin blue border makes preservation of existing page artwork observable.
        artwork = DecodedStreamObject()
        artwork.set_data(f"q 0 0 1 RG 1 w 12 22 {width - 24} {height - 44} re S Q".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(artwork)
    with (ROOT / filename).open("wb") as output:
        writer.write(output)
