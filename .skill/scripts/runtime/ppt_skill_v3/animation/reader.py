from __future__ import annotations

import hashlib
import posixpath
import re
import zipfile
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree as ET

from .plan import require

P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"p": P, "a": A, "r": R}


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def resolve_part(base, target):
    target = unquote(target.split("#", 1)[0])
    name = posixpath.normpath(target.lstrip("/") if target.startswith("/") else posixpath.join(posixpath.dirname(base), target))
    require(not name.startswith("../") and name != ".." and "\\" not in name, "Invalid package relationship path")
    return name


def read_package(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), "Duplicate ZIP entries")
        parts = {name: archive.read(name) for name in names}  # read verifies CRC
    require("[Content_Types].xml" in parts and "ppt/presentation.xml" in parts, "Not a supported PPTX package")
    for name, data in parts.items():
        if name.endswith((".xml", ".rels")):
            root = ET.fromstring(data)
            if name.endswith(".rels"):
                base = "" if name == "_rels/.rels" else posixpath.join(posixpath.dirname(posixpath.dirname(name)), posixpath.basename(name)[:-5])
                for rel in root:
                    if rel.get("TargetMode") != "External":
                        require(resolve_part(base, rel.get("Target", "")) in parts, f"Broken relationship: {name}")
    return parts


def inventory_from_parts(parts, source):
    presentation = ET.fromstring(parts["ppt/presentation.xml"])
    require(presentation.tag == f"{{{P}}}presentation", "Unsupported presentation namespace (requires transitional PPTX)")
    rels = ET.fromstring(parts["ppt/_rels/presentation.xml.rels"])
    mapping = {r.get("Id"): resolve_part("ppt/presentation.xml", r.get("Target", "")) for r in rels if r.get("TargetMode") != "External"}
    size = presentation.find("p:sldSz", NS)
    pages = []
    order = presentation.findall("p:sldIdLst/p:sldId", NS)
    require(bool(order), "Presentation has no supported slides")
    for index, entry in enumerate(order, 1):
        part = mapping.get(entry.get(f"{{{R}}}id"))
        require(part in parts, "Slide relationship missing")
        slide = ET.fromstring(parts[part])
        tree = slide.find("p:cSld/p:spTree", NS)
        require(tree is not None, f"Missing shape tree: {part}")
        objects = []
        all_ids = [int(n.get("id")) for n in tree.findall(".//p:cNvPr", NS)]
        for node in tree:
            kind = node.tag.rsplit("}", 1)[-1]
            if kind in {"nvGrpSpPr", "grpSpPr", "extLst"}:
                continue
            require(kind in {"sp", "pic", "grpSp", "graphicFrame", "cxnSp", "contentPart"}, f"Unsupported shape kind: {kind}")
            ids = node.findall(".//p:cNvPr", NS)
            require(bool(ids), f"Missing object ID: {part}")
            values = [int(n.get("id")) for n in ids]
            texts = [n.text or "" for n in node.findall(".//a:t", NS)]
            objects.append({"id": values[0], "name": ids[0].get("name", ""), "kind": kind,
                            "text": "\n".join(texts), "nested_ids": values[1:],
                            "geometry": [dict(n.attrib) for n in node.findall(".//a:xfrm/*", NS)]})
        require(len(all_ids) == len(set(all_ids)), f"Duplicate shape ID: {part}")
        transition = slide.find("p:transition", NS)
        pages.append({"slide_index": index, "part": part,
                      "title": next((o["text"].split("\n")[0][:100] for o in objects if o["text"]), "（无可提取文字）"),
                      "objects": objects, "has_timing": slide.find("p:timing", NS) is not None,
                      "auto_advance": transition is not None and transition.get("advTm") is not None,
                      "has_visual_content": any(o["kind"] in {"pic", "grpSp", "graphicFrame", "contentPart"} for o in objects)
                      or slide.find("p:cSld/p:bg//a:blip", NS) is not None})
    require(len({p["part"] for p in pages}) == len(pages), "Duplicate slide reference")
    return {"schema_version": "1.0", "source": source, "slide_size": dict(size.attrib) if size is not None else None, "pages": pages}


def inspect_source(path):
    source = Path(path).expanduser().resolve()
    require(source.suffix.lower() == ".pptx" and source.is_file(), "Only existing PPTX files are supported")
    before = source.read_bytes()
    # Load the exact hashed bytes, avoiding a mixed snapshot if another process saves.
    import io
    parts = read_package(io.BytesIO(before))
    return inventory_from_parts(parts, {"path": str(source), "sha256": digest(before)})


def compact_inventory(inventory):
    return {"source": inventory["source"], "slide_count": len(inventory["pages"]),
            "pages": [{k: p[k] for k in ("slide_index", "title", "has_timing", "auto_advance", "has_visual_content")}
                      | {"object_count": len(p["objects"])} for p in inventory["pages"]]}


def _candidate(path):
    return path.is_file() and path.suffix.lower() == ".pptx" and not (
        path.name.startswith(("~$", ".")) or re.search(r"(?:temp|tmp|backup|test|fixture|备份|试样|样本|对照)", path.stem, re.I))


def resolve_source(*, explicit=None, active=None, project=None, directories=()):
    """Use caller-provided conversational evidence before a bounded directory scan."""
    for label, value in (("explicit", explicit), ("conversation", active), ("project", project)):
        if value:
            path = Path(value).expanduser().resolve()
            if path.is_dir():
                candidates = sorted(p for p in path.iterdir() if _candidate(p))
                return _selection(candidates, label)
            if path.is_file() and path.suffix.lower() == ".pptx":
                return {"status": "resolved", "path": str(path), "basis": label}
            return {"status": "needs_source", "basis": label, "missing": str(path)}
    candidates = set()
    for directory in directories:
        root = Path(directory).expanduser().resolve()
        if root.is_dir():
            candidates.update(p.resolve() for p in root.iterdir() if _candidate(p))
    return _selection(sorted(candidates), "unique_related_directory")


def _selection(candidates, basis):
    if len(candidates) == 1:
        return {"status": "resolved", "path": str(candidates[0]), "basis": basis}
    return {"status": "needs_selection" if candidates else "needs_source", "basis": basis,
            "candidates": [str(p) for p in candidates]}
