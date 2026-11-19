"""What the package holds, and bringing its models inside it.

    mitra-marketplace models         the model each app would use, and where it is read from
    mitra-marketplace models sync    copy those models (and the llama runtime) into this folder
    mitra-marketplace size           what the whole package takes on disk

Models are normally read from the model library (models_dir, an external drive on this
laptop). `sync` copies only the ones an installed app actually uses into <root>/models, which
is searched first, so every app keeps working with the library unplugged and the package can
be carried to another system whole.
"""
import json
import shutil
import sys
from pathlib import Path

from . import models, paths, registry

PKG_MODELS = paths.ROOT / "models"
PKG_LLAMA = paths.ROOT / "runtimes" / "llama"
SIDE_FILE_MAX = 5 << 20   # readme, config and provenance travel with the weights; other weights do not


def mb(n: int) -> float:
    return round(n / (1 << 20), 1)


def tree_bytes(p: Path, skip=()) -> int:
    if p.is_file():
        return p.stat().st_size
    if not p.is_dir():
        return 0
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file() and not any(s in f.parts for s in skip))


def needed() -> list[dict]:
    """One row per capability that some installed app declares."""
    users: dict[str, list[str]] = {}
    for a in registry.discover().values():
        for cap in a.manifest.get("needs", []):
            users.setdefault(cap, []).append(a.id)
    rows = []
    for cap, apps in sorted(users.items()):
        p = models.pick(cap)
        f = Path(p["file"]) if p.get("file") else None
        rows.append({"capability": cap, "apps": apps, "model": p.get("model"), "file": str(f) if f else None,
                     "size_mb": mb(f.stat().st_size) if f else 0, "est_ram_mb": p.get("est_mb"), "ready": p.get("ready", False),
                     "in_package": bool(f and PKG_MODELS in f.parents), "hint": p.get("hint", "")})
    return rows


def sync() -> dict:
    copied, kept = [], []
    for row in needed():
        if not row["file"]:
            continue
        src = Path(row["file"])
        dst_dir = PKG_MODELS / row["model"]
        if row["in_package"] or (dst_dir / src.name).is_file() and (dst_dir / src.name).stat().st_size == src.stat().st_size:
            kept.append(row["model"])
            continue
        dst_dir.mkdir(parents=True, exist_ok=True)
        folder = next((p for p in src.parents if p.name == row["model"]), src.parent)
        for f in [src] + [f for f in folder.iterdir() if f.is_file() and f != src and f.stat().st_size <= SIDE_FILE_MAX]:
            shutil.copy2(f, dst_dir / f.name)
        copied.append({"model": row["model"], "mb": row["size_mb"], "from": str(folder)})
    # The llama runtime: only the CPU build. Ollama's folder also holds gigabytes of GPU
    # libraries in subfolders, which a machine with no graphics card never loads.
    runtime = None
    rt = models.runtime_path("llama-server")
    if rt and PKG_LLAMA not in Path(rt).parents:
        PKG_LLAMA.mkdir(parents=True, exist_ok=True)
        n = 0
        for f in Path(rt).parent.iterdir():
            if f.is_file() and f.suffix.lower() in (".exe", ".dll", ".so", ".dylib", "") and "quantize" not in f.name:
                shutil.copy2(f, PKG_LLAMA / f.name)
                n += f.stat().st_size
        runtime = {"from": str(Path(rt).parent), "mb": mb(n)}
    try:
        (paths.HOME / "run" / "model-index.json").unlink()   # so the next lookup finds the copies
    except OSError:
        pass
    return {"copied": copied, "already_in_package": kept, "llama_runtime": runtime}


def size() -> dict:
    parts = {
        "launcher and governor (bin)": tree_bytes(paths.ROOT / "bin"),
        "apps and web pages": tree_bytes(paths.ROOT / "apps") + tree_bytes(paths.ROOT / "web"),
        "workers (Python source)": tree_bytes(paths.ROOT / "workers", skip=("__pycache__",)),
        "runtime: llama": tree_bytes(PKG_LLAMA),
        "runtime: whisper.cpp": tree_bytes(paths.ROOT / "runtimes" / "whisper.cpp"),
        "runtime: audio.cpp": tree_bytes(paths.ROOT / "runtimes" / "audio.cpp"),
        "models in the package": tree_bytes(PKG_MODELS),
    }
    outside = {}
    for row in needed():
        if row["file"] and not row["in_package"]:
            outside[row["model"]] = Path(row["file"]).stat().st_size
    rt = models.runtime_path("llama-server")
    if rt and PKG_LLAMA not in Path(rt).parents:
        outside["llama runtime (CPU files only)"] = sum(f.stat().st_size for f in Path(rt).parent.iterdir() if f.is_file())
    ff = shutil.which("ffmpeg") or paths.config().get("ffmpeg") or ""
    if ff and Path(ff).is_file():
        outside["ffmpeg"] = Path(ff).stat().st_size
    return {"package_mb": mb(sum(parts.values())), "parts_mb": {k: mb(v) for k, v in parts.items()},
            "outside_mb": {k: mb(v) for k, v in outside.items()}, "total_mb": mb(sum(parts.values()) + sum(outside.values())),
            "root": str(paths.ROOT)}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "models"
    sub = sys.argv[2] if len(sys.argv) > 2 else ""
    if "--json" in sys.argv:
        print(json.dumps({"models": needed, "size": size}.get(cmd, needed)() if sub != "sync" else sync()))
        return
    if cmd == "size":
        s = size()
        print(f"Package at {s['root']}")
        for k, v in s["parts_mb"].items():
            print(f"  {k:<34} {v:>8.1f} MB")
        print(f"  {'in the package':<34} {s['package_mb']:>8.1f} MB")
        if s["outside_mb"]:
            print("Used from outside the package:")
            for k, v in s["outside_mb"].items():
                print(f"  {k:<34} {v:>8.1f} MB")
        print(f"Everything Mitra uses: {s['total_mb']:.1f} MB")
        return
    if sub == "sync":
        r = sync()
        for c in r["copied"]:
            print(f"Copied {c['model']} ({c['mb']} MB) from {c['from']}")
        for m in r["already_in_package"]:
            print(f"Already in the package: {m}")
        if r["llama_runtime"]:
            print(f"Copied the llama runtime ({r['llama_runtime']['mb']} MB, CPU files only) from {r['llama_runtime']['from']}")
        print(f"Models are in {PKG_MODELS}")
        return
    for row in needed():
        where = "in the package" if row["in_package"] else (row["file"] or "not found: " + row["hint"])
        print(f"  {row['capability']:<14} {row['model'] or '-':<34} {row['size_mb']:>7.1f} MB on disk, about {row['est_ram_mb'] or '?'} MB RAM"
              f"\n  {'':<14} used by {', '.join(row['apps'])}; {where}")


if __name__ == "__main__":
    main()
