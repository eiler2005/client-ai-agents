"""Actual placement and crop must expose undersampled images and tiny SVG labels."""

import struct
from zipfile import ZipFile

import pytest

from assess.image_quality import (
    NS,
    effective_ppi,
    inspect_pptx_images,
    main,
    raster_size,
    validate_svg_text,
)


def picture_deck(path, width, height, crop="", name="Picture", group=False):
    """Synthetic OOXML and IHDR dimensions; no real client material."""
    p, a, r = NS["p"], NS["a"], NS["r"]
    rel = "http://schemas.openxmlformats.org/package/2006/relationships"
    group_open = (
        '<p:grpSp><p:grpSpPr><a:xfrm><a:ext cx="18288000" cy="9144000"/>'
        '<a:chExt cx="9144000" cy="4572000"/></a:xfrm></p:grpSpPr>'
        if group
        else ""
    )
    group_close = "</p:grpSp>" if group else ""
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "ppt/presentation.xml",
            f'<p:presentation xmlns:p="{p}" xmlns:r="{r}"><p:sldIdLst>'
            '<p:sldId r:id="one"/></p:sldIdLst></p:presentation>',
        )
        archive.writestr(
            "ppt/_rels/presentation.xml.rels",
            f'<Relationships xmlns="{rel}"><Relationship Id="one" '
            f'Type="{r}/slide" Target="slides/slide7.xml"/></Relationships>',
        )
        archive.writestr(
            "ppt/slides/slide7.xml",
            f'<p:sld xmlns:p="{p}" xmlns:a="{a}" xmlns:r="{r}">{group_open}<p:pic>'
            f'<p:nvPicPr><p:cNvPr name="{name}"/></p:nvPicPr><p:blipFill>'
            f'<a:blip r:embed="asset"/>{crop}</p:blipFill><p:spPr><a:xfrm>'
            f'<a:ext cx="9144000" cy="4572000"/></a:xfrm></p:spPr></p:pic>{group_close}</p:sld>',
        )
        archive.writestr(
            "ppt/slides/_rels/slide7.xml.rels",
            f'<Relationships xmlns="{rel}"><Relationship Id="asset" '
            f'Type="{r}/image" Target="../media/image.png"/></Relationships>',
        )
        archive.writestr(
            "ppt/media/image.png",
            b"\x89PNG\r\n\x1a\n"
            + struct.pack(">I", 13)
            + b"IHDR"
            + struct.pack(">II", width, height),
        )


def test_exported_resolution_is_checked_at_actual_placement(tmp_path):
    path = tmp_path / "invented.pptx"
    picture_deck(path, 960, 480)
    low = inspect_pptx_images(path)
    assert not low["passed"]
    assert low["images"][0]["effective_ppi"] == 96
    assert "slide 1" in low["errors"][0]  # presentation order, not the part filename
    picture_deck(path, 1920, 960)
    assert inspect_pptx_images(path)["passed"]
    assert not inspect_pptx_images(path, diagram_slides={1})["passed"]


def test_crop_can_make_a_large_bitmap_insufficient(tmp_path):
    path = tmp_path / "invented.pptx"
    picture_deck(path, 2400, 1200, '<a:srcRect l="30000" r="30000"/>')
    assert not inspect_pptx_images(path)["passed"]
    assert inspect_pptx_images(path)["images"][0]["effective_ppi"] == 96


def test_corrupt_raster_is_not_silently_approved(tmp_path):
    path = tmp_path / "invented.pptx"
    picture_deck(path, 0, 0)
    assert not inspect_pptx_images(path)["passed"]
    with pytest.raises(ValueError, match="entire image"):
        effective_ppi((2400, 1200), (9144000, 4572000), {"l": 100000})


def test_large_svg_render_does_not_rescue_tiny_placed_text(tmp_path):
    path = tmp_path / "invented.svg"
    path.write_text('<svg viewBox="0 0 1000 600"><text font-size="9">Label</text></svg>')
    with pytest.raises(ValueError, match="raster upscaling does not help"):
        validate_svg_text(path, (1000, 430))
    path.write_text('<svg viewBox="0 0 1000 600"><text font-size="20">Label</text></svg>')
    validate_svg_text(path, (1000, 430))


def test_svg_wrapper_does_not_disguise_a_bitmap_as_vector(tmp_path):
    path = tmp_path / "invented.svg"
    path.write_text('<svg viewBox="0 0 1000 600"><image href="tiny.png"/></svg>')
    with pytest.raises(ValueError, match="embedded rasters"):
        validate_svg_text(path, (1000, 430))


def test_jpeg_progressive_frame_and_truncation():
    # SOI + progressive SOF; precision, height, width and component count.
    frame = b"\xff\xd8\xff\xc2" + struct.pack(">HBHHB", 8, 8, 960, 1920, 0)
    assert raster_size(frame) == (1920, 960)
    with pytest.raises(ValueError, match="Truncated"):
        raster_size(frame[:-2])


def test_cli_returns_failure_for_insufficient_pixels(tmp_path, capsys):
    path = tmp_path / "invented.pptx"
    picture_deck(path, 960, 480)
    assert main([str(path)]) == 1
    assert '"passed": false' in capsys.readouterr().out
    picture_deck(path, 1920, 960)
    assert main([str(path)]) == 0


def test_enlarging_a_group_reduces_actual_image_sampling(tmp_path):
    path = tmp_path / "invented.pptx"
    picture_deck(path, 1920, 960, group=True)
    report = inspect_pptx_images(path)
    assert not report["passed"]
    assert report["images"][0]["effective_ppi"] == 96
    assert report["images"][0]["group_scale_bound"] == 2


@pytest.mark.parametrize(
    "label",
    [
        '<text font-size="20"><tspan font-size="6">Small label</tspan></text>',
        '<text font-size="20" style="font-size:6px">Small label</text>',
    ],
)
def test_svg_font_override_cannot_hide_small_text(tmp_path, label):
    path = tmp_path / "invented.svg"
    path.write_text(f'<svg viewBox="0 0 1000 600">{label}</svg>')
    with pytest.raises(ValueError):
        validate_svg_text(path, (1000, 600))
