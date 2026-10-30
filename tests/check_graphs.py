#!/usr/bin/env python3
"""check_graphs.py [server] — static check of every workflow against the live server's /object_info, WITHOUT queueing
anything (ComfyUI has no dry-run: a valid /prompt renders). Checks node classes, required inputs (dynamic-combo children
included), link targets and output slots, and combo values. Placeholders are filled with sample values."""
import json, pathlib, sys, urllib.request
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import tape

SAMPLE = {"NAME": "check", "PROMPT": "a cat", "NEGATIVE": "x", "SEED": 1, "ASPECT": "4:3 (Standard)", "IMAGE": None,
          "IMAGE_STRENGTH": 0.7, "TAGS": "x", "LYRICS": "[Instrumental]", "BPM": 64, "KEY": "D minor", "SECONDS": 10}

def check(graph, oi):
    errs = []
    for nid, n in graph.items():
        ct = n["class_type"]
        if ct not in oi: errs.append(f"{nid}: no node class {ct}"); continue
        spec = oi[ct]["input"]; req = spec.get("required", {}); allin = {**req, **spec.get("optional", {})}
        ins = n["inputs"]
        for k, s in req.items():
            if k not in ins and not any(x.startswith(k + ".") for x in ins): errs.append(f"{nid} {ct}: missing required input {k}"); continue
            if s[0] == "COMFY_DYNAMICCOMBO_V3":
                opt = next((o for o in s[1]["options"] if o["key"] == ins[k]), None)
                if not opt: errs.append(f"{nid} {ct}.{k}: {ins[k]!r} not an option"); continue
                for ck in opt["inputs"].get("required", {}):
                    if f"{k}.{ck}" not in ins: errs.append(f"{nid} {ct}: missing {k}.{ck}")
        for k, v in ins.items():
            base = k.split(".")[0]
            if base not in allin and base != "values": errs.append(f"{nid} {ct}: unknown input {k}")
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                if v[0] not in graph: errs.append(f"{nid} {ct}.{k}: link to missing node {v[0]}")
                elif v[1] >= len(oi[graph[v[0]]["class_type"]]["output"]): errs.append(f"{nid} {ct}.{k}: bad output slot {v[1]}")
            elif base in allin and v is not None and ct != "LoadImage" and k == base:
                s0 = allin[base]
                opts = s0[0] if isinstance(s0[0], list) else (s0[1].get("options") if s0[0] == "COMBO" and len(s0) > 1 else None)
                if opts is not None and v not in opts: errs.append(f"{nid} {ct}.{k}: {v!r} not in its options")
    return errs

def main():
    server = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8188"
    oi = json.load(urllib.request.urlopen(server + "/object_info", timeout=60))
    bad = 0
    for p in sorted((tape.HERE / "workflows").glob("*.json")):
        errs = check(tape.load_graph(p, SAMPLE), oi)
        print(("ok  " if not errs else "BAD ") + p.name + "".join("\n    " + e for e in errs)); bad += bool(errs)
    sys.exit(1 if bad else 0)

if __name__ == "__main__": main()
