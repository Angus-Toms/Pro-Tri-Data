from __future__ import annotations

import json
import subprocess
from pathlib import Path

from PIL import Image, UnidentifiedImageError

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
BUCKET_NAME = "ptd-static-assets"
R2_PREFIX = "athlete_imgs"
WRANGLER_BIN = "wrangler"

def crop_top_square(image: Image.Image) -> Image.Image:
    width, height = image.size
    square = min(width, height)
    left = (width - square) // 2
    top = 0
    right = left + square
    bottom = top + square
    return image.crop((left, top, right, bottom))


def compress_images(img_dir: Path, sizes: tuple[int, ...]) -> None:
    for path in sorted(img_dir.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_EXTS:
            continue

        output_paths = [
            img_dir / str(size) / f"{path.stem}.webp" for size in sizes
        ]
        if all(output_path.exists() for output_path in output_paths):
            continue

        try:
            with Image.open(path) as image:
                image.load()
                square = crop_top_square(image)

                for size, output_path in zip(sizes, output_paths):
                    if output_path.exists():
                        continue
                    resized = square.resize((size, size), Image.LANCZOS)
                    resized.save(output_path, format="WEBP", quality=85, method=6)
        except UnidentifiedImageError:
            print(f"Warning: cannot identify image file '{path}'")


def upload_dir(
    bucket: str,
    size_dir: Path,
    *,
    prefix: str,
    wrangler: str,
) -> None:
    if not size_dir.exists():
        raise SystemExit(f"Missing directory: {size_dir}")

    prefix = prefix.strip("/")
    list_prefix = f"{prefix}/{size_dir.name}".strip("/")
    existing_keys = list_existing_keys(bucket, list_prefix, wrangler)
    for path in sorted(size_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(size_dir).as_posix()
        if prefix:
            key = f"{prefix}/{size_dir.name}/{relative}"
        else:
            key = f"{size_dir.name}/{relative}"
        if key in existing_keys:
            continue
        subprocess.run(
            [
                wrangler,
                "r2",
                "object",
                "put",
                f"{bucket}/{key}",
                "--remote",
                "--file",
                str(path),
            ],
            check=True,
        )


def list_existing_keys(bucket: str, prefix: str, wrangler: str) -> set[str]:
    keys: set[str] = set()
    args = [wrangler, "r2", "object", "list", bucket, "--remote"]
    if prefix:
        args.extend(["--prefix", prefix])
    result = subprocess.run(args, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        print(
            "Warning: failed to list bucket objects; proceeding without skip logic."
            + (f" Details: {stderr}" if stderr else "")
        )
        return keys

    output = (result.stdout or "").splitlines()
    for line in output:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.lower().startswith("key"):
            continue
        if stripped.startswith("─"):
            continue
        if stripped.lower().startswith("no objects"):
            return set()
        key = stripped.split()[0]
        if key:
            keys.add(key)
    return keys


def upload_images(img_dir: Path, bucket: str, prefix: str, wrangler: str) -> None:
    for size in ("64", "128"):
        upload_dir(bucket, img_dir / size, prefix=prefix, wrangler=wrangler)


def main() -> None:
    img_dir = Path("./data/athlete_imgs")
    if not img_dir.exists():
        raise SystemExit(f"Image directory does not exist: {img_dir}")

    upload_images(img_dir, BUCKET_NAME, R2_PREFIX, WRANGLER_BIN)


if __name__ == "__main__":
    main()
