"""Fast PDF parser using PyMuPDF (fitz) for simple, native-text PDFs.

Provides:
- classify_pdf(): triage PDFs as "simple" or "complex"
- extract_pages_and_sentences_fitz(): sentence-level extraction with bboxes
- validate_fast_parse(): quality check on extraction results
"""

import re
import logging

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# Sentence boundary regex — matches the one in ml_worker.py:188
_SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+')

# Font name substrings that indicate math/symbol content
_MATH_FONT_MARKERS = (
    "math", "symbol", "cmsy", "cmmi", "cmex", "stix",
    "cambria math", "asana", "xits",
)

# Minimum chars of extractable text for a page to count as "has text"
_MIN_TEXT_CHARS = 50

# Maximum image-area-to-page-area ratio before flagging as image-heavy
_MAX_IMAGE_RATIO = 0.4

# Minimum gap between column x-positions as fraction of page width
_COLUMN_GAP_FRACTION = 0.20

# Minimum text blocks per cluster to count as a real column
_MIN_BLOCKS_PER_COLUMN = 3


def _pick_sample_pages(total_pages, max_samples=5):
    """Pick evenly-spaced page indices to sample for triage."""
    if total_pages <= max_samples:
        return list(range(total_pages))
    # Always include first and last; fill middle evenly
    indices = {0, total_pages - 1}
    remaining = max_samples - 2
    for i in range(remaining):
        idx = int((i + 1) * (total_pages - 1) / (remaining + 1))
        indices.add(idx)
    return sorted(indices)


def _is_multi_column(text_blocks, page_width):
    """Detect multi-column layout by clustering text block x-positions."""
    if len(text_blocks) < _MIN_BLOCKS_PER_COLUMN * 2:
        return False

    # Collect x0 (left edge) of each text block
    x_positions = [b["bbox"][0] for b in text_blocks]
    x_positions.sort()

    # Find gaps larger than threshold
    gap_threshold = page_width * _COLUMN_GAP_FRACTION
    clusters = []
    current_cluster = [x_positions[0]]

    for i in range(1, len(x_positions)):
        if x_positions[i] - x_positions[i - 1] > gap_threshold:
            clusters.append(current_cluster)
            current_cluster = [x_positions[i]]
        else:
            current_cluster.append(x_positions[i])
    clusters.append(current_cluster)

    # Need at least 2 clusters with meaningful content
    significant_clusters = [c for c in clusters if len(c) >= _MIN_BLOCKS_PER_COLUMN]
    return len(significant_clusters) >= 2


def _has_math_fonts(text_blocks):
    """Check if any text block uses math/symbol fonts."""
    for block in text_blocks:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                font_lower = span.get("font", "").lower()
                if any(marker in font_lower for marker in _MATH_FONT_MARKERS):
                    return True
    return False


def _estimate_image_area(page):
    """Sum the area of all images on a page."""
    total_area = 0
    for img in page.get_images(full=True):
        xref = img[0]
        try:
            rects = page.get_image_rects(xref)
            for rect in rects:
                total_area += rect.width * rect.height
        except Exception:
            pass
    return total_area


def classify_pdf(pdf_path):
    """Classify a PDF as 'simple' or 'complex' by sampling pages.

    Simple PDFs have native text, single-column layouts, no math fonts,
    and are not image-heavy. Returns 'complex' if any sampled page fails
    any check, or on any error.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        'simple' or 'complex'
    """
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        logger.warning(f"Could not open PDF for triage: {e}")
        return "complex"

    try:
        sample_indices = _pick_sample_pages(len(doc))

        for page_idx in sample_indices:
            page = doc[page_idx]
            page_width = page.rect.width
            page_area = page.rect.width * page.rect.height

            # Check 1: Text extractability (scanned PDF detection)
            text = page.get_text("text")
            images = page.get_images(full=True)
            if len(text.strip()) < _MIN_TEXT_CHARS and len(images) > 0:
                logger.info(f"Triage: page {page_idx} looks scanned (text={len(text.strip())} chars, images={len(images)})")
                return "complex"

            # Get structured block data for remaining checks
            page_dict = page.get_text("dict")
            text_blocks = [b for b in page_dict["blocks"] if b["type"] == 0]

            # Check 2: Multi-column layout
            if _is_multi_column(text_blocks, page_width):
                logger.info(f"Triage: page {page_idx} has multi-column layout")
                return "complex"

            # Check 3: Math/symbol fonts
            if _has_math_fonts(text_blocks):
                logger.info(f"Triage: page {page_idx} has math fonts")
                return "complex"

            # Check 4: Image-heavy page
            if page_area > 0:
                image_area = _estimate_image_area(page)
                if image_area / page_area > _MAX_IMAGE_RATIO:
                    logger.info(f"Triage: page {page_idx} is image-heavy ({image_area/page_area:.0%})")
                    return "complex"

        return "simple"
    except Exception as e:
        logger.warning(f"Triage error, defaulting to complex: {e}")
        return "complex"
    finally:
        doc.close()


def _fitz_bbox_to_polygon(x0, y0, x1, y1):
    """Convert PyMuPDF rect coords to 4-corner polygon matching marker format.

    Returns [[x0,y0],[x1,y0],[x1,y1],[x0,y1]] (TL, TR, BR, BL).
    """
    return [
        [round(x0, 2), round(y0, 2)],
        [round(x1, 2), round(y0, 2)],
        [round(x1, 2), round(y1, 2)],
        [round(x0, 2), round(y1, 2)],
    ]


def extract_pages_and_sentences_fitz(pdf_path):
    """Extract page dimensions and sentences with bounding boxes using PyMuPDF.

    Replicates the output format of extract_pages_and_sentences() in ml_worker.py.

    Returns:
        list of dicts, one per page:
        {
            "page_number": int (0-indexed),
            "width": float,
            "height": float,
            "sentences": [
                {"text": str, "bbox": [[[x1,y1],[x2,y2],[x3,y3],[x4,y4]], ...]},
                ...
            ]
        }
    """
    doc = fitz.open(pdf_path)
    pages_data = []

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        page_info = {
            "page_number": page_idx,
            "width": page.rect.width,
            "height": page.rect.height,
            "sentences": [],
        }

        page_dict = page.get_text("dict")
        text_blocks = [b for b in page_dict["blocks"] if b["type"] == 0]

        for block in text_blocks:
            lines = block.get("lines", [])
            if not lines:
                continue

            # Collect each line's text and bbox
            line_texts = []
            line_polygons = []
            for line in lines:
                # Concatenate spans within the line
                line_text = "".join(span["text"] for span in line.get("spans", []))
                line_text = line_text.rstrip("\n")
                line_texts.append(line_text)

                bbox = line["bbox"]  # (x0, y0, x1, y1)
                line_polygons.append(_fitz_bbox_to_polygon(*bbox))

            # Build concatenated block text with spaces between lines,
            # tracking which character index maps to which line
            # (mirrors ml_worker.py:219-227)
            block_text = ""
            char_to_line = []
            for i, lt in enumerate(line_texts):
                if i > 0:
                    block_text += " "
                    char_to_line.append(i)  # space belongs to next line
                for _ in lt:
                    char_to_line.append(i)
                block_text += lt

            if not block_text.strip():
                continue

            # Split block text into sentences (mirrors ml_worker.py:233-239)
            sentence_spans = []
            last_end = 0
            for match in _SENTENCE_SPLIT.finditer(block_text):
                sentence_spans.append((last_end, match.start()))
                last_end = match.end()
            if last_end < len(block_text):
                sentence_spans.append((last_end, len(block_text)))

            for start, end in sentence_spans:
                sentence_text = block_text[start:end].strip()
                if not sentence_text:
                    continue

                # Determine which lines this sentence spans
                spanned_line_indices = set()
                for char_idx in range(start, min(end, len(char_to_line))):
                    spanned_line_indices.add(char_to_line[char_idx])

                # Collect polygons, deduplicating identical ones
                # (mirrors ml_worker.py:253-258)
                seen = []
                for li in sorted(spanned_line_indices):
                    poly = line_polygons[li]
                    if poly not in seen:
                        seen.append(poly)

                page_info["sentences"].append({
                    "text": sentence_text,
                    "bbox": seen,
                })

        # Merge short sentences (<150 chars) with the next one
        # (mirrors ml_worker.py:266-278)
        merged = []
        for sent in page_info["sentences"]:
            if merged and len(merged[-1]["text"]) < 150:
                merged[-1]["text"] += " " + sent["text"]
                merged[-1]["bbox"].extend(sent["bbox"])
            else:
                merged.append({"text": sent["text"], "bbox": list(sent["bbox"])})

        # If the last entry is still short, fold it into the previous one
        if len(merged) >= 2 and len(merged[-1]["text"]) < 150:
            merged[-2]["text"] += " " + merged[-1]["text"]
            merged[-2]["bbox"].extend(merged[-1]["bbox"])
            merged.pop()

        page_info["sentences"] = merged
        pages_data.append(page_info)

    doc.close()
    return pages_data


def generate_markdown_fitz(pdf_path):
    """Generate markdown text from a PDF using PyMuPDF.

    Detects headers by relative font size and produces simple markdown.

    Returns:
        list of str, one markdown string per page
    """
    doc = fitz.open(pdf_path)
    page_markdowns = []

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        page_dict = page.get_text("dict")
        text_blocks = [b for b in page_dict["blocks"] if b["type"] == 0]

        # Find the most common font size (body text size)
        font_sizes = []
        for block in text_blocks:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if span["text"].strip():
                        font_sizes.append(round(span["size"], 1))

        body_size = max(set(font_sizes), key=font_sizes.count) if font_sizes else 12

        lines_out = []
        for block in text_blocks:
            block_lines = block.get("lines", [])
            for line in block_lines:
                spans = line.get("spans", [])
                if not spans:
                    continue
                line_text = "".join(s["text"] for s in spans).strip()
                if not line_text:
                    continue

                # Detect headers by font size
                avg_size = sum(s["size"] for s in spans) / len(spans)
                if avg_size > body_size * 1.3:
                    line_text = f"## {line_text}"
                elif avg_size > body_size * 1.15:
                    line_text = f"### {line_text}"

                lines_out.append(line_text)
            lines_out.append("")  # blank line between blocks

        page_markdowns.append("\n".join(lines_out).strip())

    doc.close()
    return page_markdowns


def validate_fast_parse(pages_data, total_pages):
    """Check whether fast parse produced reasonable results.

    Returns True if results look valid, False if GPU fallback is needed.
    """
    if not pages_data:
        return False

    # Check that we got text from at least 70% of pages
    pages_with_text = sum(1 for p in pages_data if p["sentences"])
    if pages_with_text < total_pages * 0.7:
        logger.warning(f"Fast parse validation: only {pages_with_text}/{total_pages} pages have text")
        return False

    # Check average sentence count is reasonable
    total_sentences = sum(len(p["sentences"]) for p in pages_data)
    if total_sentences < total_pages * 0.5:
        logger.warning(f"Fast parse validation: only {total_sentences} sentences for {total_pages} pages")
        return False

    # Check extracted text is mostly printable (not garbled)
    all_text = " ".join(s["text"] for p in pages_data for s in p["sentences"])
    if all_text:
        printable_count = sum(1 for c in all_text if c.isprintable() or c.isspace())
        ratio = printable_count / len(all_text)
        if ratio < 0.85:
            logger.warning(f"Fast parse validation: text is {ratio:.0%} printable (threshold 85%)")
            return False

    return True
