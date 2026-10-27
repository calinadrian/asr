"""Apply a locally verified UI patch profile to an exact matching desktop build."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile


def patch(source, destination, profile_path, backup):
    source = source.resolve(strict=True)
    destination = destination.resolve()
    profile = json.loads(profile_path.read_text())
    original = source.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    if digest == profile['patched_sha256'] and source == destination:
        print('This executable already has the verified UI patch.')
        return
    if digest != profile['source_sha256']:
        raise ValueError('The game build changed. This patch must be re-analyzed for the new executable.')
    modified = bytearray(original)
    for entry in profile['patches']:
        offset = entry['offset']
        before, after = bytes.fromhex(entry['before']), bytes.fromhex(entry['after'])
        if len(before) != len(after) or offset < 0 or modified[offset:offset + len(before)] != before:
            raise ValueError('Patch precondition failed: ' + entry['name'])
        modified[offset:offset + len(after)] = after
    if hashlib.sha256(modified).hexdigest() != profile['patched_sha256']:
        raise ValueError('Patched executable did not match the verified test copy')
    backup.parent.mkdir(parents=True, exist_ok=True)
    if backup.exists():
        if hashlib.sha256(backup.read_bytes()).hexdigest() != digest:
            raise ValueError('Existing backup does not match; choose a different backup file')
    else:
        backup.write_bytes(original)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=destination.name + '.', suffix='.tmp', delete=False) as output:
            temporary = Path(output.name)
            output.write(modified)
        os.replace(temporary, destination)
        print('Applied verified footer patch: ' + str(destination))
        print('Original executable backup: ' + str(backup))
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--backup', type=Path, required=True)
    args = parser.parse_args()
    patch(args.source, args.output, args.profile, args.backup)
