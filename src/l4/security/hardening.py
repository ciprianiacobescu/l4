"""Parsers for files an agent's code can write (SPEC L4-SEC-006): XML without DTDs or entities, size-capped."""

import xml.etree.ElementTree as ET
from pathlib import Path
from xml.parsers import expat

from l4.fsutil import UnsafeFile, read_regular_file


class XmlRejected(ValueError):
    """The document is malformed, too large, or uses a DTD (and with it entities)."""


def _refuse_dtd(*_args: object) -> None:
    raise XmlRejected("the report declares a DTD or entity, which is not accepted")


def safe_parse_xml(path: Path, *, max_bytes: int) -> ET.Element:
    """Any DOCTYPE is refused through expat's own handler in a first pass, so the check does not depend on the
    document's encoding (a UTF-16 `<!DOCTYPE` would slip past a byte scan). Without a DTD there are no entities to
    expand, and only then is the tree built."""
    try:
        data = read_regular_file(path, limit=max_bytes)
    except UnsafeFile as exc:
        raise XmlRejected(str(exc)) from None
    except OSError as exc:
        raise XmlRejected(f"cannot read {path.name}: {type(exc).__name__}") from None
    guard = expat.ParserCreate()
    guard.StartDoctypeDeclHandler = _refuse_dtd
    guard.EntityDeclHandler = _refuse_dtd
    try:
        guard.Parse(data, True)
        return ET.fromstring(data)
    except (expat.ExpatError, ET.ParseError) as exc:
        raise XmlRejected(f"{path.name} is not well-formed XML: {exc}") from None
