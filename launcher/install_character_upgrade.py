"""Install the validated local character upgrade with verified rollback copies.

Without --apply, only inspect the candidate and installed files. Only ASR.exe,
Data/patch-W.MPQ and Data/patch-V.MPQ are changed; saves are not accessed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from character_equipment_patch import apply as equipment_patch
from verify_character_upgrade import verify


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def atomic_copy(source, destination):
    handle, name = tempfile.mkstemp(prefix=destination.name+'.upgrade-', suffix='.tmp', dir=destination.parent)
    os.close(handle)
    temporary = Path(name)
    try:
        shutil.copyfile(source, temporary)
        if digest(temporary) != digest(source):
            raise ValueError(f'Copy hash mismatch: {destination}')
        try:
            os.replace(temporary, destination)
        except PermissionError:
            if destination.suffix.lower() not in ('.exe', '.mpq') or not destination.exists():
                raise
            # Windows can deny replacement of a mapped image/archive while still
            # allowing its directory entry to move. Keep it; never stop the process.
            displaced = destination.with_name(destination.name+'.previous-'+uuid.uuid4().hex[:12])
            os.rename(destination, displaced)
            try:
                os.replace(temporary, destination)
            except BaseException:
                os.rename(displaced, destination)
                raise
            return displaced
    finally:
        temporary.unlink(missing_ok=True)


def install(candidate, installed, backup, apply=False):
    candidate, installed, backup = candidate.resolve(), installed.resolve(), backup.resolve()
    planned = [('Data/patch-V.MPQ', 'patch-V.MPQ'), ('Data/patch-W.MPQ', 'patch-W.MPQ'), ('ASR.exe', 'ASR.exe')]
    for relative, source in planned:
        if not (candidate/source).is_file() or not (installed/relative).parent.is_dir():
            raise ValueError(f'Missing candidate file or installed parent: {relative}')
    wanted = {relative: digest(candidate/source) for relative, source in planned}
    before = {relative: digest(installed/relative) if (installed/relative).exists() else None
              for relative, _ in planned}
    if wanted == before:
        print('The complete character upgrade is already installed')
        return
    current = (installed/'ASR.exe').read_bytes()
    staged = (candidate/'ASR.exe').read_bytes()
    if equipment_patch(current) != staged or equipment_patch(staged) != staged:
        raise ValueError('The installed executable changed since the candidate was prepared')
    race_report = json.loads((candidate/'patch-W.json').read_text())
    if before['Data/patch-W.MPQ'] != race_report['base_race_archive_sha256']:
        raise ValueError('The installed race archive changed since preparation')
    validation = verify([candidate/'patch-V.MPQ', candidate/'patch-W.MPQ'], installed/'Data')
    print(f'Validated {validation["models"]} models and {validation["assets"]} assets', flush=True)
    for relative, _ in planned:
        print(f'{installed/relative}: {before[relative]} -> {wanted[relative]}', flush=True)
    if not apply:
        print('Inspection complete; --apply is required to install')
        return
    backup.mkdir(parents=True, exist_ok=False)
    for relative, _ in planned:
        if before[relative] is not None:
            dest = backup/relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(installed/relative, dest)
            if digest(dest) != before[relative]:
                raise ValueError(f'Rollback backup failed verification: {relative}')
    record = dict(installed=str(installed), candidate=str(candidate), before=before, after=wanted,
                  validation=validation, status='backed_up')
    journal = backup/'installation.json'
    journal.write_text(json.dumps(record, indent=2)+'\n')
    changed = []
    retained = []
    try:
        for relative, source in planned:
            if before[relative] == wanted[relative]:
                continue
            displaced = atomic_copy(candidate/source, installed/relative)
            if displaced is not None:
                retained.append(str(displaced))
            changed.append(relative)
        for relative, _ in planned:
            if digest(installed/relative) != wanted[relative]:
                raise ValueError(f'Installed file hash mismatch: {relative}')
        if equipment_patch((installed/'ASR.exe').read_bytes()) != staged:
            raise ValueError('Installed equipment bridge failed verification')
    except BaseException:
        for relative in reversed(changed):
            if before[relative] is None:
                (installed/relative).unlink(missing_ok=True)
            else:
                atomic_copy(backup/relative, installed/relative)
        record['status'] = 'rolled_back'
        journal.write_text(json.dumps(record, indent=2)+'\n')
        raise
    record['status'] = 'installed'
    record['retained_replaced_files'] = retained
    journal.write_text(json.dumps(record, indent=2)+'\n')
    print(f'Installed and verified. Rollback copies: {backup}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--installed', type=Path, required=True)
    parser.add_argument('--backup', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    install(args.candidate, args.installed, args.backup, args.apply)
