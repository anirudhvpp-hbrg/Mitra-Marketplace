"""Two feasibility checks with models already in the library and runtimes already in the package:

1. SmolVLM 256M (GGUF + mmproj) in llama-server: can it read the text off a page image?
   This would let Anything to MD and Mitra PDF handle scanned pages.
2. Piper TTS (amy) in audio.cpp: can it speak a sentence? This would give read-aloud.

Prints what happened and the peak memory; writes nothing outside ~/.mitra/tmp.
"""
import base64
import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workers"))
from mitra_workers import models, paths  # noqa: E402

TMP = paths.HOME / "tmp"
TMP.mkdir(parents=True, exist_ok=True)


def peak(name):
    best = {}
    for f in sorted((paths.HOME / "memory" / "events").glob("*.jsonl"))[-2:]:
        for line in f.read_text("utf-8", errors="replace").splitlines():
            if '"model.run"' in line and name in line:
                best = json.loads(line)["data"]
    return best


def vision():
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (900, 420), "white")
    d = ImageDraw.Draw(img)
    try:
        big, small = ImageFont.truetype("arial.ttf", 34), ImageFont.truetype("arial.ttf", 24)
    except OSError:
        big = small = ImageFont.load_default()
    d.text((40, 30), "Quarterly Plan 2026", fill="black", font=big)
    for i, line in enumerate(["Ship the export fix by Thursday.", "Release stays on the 20th of November.",
                              "Budget approved: 4,200 dollars for the pilot.", "Owner: Priya Raman"]):
        d.text((40, 110 + i * 60), line, fill="black", font=small)
    png = TMP / "scan-test.png"
    img.save(png)
    folder = models.find_model("smolvlm-256m-instruct-q8_0")
    if not folder:
        return print("vision: SmolVLM not found in the library")
    main = next(p for p in folder.parent.glob("*.gguf") if "mmproj" not in p.name)
    proj = next(p for p in folder.parent.glob("*.gguf") if "mmproj" in p.name)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    cmd = models.governed("measure", "smolvlm-256m", 100, [models.runtime_path("llama-server"), "-m", str(main), "--mmproj", str(proj),
                          "--host", "127.0.0.1", "--port", str(port), "-c", "4096", "-t", str(paths.config()["threads"]), "-ngl", "0", "--no-repack"],
                          hold=True, timeout=300, budget_mb=1024)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=open(TMP / "smolvlm.log", "w"))
    try:
        for _ in range(600):
            if proc.poll() is not None:
                return print("vision: server stopped at start:", (TMP / "smolvlm.log").read_text(errors="replace")[-400:])
            try:
                if urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1).status == 200:
                    break
            except Exception:
                time.sleep(0.1)
        b64 = base64.b64encode(png.read_bytes()).decode()
        body = {"messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
            {"type": "text", "text": "Read all the text in this image, line by line, exactly as written."}]}], "max_tokens": 200, "temperature": 0}
        t0 = time.time()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        res = json.loads(urllib.request.urlopen(req, timeout=300).read())
        print(f"vision: answered in {time.time() - t0:.0f} s:\n" + res["choices"][0]["message"]["content"])
    except Exception as e:
        print("vision: failed:", str(e)[:300], "|", (TMP / "smolvlm.log").read_text(errors="replace")[-300:])
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=15)
        except Exception:
            proc.kill()
        print("vision: peak", peak("smolvlm-256m").get("peak_mb"), "MB")
        png.unlink(missing_ok=True)


def tts():
    folder = models.find_model("piper-tts-amy-en", patterns=("*.onnx",))
    if not folder:
        return print("tts: piper voice not found in the library")
    out = TMP / "tts-test.wav"
    out.unlink(missing_ok=True)
    cmd = models.governed("measure", "piper-amy", 100, [models.runtime_path("audio.cpp"), "--task", "tts", "--family", "piper_tts", "--model", str(folder),
                          "--backend", "cpu", "--text", "The release stays on the twentieth of November.", "--out", str(out)], budget_mb=1024)
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if out.exists():
        print(f"tts: wrote {models.wav_seconds(out):.1f} s of speech, peak {peak('piper-amy').get('peak_mb')} MB")
        out.unlink()
    else:
        print("tts: no audio. exit", r.returncode, "|", (r.stderr or r.stdout).strip()[-500:])


vision()
tts()
