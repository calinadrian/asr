"""Assemble the complete local game from the owned builders and validated inputs.

Builds under downloads/main-build by default. Installation verifies every hash,
keeps rollback copies, writes data before the executable and never opens saves.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / 'launcher/native-main-build.json'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def required_data():
    return json.loads(PROFILE.read_text())['data']


def validate_data(data):
    for name, expected in required_data().items():
        path = Path(data) / name
        if not path.is_file() or digest(path) != expected:
            raise ValueError(f'Main build needs the reviewed {name}; rebuild with asr build-main')


def build(installed, races, vanilla, source, output, version):
    import stamp_game
    import photo_archive
    import story_assets
    import story_npc_assets
    import deadmines_arena
    import wailing_arena
    output.mkdir(parents=True, exist_ok=False)
    data = output / 'Data'
    data.mkdir()
    for path in sorted((installed / 'Data').glob('*.MPQ')):
        if path.name.upper() not in {f'PATCH-{n}.MPQ' for n in 'STUVWZ'}:
            shutil.copyfile(path, data / path.name)
    for letter in 'VW':
        shutil.copyfile(races / f'patch-{letter}.MPQ', data / f'patch-{letter}.MPQ')
    print('Building complete story terrain and creatures', flush=True)
    archive, report = story_assets.prepare(vanilla, data)
    (data / 'patch-S.MPQ').write_bytes(archive)
    (output / 'story-assets.json').write_text(json.dumps(report, indent=2))
    (data / 'patch-T.MPQ').write_bytes(deadmines_arena.build_archive(vanilla))
    (data / 'patch-U.MPQ').write_bytes(wailing_arena.build_archive(vanilla))
    (data / 'patch-Z.MPQ').write_bytes(photo_archive.build_photos(ROOT / 'launcher/zone-photos'))
    archive, report = story_npc_assets.prepare(vanilla, data)
    (data / 'patch-Z.MPQ').write_bytes(archive)
    (output / 'story-npcs.json').write_text(json.dumps(report, indent=2))
    stamp_game.stamp(source, output / 'ASR.exe', version)
    finish(output, races, vanilla, version)


def finish(output, races, vanilla, version):
    from audit_story_bodies import audit
    from verify_race_expansion import verify
    data = output / 'Data'
    # The race verifier expects its artifacts at the candidate root and an
    # executable without the reversible final story payload.
    import starter_missions
    validation = output / 'race-validation'
    validation.mkdir(exist_ok=True)
    for letter in 'VW':
        shutil.copyfile(races / f'patch-{letter}.json', validation / f'patch-{letter}.json')
        shutil.copyfile(data / f'patch-{letter}.MPQ', validation / f'patch-{letter}.MPQ')
    (validation / 'ASR.exe').write_bytes(starter_missions.remove((output / 'ASR.exe').read_bytes()))
    print('Verifying all races, armor and asset dependencies', flush=True)
    races_report = verify(validation, races / 'baseline/Data')
    bodies_report = audit(data, vanilla)
    (output / 'validation.json').write_text(json.dumps(dict(races=races_report, bodies=bodies_report), indent=2))
    files = {p.relative_to(output).as_posix(): digest(p)
             for p in [output / 'ASR.exe', *sorted(data.glob('*.MPQ'))]}
    record = dict(version=version, files=files)
    (output / 'build.json').write_text(json.dumps(record, indent=2)+'\n')
    reviewed = dict(version=version, data={p.name: digest(p) for p in sorted(data.glob('patch-*.MPQ'))})
    PROFILE.write_text(json.dumps(reviewed, indent=2)+'\n')
    print(f'Complete main build: {output}', flush=True)


def install(candidate, installed, backup):
    from install_character_upgrade import atomic_copy
    record = json.loads((candidate / 'build.json').read_text())
    files = record['files']
    for relative, expected in files.items():
        if digest(candidate / relative) != expected:
            raise ValueError(f'Candidate hash mismatch: {relative}')
    validate_data(candidate / 'Data')
    changed = [r for r, expected in files.items()
               if not (installed / r).exists() or digest(installed / r) != expected]
    changed.sort(key=lambda r: (r == 'ASR.exe', r))
    backup.mkdir(parents=True, exist_ok=False)
    before = {}
    for relative in changed:
        path = installed / relative
        before[relative] = digest(path) if path.exists() else None
        if path.exists():
            dest = backup / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)
            if digest(dest) != before[relative]:
                raise ValueError(f'Backup hash mismatch: {relative}')
    journal = dict(candidate=str(candidate), installed=str(installed), before=before,
                   after=files, status='backed_up')
    journal_path = backup / 'installation.json'
    journal_path.write_text(json.dumps(journal, indent=2))
    copied = []
    try:
        for relative in changed:
            (installed / relative).parent.mkdir(parents=True, exist_ok=True)
            atomic_copy(candidate / relative, installed / relative)
            copied.append(relative)
        for relative, expected in files.items():
            if digest(installed / relative) != expected:
                raise ValueError(f'Installed hash mismatch: {relative}')
    except BaseException:
        for relative in reversed(copied):
            if before[relative] is None:
                (installed / relative).unlink(missing_ok=True)
            else:
                atomic_copy(backup / relative, installed / relative)
        journal['status'] = 'rolled_back'
        journal_path.write_text(json.dumps(journal, indent=2))
        raise
    journal['status'] = 'installed'
    journal_path.write_text(json.dumps(journal, indent=2))
    print(f'Installed and hash-verified {len(changed)} files; rollback: {backup}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installed', type=Path, default=Path(r'D:\Personal\ASR'))
    parser.add_argument('--races', type=Path, default=ROOT / 'downloads/race-expansion')
    parser.add_argument('--vanilla', type=Path, default=ROOT / 'downloads/durotar-assets/vanilla-1.12.1/app/Data')
    parser.add_argument('--source', type=Path, default=ROOT / 'downloads/race-expansion/baseline/ASR.exe')
    parser.add_argument('--out', type=Path, default=ROOT / 'downloads/main-build')
    parser.add_argument('--version', default='0.124.4')
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--backup', type=Path)
    args = parser.parse_args()
    if args.install:
        if not args.backup:
            parser.error('--install requires --backup')
        install(args.out, args.installed, args.backup)
    else:
        build(args.installed, args.races, args.vanilla, args.source, args.out, args.version)
