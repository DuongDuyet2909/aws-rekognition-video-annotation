"""Download/restore the complete demo release without requiring AWS credentials."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def checksum(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verify_checksum(path, expected):
    if checksum(path) != expected:
        raise ValueError('Archive checksum mismatch. No files were extracted.')


def safe_extract(archive, destination):
    destination = Path(destination).resolve()
    if (destination/'output').exists() or (destination/'zebras.mp4').exists():
        raise ValueError('Existing video/output detected. Use a clean clone; existing work will not be overwritten.')
    with zipfile.ZipFile(archive) as bundle:
        seen = set()
        for member in bundle.infolist():
            name = member.filename
            relative = PurePosixPath(name)
            allowed = name in {'zebras.mp4', 'demo_manifest.json'} or name.startswith('output/')
            target = (destination/name).resolve()
            if (not allowed or '\\' in name or relative.is_absolute() or '..' in relative.parts
                    or not target.is_relative_to(destination)
                    or (member.external_attr >> 16) & 0o170000 == 0o120000
                    or name.casefold() in seen):
                raise ValueError(f'Unsafe or duplicate archive entry: {name}')
            seen.add(name.casefold())
        for member in bundle.infolist():
            target = destination/member.filename
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(member) as source, target.open('wb') as stream:
                shutil.copyfileobj(source, stream)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--download', action='store_true', help='Download the GitHub Release data archive')
    choice.add_argument('--archive', type=Path, help='Use an already-downloaded release archive')
    args = parser.parse_args()
    metadata = json.loads((ROOT/'reports/demo_asset.json').read_text(encoding='utf-8'))
    if (ROOT/'output').exists() or (ROOT/'zebras.mp4').exists():
        parser.error('Demo files already exist. Run the offline commands or restore into a clean clone.')
    archive = args.archive
    if args.download:
        archive = ROOT/'.downloads'/metadata['filename']
        archive.parent.mkdir(parents=True, exist_ok=True)
        partial = archive.with_suffix('.part')
        print(f"Downloading {metadata['size_bytes']/1024/1024:.1f} MiB from GitHub Releases…", flush=True)
        with urllib.request.urlopen(metadata['download_url'], timeout=120) as response, partial.open('wb') as stream:
            shutil.copyfileobj(response, stream)
        partial.replace(archive)
    verify_checksum(archive, metadata['sha256'])
    safe_extract(archive, ROOT)
    sys.path.insert(0, str(ROOT))
    from pipeline import export_yolo
    export_yolo(ROOT/'output', every=5, validation_fraction=.2, gap=30)
    print('Demo restored and YOLO paths regenerated. No AWS calls were made.')
    print('Next: python main.py detect --offline --stride 1 --max-api-calls 0')


if __name__ == '__main__':
    main()
