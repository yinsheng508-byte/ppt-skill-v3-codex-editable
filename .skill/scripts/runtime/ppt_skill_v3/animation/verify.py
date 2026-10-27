from __future__ import annotations

import io
import json
from xml.etree import ElementTree as ET

from .plan import require, steps
from .reader import NS, P, digest, read_package


def _structure(node, *, slide_root=False):
    # Only formatting whitespace outside text-bearing nodes is insignificant.
    text = node.text or ""
    if node.tag != f"{{{NS['a']}}}t" and not text.strip():
        text = ""
    return [node.tag, sorted(node.attrib.items()), text,
            [_structure(c) for c in node if not (slide_root and c.tag == f"{{{P}}}timing")]]


def _namespaces(data):
    return [list(item) for item in sorted(set((prefix or "", uri) for _, (prefix, uri) in ET.iterparse(io.BytesIO(data), events=("start-ns",))))]


def content_snapshot(parts, selected):
    """Hash all non-animation content, without storing a second whole deck."""
    hashes, namespaces = {}, {}
    for name, data in parts.items():
        if name in selected:
            root = ET.fromstring(data)
            hashes[name] = digest(json.dumps(_structure(root, slide_root=True), ensure_ascii=False, separators=(",", ":")).encode())
            namespaces[name] = _namespaces(data)
        else:
            hashes[name] = digest(data)
    return {"parts": hashes, "namespaces": namespaces,
            "signature": digest(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode())}


def verify_timing(data, page):
    root = ET.fromstring(data)
    trees = root.findall("p:timing", NS)
    expected = steps(page)
    require(len(trees) == (1 if expected else 0), "Missing/duplicate timing tree")
    if not expected:
        return {"slide_index": page["slide_index"], "clicks": 0, "effects": 0}
    timing = trees[0]
    require(list(root).index(timing) == len(list(root)) - (2 if root.find("p:extLst", NS) is not None else 1), "Invalid timing node order")
    clocks = timing.findall(".//p:cTn", NS)
    ids = [c.get("id") for c in clocks]
    require(all(i and i.isdigit() for i in ids) and len(set(ids)) == len(ids), "Duplicate/invalid timing IDs")
    require(len(clocks) == 2 + sum(2 + 3 * len(s) for s in expected), "Unexpected timing nodes")
    tm = timing.find("p:tnLst/p:par/p:cTn", NS)
    require(tm is not None and tm.get("nodeType") == "tmRoot" and tm.get("dur") == "indefinite", "Invalid timing root")
    seq = tm.find("p:childTnLst/p:seq", NS)
    require(seq is not None and seq.get("concurrent") == "1" and seq.get("nextAc") == "seek", "Invalid main sequence")
    main = seq.find("p:cTn", NS)
    require(main is not None and main.get("nodeType") == "mainSeq", "Missing mainSeq")
    for tag, event in (("prevCondLst", "onPrev"), ("nextCondLst", "onNext")):
        cond = seq.find(f"p:{tag}/p:cond", NS)
        require(cond is not None and cond.get("evt") == event and cond.get("delay") == "0" and
                cond.find("p:tgtEl/p:sldTgt", NS) is not None, "Missing manual navigation")
    wrappers = main.findall("p:childTnLst/p:par/p:cTn", NS)
    require(len(wrappers) == len(expected), "Click count mismatch")
    for wrapper, targets in zip(wrappers, expected):
        conds = wrapper.findall("p:stCondLst/p:cond", NS)
        require(len(conds) == 1 and conds[0].attrib == {"delay": "indefinite"}, "Reveal must wait for manual click")
        inner = wrapper.findall("p:childTnLst/p:par/p:cTn", NS)
        require(len(inner) == 1, "Missing WPS B inner container")
        conditions = inner[0].findall("p:stCondLst/p:cond", NS)
        require(len(conditions) == 1 and conditions[0].attrib == {"delay": "0"}, "Invalid B inner start")
        effects = inner[0].findall("p:childTnLst/p:par/p:cTn", NS)
        require(len(effects) == len(targets), "Missing full-unit members")
        for index, (effect, sid) in enumerate(zip(effects, targets)):
            require(effect.get("nodeType") == ("clickEffect" if index == 0 else "withEffect") and
                    effect.get("presetClass") == "entr" and effect.get("presetID") == "10", "Invalid entrance preset/start")
            start = effect.find("p:stCondLst/p:cond", NS)
            require(start is not None and start.attrib == {"delay": "0"}, "Automatic delayed reveal is unsupported")
            entrance = effect.find("p:childTnLst/p:animEffect", NS)
            require(entrance is not None and entrance.attrib == {"transition": "in", "filter": "fade"}, "Expected fade entrance")
            duration = entrance.find("p:cBhvr/p:cTn", NS)
            require(duration is not None and duration.get("dur") == "350", "Unexpected animation duration")
            visibility = effect.find("p:childTnLst/p:set", NS)
            require(visibility is not None, "Missing initial entrance visibility behavior")
            value = visibility.find("p:to/p:strVal", NS)
            attr = visibility.find("p:cBhvr/p:attrNameLst/p:attrName", NS)
            require(value is not None and value.get("val") == "visible" and attr is not None and attr.text == "style.visibility", "Invalid visibility behavior")
            for behavior in (entrance, visibility):
                target = behavior.find("p:cBhvr/p:tgtEl/p:spTgt", NS)
                require(target is not None and target.get("spid") == str(sid), "Animation target mismatch")
    require(len(timing.findall(".//p:animEffect", NS)) == sum(map(len, expected)) and
            len(timing.findall(".//p:set", NS)) == sum(map(len, expected)), "Unexpected extra effect")
    require(not timing.findall(".//p:cTn[@nodeType='afterEffect']", NS), "Automatic afterEffect forbidden")
    return {"slide_index": page["slide_index"], "clicks": len(expected), "effects": sum(map(len, expected))}


def verify_parts(parts, baseline, plan):
    selected = {p["part"] for p in plan["pages"]}
    current = content_snapshot(parts, selected)
    require(current["parts"] == baseline["parts"], "Non-animation content/parts changed")
    require(current["namespaces"] == baseline["namespaces"], "Namespace declarations changed")
    pages = [verify_timing(parts[p["part"]], p) for p in plan["pages"]]
    return {"ok": True, "content_unchanged": True, "content_signature": current["signature"],
            "pages": pages, "playback": {"wps": "pending_native_playback", "powerpoint": "pending_native_playback"}}


def verify_file(path, baseline, plan):
    return verify_parts(read_package(path), baseline, plan)
