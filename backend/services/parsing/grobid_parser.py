"""GROBID API integration for reference extraction."""
import io
import xml.etree.ElementTree as ET
import httpx
from common.config import settings
from common.logging import logger

GROBID_TIMEOUT = 120
GROBID_URL = f"{settings.GROBID_BASE_URL}/api/processFulltextDocument"

NS = {"tei": "http://www.tei-c.org/ns/1.0"}


async def parse_references_with_grobid(pdf_bytes: bytes) -> list[dict]:
    """POST PDF to GROBID, parse TEI XML, return structured reference list.

    Each reference dict: {title, authors, year, doi, raw_ref}.
    """
    logger.info(f"Sending PDF to GROBID ({len(pdf_bytes)} bytes)...")

    try:
        async with httpx.AsyncClient(timeout=GROBID_TIMEOUT) as client:
            resp = await client.post(
                GROBID_URL,
                files={"input": ("paper.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
                data={
                    "consolidateCitations": "1",
                    "includeRawCitations": "1",
                },
            )
            resp.raise_for_status()
            xml_text = resp.text
    except httpx.HTTPError as e:
        logger.warning(f"GROBID request failed: {e}; returning empty refs")
        return []
    except Exception as e:
        logger.error(f"GROBID unexpected error: {e}")
        return []

    return _parse_tei_references(xml_text)


def _parse_tei_references(xml_text: str) -> list[dict]:
    """Extract references from GROBID TEI XML."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.warning(f"Failed to parse GROBID XML: {e}")
        return []

    refs = []
    for bibl in root.findall(".//tei:biblStruct", NS):
        title_el = bibl.find(".//tei:title[@type='main']", NS)
        title = title_el.text.strip() if title_el is not None and title_el.text else ""

        authors = []
        for author in bibl.findall(".//tei:author", NS):
            forename = author.find("tei:persName/tei:forename", NS)
            surname = author.find("tei:persName/tei:surname", NS)
            parts = []
            if forename is not None and forename.text:
                parts.append(forename.text)
            if surname is not None and surname.text:
                parts.append(surname.text)
            if parts:
                authors.append(" ".join(parts))

        year = ""
        date_el = bibl.find(".//tei:date", NS)
        if date_el is not None and date_el.text:
            import re
            match = re.search(r"\d{4}", date_el.text)
            year = match.group() if match else ""

        doi = ""
        for idno in bibl.findall(".//tei:idno[@type='DOI']", NS):
            doi = idno.text or ""

        raw_ref = ET.tostring(bibl, encoding="unicode") if title else ""

        refs.append({
            "title": title,
            "authors": authors,
            "year": year,
            "doi": doi,
            "raw_ref": raw_ref,
        })

    logger.info(f"GROBID extracted {len(refs)} references")
    return refs
