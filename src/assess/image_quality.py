"""Check image sampling at its actual slide size, including cropping.

Large PNG dimensions alone do not establish readability. SVG text is checked before
rasterisation; exported media are checked independently from authoring previews.
"""

from __future__ import annotations

import argparse
import json
import math
import posixpath
import re
import struct
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

EMU_PER_INCH = 914400
MIN_IMAGE_PPI = 144
MIN_DIAGRAM_PPI = 288
MIN_DIAGRAM_TEXT_PX = 12
NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def raster_size(blob: bytes) -> tuple[int, int]:
    """Read PNG/JPEG dimensions without a raster library or DPI metadata."""
    width = height = 0
    if blob.startswith(b"\x89PNG\r\n\x1a\n") and len(blob) >= 24:
        width, height = struct.unpack(">II", blob[16:24])
    elif blob.startswith(b"\xff\xd8"):
        offset = 2
        while offset < len(blob):
            if blob[offset] != 0xFF:
                raise ValueError("Malformed JPEG marker")
            while offset < len(blob) and blob[offset] == 0xFF:
                offset += 1
            if offset >= len(blob):
                break
            marker = blob[offset]
            offset += 1
            if marker in {0xD8, 0x01} or 0xD0 <= marker <= 0xD7:
                continue
            if marker in {0xD9, 0xDA} or offset + 2 > len(blob):
                break
            length = int.from_bytes(blob[offset : offset + 2], "big")
            if length < 2 or offset + length > len(blob):
                raise ValueError("Truncated JPEG segment")
            if marker in {
                0xC0,
                0xC1,
                0xC2,
                0xC3,
                0xC5,
                0xC6,
                0xC7,
                0xC9,
                0xCA,
                0xCB,
                0xCD,
                0xCE,
                0xCF,
            }:
                height, width = struct.unpack(">HH", blob[offset + 3 : offset + 7])
                break
            offset += length
        else:
            raise ValueError("JPEG dimensions not found")
        if not width:
            raise ValueError("JPEG dimensions not found")
    else:
        raise ValueError("Unsupported raster format; use PNG or JPEG")
    if width <= 0 or height <= 0:
        raise ValueError("Invalid image dimensions")
    return width, height


def effective_ppi(size: tuple[int, int], extent: tuple[int, int], crop: dict) -> float:
    if min(extent) <= 0:
        raise ValueError("Image placement must have positive dimensions")
    fractions = {side: float(crop.get(side, 0)) / 100000 for side in ("l", "r", "t", "b")}
    if any(not math.isfinite(value) or value < 0 for value in fractions.values()):
        raise ValueError("Invalid image crop")
    visible = (1 - fractions["l"] - fractions["r"], 1 - fractions["t"] - fractions["b"])
    if min(visible) <= 0:
        raise ValueError("Image crop removes the entire image")
    return min(size[axis] * visible[axis] / (extent[axis] / EMU_PER_INCH) for axis in (0, 1))


def relationship_targets(archive: ZipFile, part: str) -> dict[str, str]:
    parent, name = posixpath.split(part)
    rel_file = posixpath.join(parent, "_rels", name + ".rels")
    if rel_file not in archive.namelist():
        return {}
    return {
        item.attrib["Id"]: posixpath.normpath(posixpath.join(parent, item.attrib["Target"]))
        if not item.attrib["Target"].startswith("/")
        else item.attrib["Target"].lstrip("/")
        for item in ET.fromstring(archive.read(rel_file))
        if item.get("TargetMode") != "External"
    }


def group_scale(picture: ET.Element, parents: dict) -> float:
    """Conservative sampling bound for nested, possibly rotated group scaling."""
    scale = 1.0
    parent = parents.get(picture)
    while parent is not None:
        if parent.tag == f"{{{NS['p']}}}grpSp":
            transform = parent.find("p:grpSpPr/a:xfrm", NS)
            if transform is not None:
                ext, child = transform.find("a:ext", NS), transform.find("a:chExt", NS)
                if ext is None or child is None:
                    raise ValueError("Grouped image scaling dimensions are missing")
                dimensions = [
                    float(node.attrib[key]) for node in (ext, child) for key in ("cx", "cy")
                ]
                if any(not math.isfinite(value) or value <= 0 for value in dimensions):
                    raise ValueError("Invalid grouped image scaling")
                scale *= max(dimensions[0] / dimensions[2], dimensions[1] / dimensions[3])
        parent = parents.get(parent)
    return scale


def inspect_pptx_images(pptx: Path, diagram_slides: set[int] | None = None) -> dict:
    """Audit embedded pixels against picture extents in presentation order."""
    records, errors = [], []
    with ZipFile(pptx) as archive:
        presentation = ET.fromstring(archive.read("ppt/presentation.xml"))
        targets = relationship_targets(archive, "ppt/presentation.xml")
        for number, item in enumerate(presentation.findall("p:sldIdLst/p:sldId", NS), 1):
            part = targets[item.attrib[f"{{{NS['r']}}}id"]]
            rels = relationship_targets(archive, part)
            document = ET.fromstring(archive.read(part))
            parents = {child: parent for parent in document.iter() for child in parent}
            for picture in document.findall(".//p:pic", NS):
                label = picture.find("p:nvPicPr/p:cNvPr", NS)
                name = (label.get("name") or "picture") if label is not None else "picture"
                record = {"slide": number, "name": name}
                try:
                    blip = picture.find("p:blipFill/a:blip", NS)
                    if blip is None or f"{{{NS['r']}}}embed" not in blip.attrib:
                        raise ValueError("Linked image cannot be verified as an embedded asset")
                    media = rels[blip.attrib[f"{{{NS['r']}}}embed"]]
                    record["media"] = media
                    blob = archive.read(media)
                    if media.lower().endswith(".svg"):
                        svg = ET.fromstring(blob)
                        if any(node.tag.rsplit("}", 1)[-1] == "image" for node in svg.iter()):
                            raise ValueError(
                                "SVG with raster content requires a separate pixel audit"
                            )
                        records.append({**record, "kind": "vector", "passed": True})
                        continue
                    size = raster_size(blob)
                    ext = picture.find("p:spPr/a:xfrm/a:ext", NS)
                    if ext is None:
                        raise ValueError("Image placement dimensions are missing")
                    extent = (int(ext.attrib["cx"]), int(ext.attrib["cy"]))
                    crop = picture.find("p:blipFill/a:srcRect", NS)
                    crop = dict(crop.attrib) if crop is not None else {}
                    scale = group_scale(picture, parents)
                    ppi = effective_ppi(size, extent, crop) / scale
                    minimum = (
                        MIN_DIAGRAM_PPI if number in (diagram_slides or set()) else MIN_IMAGE_PPI
                    )
                    record.update(
                        kind="raster",
                        pixels=list(size),
                        crop=crop,
                        group_scale_bound=scale,
                        effective_ppi=round(ppi, 2),
                        minimum_ppi=minimum,
                        passed=ppi + 0.01 >= minimum,
                    )
                    if not record["passed"]:
                        errors.append(f"slide {number}: {name}: {ppi:.0f} ppi < {minimum} ppi")
                except (ValueError, KeyError, ET.ParseError, struct.error) as exc:
                    record.update(passed=False, error=str(exc))
                    errors.append(f"slide {number}: {name}: {exc}")
                records.append(record)
    return {
        "passed": not errors,
        "minimum_ppi": MIN_IMAGE_PPI,
        "diagram_minimum_ppi": MIN_DIAGRAM_PPI,
        "images": records,
        "errors": errors,
        "scope": "embedded PNG/JPEG and pure SVG; pixel sampling is not a sharpness/OCR check",
    }


def validate_svg_text(path: Path, frame: tuple[float, float]) -> None:
    """Check text sizes in supported static SVG before fitting into its frame.

    Unresolved CSS/transforms require adaptation rather than an unjustified pass.
    """
    svg = ET.fromstring(path.read_bytes())
    view = [float(value) for value in re.split(r"[\s,]+", svg.attrib.get("viewBox", ""))]
    if len(view) != 4 or not all(math.isfinite(value) for value in view) or min(view[2:]) <= 0:
        raise ValueError("SVG requires a positive viewBox for placement checks")
    scale = min(frame[0] / view[2], frame[1] / view[3])
    for node in svg.iter():
        kind = node.tag.rsplit("}", 1)[-1]
        if (
            kind in {"image", "foreignObject", "style"}
            or node.get("transform")
            or node.get("style")
        ):
            raise ValueError("Adapt SVG with embedded rasters, CSS or transforms to native objects")
        if (
            kind in {"text", "tspan"}
            and "".join(node.itertext()).strip()
            and (kind == "text" or node.get("font-size") is not None)
        ):
            font = node.get("font-size", "")
            if not re.fullmatch(r"\d+(?:\.\d+)?(?:px)?", font):
                raise ValueError("SVG text needs an explicit font-size in px")
            placed = float(font.removesuffix("px")) * scale
            if placed < MIN_DIAGRAM_TEXT_PX:
                raise ValueError(
                    f"SVG text becomes {placed:.1f}px < {MIN_DIAGRAM_TEXT_PX}px on the slide; "
                    "adapt to native objects or split the diagram; raster upscaling does not help"
                )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pptx", type=Path)
    parser.add_argument("--diagram-slide", type=int, action="append", default=[])
    args = parser.parse_args(argv)
    if any(number < 1 for number in args.diagram_slide):
        parser.error("diagram slide numbers must be positive")
    report = inspect_pptx_images(args.pptx, set(args.diagram_slide))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
