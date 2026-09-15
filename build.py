#!/usr/bin/env python3
"""Build a verified static Pages artifact from public GitHub release assets."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
from urllib.request import Request, urlopen

ALLOWED_BACKING_BASE_URL = "https://github.com/raymondeinhornfinkle/audio-feed/releases/download"
METADATA_FILES = {"transcript.txt", "rss-item.xml", "published-package.json"}

def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def public_open(request):
    return urlopen(request, timeout=60)


def build(root=Path(__file__).resolve().parent, opener=public_open):
    root = Path(root)
    manifest = json.loads((root / "asset-manifest.json").read_text())
    capacity = manifest["capacity_bytes"]
    require(manifest["backing_base_url"] == ALLOWED_BACKING_BASE_URL,
            "Manifest backing release base is not allowlisted")
    prefix = ALLOWED_BACKING_BASE_URL + "/"
    assets = manifest["assets"]
    require(sum(item["bytes"] for item in assets) <= capacity, "Manifest exceeds media capacity")
    site = root / "_site"
    staging = root / "_site.tmp"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    try:
        links = []
        for item in assets:
            require(re.fullmatch(r"article-[A-Za-z0-9._-]+", item["release_name"]),
                    "Invalid release name")
            require(item["destination"] == f'releases/{item["release_name"]}/article.mp3',
                    "Invalid asset destination")
            require(item["source_url"].startswith(prefix)
                    and item["source_url"] == prefix + item["release_name"] + "/article.mp3",
                    "Asset source is outside the allowed backing release path")
            destination = staging / item["destination"]
            require(destination.resolve().is_relative_to(staging.resolve()), "Invalid asset destination")
            destination.parent.mkdir(parents=True, exist_ok=True)
            request = Request(item["source_url"], headers={"User-Agent": "Colossus-Pages-Builder/1.0",
                                                            "Accept-Encoding": "identity"})
            digest, count = hashlib.sha256(), 0
            with opener(request) as response, destination.open("xb") as output:
                require(getattr(response, "status", None) == 200, "Backing asset download failed")
                for block in iter(lambda: response.read(1024 * 1024), b""):
                    count += len(block)
                    require(count <= item["bytes"], "Downloaded asset exceeds declared size")
                    digest.update(block)
                    output.write(block)
            require(count == item["bytes"] and digest.hexdigest() == item["sha256"],
                    "Downloaded asset failed size or SHA-256 verification")
            metadata_root = root / "releases" / item["release_name"]
            require(set(item["metadata"]) == METADATA_FILES, "Unexpected canonical metadata set")
            for filename, expected in item["metadata"].items():
                source = metadata_root / filename
                require(source.is_file() and not source.is_symlink() and sha(source) == expected,
                        "Canonical metadata failed SHA-256 verification")
                shutil.copyfile(source, destination.parent / filename)
            links.append(f'<li><a href="{item["destination"]}">{item["release_name"]}</a></li>')
        (staging / ".nojekyll").write_bytes(b"")
        (staging / "index.html").write_text("<!doctype html><meta charset=utf-8><title>Colossus audio</title>"
                                             "<h1>Colossus audio</h1><ul>" + "".join(links) + "</ul>\n")
        total = sum(path.stat().st_size for path in staging.rglob("*") if path.is_file())
        require(total <= capacity, "Static Pages artifact exceeds capacity")
        if site.exists():
            shutil.rmtree(site)
        staging.rename(site)
        return {"status": "built", "assets": len(assets), "bytes": total}
    finally:
        if staging.exists():
            shutil.rmtree(staging)


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
