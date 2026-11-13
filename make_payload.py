"""Zip dist/RainingMd into payload/payload.zip (embedded into rainingmd-installer.exe)."""
import zipfile
from pathlib import Path

src = Path("dist/RainingMd")
out = Path("payload/payload.zip")
out.parent.mkdir(exist_ok=True)
files = [f for f in sorted(src.rglob("*")) if f.is_file()]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for f in files:
        z.write(f, f.relative_to(src).as_posix())
print(f"payload: {len(files)} files, {out.stat().st_size / 1024 ** 2:.0f} MB")
