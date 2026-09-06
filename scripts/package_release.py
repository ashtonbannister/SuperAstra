#!/usr/bin/env python3
"""Build a source release from maintained files, excluding local runtime data."""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {
    ".gitignore", ".gitattributes", "LICENSE", "README.md", "CONTRIBUTING.md",
    "LOAD-IN-BIZHAWK.lua", "Start-Windows.cmd", "start-linux.sh", "run.py",
    "requirements-dev.txt",
}
DIRECTORIES = {"astra_snes", "emulator", "profiles", "assets", "tests", "docs", "scripts"}
EXTENSIONS = {".py", ".lua", ".json", ".png", ".svg", ".md", ".txt"}


def main():
    files = [ROOT / name for name in ROOT_FILES]
    for folder in sorted(DIRECTORIES):
        for path in (ROOT / folder).rglob("*"):
            if (path.is_file() and not path.is_symlink()
                    and not any(part.startswith(".") or part == "__pycache__"
                                for part in path.relative_to(ROOT).parts)
                    and path.suffix in EXTENSIONS):
                files.append(path)
    output = ROOT / "dist" / "Astra-SNES.zip"
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(files):
            archive.write(path, Path("Astra-SNES") / path.relative_to(ROOT))
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Release archive failed its integrity check")
    print(f"Created {output} ({len(files)} files)")


if __name__ == "__main__":
    main()
