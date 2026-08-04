#!/usr/bin/env python3
"""gpt-image-2 helper: generate (text->image) or edit (reference image -> image).

Usage:
  akc run -- python3 genimg.py gen  <out.png> <prompt-file>
  akc run -- python3 genimg.py edit <out.png> <prompt-file> <ref1.png> [ref2.png ...]

OPENAI_API_KEY must be in env (inject via akc run; never print it).
"""
import base64
import json
import os
import sys
import urllib.request


API = "https://api.openai.com/v1/images"
MODEL = "gpt-image-2"


def _req(url, data, headers):
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)


def gen(out_png, prompt):
    key = os.environ["OPENAI_API_KEY"]
    body = json.dumps({
        "model": MODEL,
        "prompt": prompt,
        "size": "1024x1024",
        "quality": "high",
        "n": 1,
    }).encode()
    res = _req(API + "/generations", body,
               {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    _save(res, out_png)


def edit(out_png, prompt, refs):
    key = os.environ["OPENAI_API_KEY"]
    boundary = "----genimgboundary7f3e"
    parts = []

    def field(name, value):
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())

    field("model", MODEL)
    field("prompt", prompt)
    field("size", "1024x1024")
    field("quality", "high")
    for i, ref in enumerate(refs):
        with open(ref, "rb") as f:
            img = f.read()
        parts.append(
            (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image[]\"; "
             f"filename=\"ref{i}.png\"\r\nContent-Type: image/png\r\n\r\n").encode() + img + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    res = _req(API + "/edits", body,
               {"Authorization": f"Bearer {key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}"})
    _save(res, out_png)


def _save(res, out_png):
    b64 = res["data"][0]["b64_json"]
    with open(out_png, "wb") as f:
        f.write(base64.b64decode(b64))
    print(f"saved {out_png} ({os.path.getsize(out_png)} bytes)")


if __name__ == "__main__":
    mode = sys.argv[1]
    out = sys.argv[2]
    with open(sys.argv[3], encoding="utf-8") as f:
        prompt_text = f.read()
    if mode == "gen":
        gen(out, prompt_text)
    elif mode == "edit":
        edit(out, prompt_text, sys.argv[4:])
    else:
        raise SystemExit(f"unknown mode {mode}")
