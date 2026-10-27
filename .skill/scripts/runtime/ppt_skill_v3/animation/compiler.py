from __future__ import annotations

import io
import os
import tempfile
import zipfile
from pathlib import Path
from xml.dom import minidom

from .plan import require, steps, validate_plan
from .reader import P, digest, inventory_from_parts, read_package
from .verify import content_snapshot, verify_file


def compile_slide(data, page):
    doc = minidom.parseString(data)
    root = doc.documentElement
    removed = False
    for node in list(root.childNodes):
        if node.namespaceURI == P and node.localName == "timing":
            root.removeChild(node)
            removed = True
    click_steps = steps(page)
    if not click_steps:
        return doc.toxml(encoding="UTF-8") if removed else data
    # Reuse a declared presentation prefix (including a default namespace).
    prefix = root.prefix
    def add(parent, tag, **attrs):
        node = doc.createElementNS(P, f"{prefix}:{tag}" if prefix else tag)
        for key, value in attrs.items():
            node.setAttribute(key, str(value))
        parent.appendChild(node)
        return node
    next_id = 0
    def clock(parent, **attrs):
        nonlocal next_id
        next_id += 1
        return add(parent, "cTn", id=next_id, **attrs)
    def start(parent, delay):
        add(add(parent, "stCondLst"), "cond", delay=delay)
    def target(parent, sid):
        add(add(parent, "tgtEl"), "spTgt", spid=sid)
    timing = doc.createElementNS(P, f"{prefix}:timing" if prefix else "timing")
    tm = clock(add(add(timing, "tnLst"), "par"), dur="indefinite", restart="never", nodeType="tmRoot")
    seq = add(add(tm, "childTnLst"), "seq", concurrent=1, nextAc="seek")
    main = clock(seq, dur="indefinite", nodeType="mainSeq")
    main_children = add(main, "childTnLst")
    for sids in click_steps:
        outer = clock(add(main_children, "par"), fill="hold")
        start(outer, "indefinite")
        # B compatibility: an additional zero-delay container inside the click wrapper.
        inner = clock(add(add(outer, "childTnLst"), "par"), fill="hold")
        start(inner, 0)
        inner_children = add(inner, "childTnLst")
        for index, sid in enumerate(sids):
            effect = clock(add(inner_children, "par"), presetID=10, presetClass="entr", presetSubtype=0,
                           fill="hold", nodeType="clickEffect" if index == 0 else "withEffect")
            start(effect, 0)
            children = add(effect, "childTnLst")
            visible = add(children, "set")
            behavior = add(visible, "cBhvr")
            clock(behavior, dur=1, fill="hold")
            target(behavior, sid)
            name = add(add(behavior, "attrNameLst"), "attrName")
            name.appendChild(doc.createTextNode("style.visibility"))
            add(add(visible, "to"), "strVal", val="visible")
            fade = add(children, "animEffect", transition="in", filter="fade")
            behavior = add(fade, "cBhvr")
            clock(behavior, dur=350)
            target(behavior, sid)
    for name, event in (("prevCondLst", "onPrev"), ("nextCondLst", "onNext")):
        cond = add(add(seq, name), "cond", evt=event, delay=0)
        add(add(cond, "tgtEl"), "sldTgt")
    ext = next((n for n in root.childNodes if n.namespaceURI == P and n.localName == "extLst"), None)
    root.insertBefore(timing, ext) if ext else root.appendChild(timing)
    return doc.toxml(encoding="UTF-8")


def apply_in_place(source, plan, *, before_replace=None, prepare_commit=None):
    """Validate a private temporary ZIP before replacing the selected source path."""
    path = Path(source).expanduser().resolve()
    require(path.suffix.lower() == ".pptx" and path.is_file(), "Expected existing PPTX")
    original = path.read_bytes()
    source_ref = {"path": str(path), "sha256": digest(original)}
    parts = read_package(io.BytesIO(original))
    inventory = inventory_from_parts(parts, source_ref)
    validate_plan(plan, inventory)
    selected = {p["part"] for p in plan["pages"]}
    baseline = content_snapshot(parts, selected)
    old_timing = {}
    for page in plan["pages"]:
        doc = minidom.parseString(parts[page["part"]])
        old_timing[page["part"]] = [n.toxml() for n in doc.documentElement.childNodes if n.namespaceURI == P and n.localName == "timing"]
        parts[page["part"]] = compile_slide(parts[page["part"]], page)
    stat = path.stat()
    fd, temp_name = tempfile.mkstemp(prefix=".ppt-animation-", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temporary = Path(temp_name)
    try:
        with zipfile.ZipFile(io.BytesIO(original)) as archive, zipfile.ZipFile(temporary, "w") as output:
            output.comment = archive.comment
            for info in archive.infolist():
                output.writestr(info, parts[info.filename])
        report = verify_file(temporary, baseline, plan)
        after_hash = digest(temporary.read_bytes())
        result = {"status": "applied", "source": str(path), "before_sha256": source_ref["sha256"],
                  "after_sha256": after_hash, "baseline": baseline, "old_timing": old_timing, "verification": report}
        # Persist small recovery evidence before the irreversible rename, never a full deck copy.
        if prepare_commit:
            prepare_commit(result)
        if before_replace:
            before_replace()
        require(digest(path.read_bytes()) == source_ref["sha256"], "Source changed concurrently; original not overwritten")
        os.chmod(temporary, stat.st_mode & 0o777)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        return result
    finally:
        temporary.unlink(missing_ok=True)
