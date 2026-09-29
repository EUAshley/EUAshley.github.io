"""CLI.

  python -m moneyshorts check   episodes/<id>.yaml     # fact-check gate only
  python -m moneyshorts script  episodes/<id>.yaml     # print script + timing estimate
  python -m moneyshorts preview episodes/<id>.yaml     # fast half-res render
  python -m moneyshorts build   episodes/<id>.yaml     # final 1080x1920 render + publish kit
  python -m moneyshorts release episodes/<id>.yaml [--platforms youtube,tiktok,instagram,linkedin]
                                                       # one cut + publish kit per platform
  python -m moneyshorts new     <id>                   # scaffold a new episode file
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

from .factcheck import check, report_markdown
from .spec import load_episode

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None):
    ap = argparse.ArgumentParser(prog="moneyshorts")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "script", "preview", "build"):
        p = sub.add_parser(name)
        p.add_argument("episode")
        p.add_argument("--out", default=None)
        p.add_argument("--workers", type=int, default=None)
        p.add_argument("--force", action="store_true", help="render even if fact-check fails (drafts only)")
    p = sub.add_parser("release")
    p.add_argument("episode")
    p.add_argument("--platforms", default="all", help="comma list or 'all'")
    p.add_argument("--out", default=None)
    p.add_argument("--workers", type=int, default=None)
    p.add_argument("--no-copy", action="store_true", help="don't copy results into renders/")
    p = sub.add_parser("new")
    p.add_argument("id")
    a = ap.parse_args(argv)

    if a.cmd == "new":
        dst = ROOT / "episodes" / f"{a.id}.yaml"
        if dst.exists():
            sys.exit(f"{dst} already exists")
        shutil.copy(ROOT / "templates" / "episode.yaml", dst)
        dst.write_text(dst.read_text().replace("EPISODE_ID", a.id))
        print(dst)
        return

    ep = load_episode(a.episode)
    out = Path(a.out) if a.out else ROOT / "out" / ep.id

    if a.cmd == "check":
        rep = check(ep)
        out.mkdir(parents=True, exist_ok=True)
        (out / "factcheck.md").write_text(report_markdown(ep, rep))
        for e in rep.errors:
            print("ERROR  ", e)
        for w in rep.warnings:
            print("warn   ", w)
        print(f"{'PASS' if rep.ok else 'FAIL'}: {len(rep.claims)} spoken claims checked, "
              f"{len(rep.errors)} errors, {len(rep.warnings)} warnings -> {out / 'factcheck.md'}")
        sys.exit(0 if rep.ok else 1)

    if a.cmd == "release":
        from .platforms import release, resolve_platforms
        t0 = time.time()
        res = release(ep, resolve_platforms(a.platforms), out / "release", workers=a.workers,
                      renders_dir=None if a.no_copy else ROOT / "renders")
        for r in res:
            shared = f"(same cut as {r['shared_render_with']})" if r["shared_render_with"] else "(own cut)"
            print(f"{r['platform']:>16}: {r['duration']:5.1f}s  {r['scenes']} scenes  {shared}  {r['video']}")
        print(f"done in {time.time() - t0:.0f}s -> {out / 'release' / 'release.md'}")
        return

    if a.cmd == "script":
        words = 0
        for sc in ep.scenes:
            print(f"[{sc.id} · {sc.type}] {sc.say}")
            words += len(sc.say.split())
        print(f"\n{words} words ≈ {words / 2.7:.0f}s at typical short-form pace")
        return

    from .render import build, ffprobe
    t0 = time.time()
    info = build(ep, out, workers=a.workers, preview=(a.cmd == "preview"), force=a.force)
    info["render_seconds"] = round(time.time() - t0, 1)
    info["probe"] = ffprobe(Path(info["video"]))
    for k, v in info.items():
        print(f"{k:>15}: {v}")


if __name__ == "__main__":
    main()
