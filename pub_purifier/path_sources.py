# SPDX-License-Identifier: MIT
"""Relocate owner-bounded source trees by changing native path fields only."""
import os
from pathlib import Path
import shutil
import yaml


def within(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def stage_sources(source_root, project, providers, destination, native):
    """Copy immutable owners, preserving file types and local source topology."""
    owners = [Path(source_root).resolve(), *[Path(p).resolve() for p in providers]]
    if len(set(owners)) != len(owners):
        raise ValueError('duplicate source owner')
    for i, owner in enumerate(owners):
        if not owner.is_dir():
            raise ValueError('source owner is not a directory')
        if any(within(owner, other) or within(other, owner) for other in owners[:i]):
            raise ValueError('overlapping source owners')
    project = Path(project).resolve()
    if not within(project, owners[0]):
        raise ValueError('project escapes source owner')
    provided = {}
    for owner in owners[1:]:
        declaration = yaml.safe_load((owner / 'pubspec.yaml').read_text())
        name = declaration.get('name') if isinstance(declaration, dict) else None
        if not isinstance(name, str) or name in provided:
            raise ValueError('invalid or duplicate provided native package name')
        provided[name] = owner
    copies = [Path(destination) / str(i) for i in range(len(owners))]

    def relocated(path):
        matches = [(owner, target) for owner, target in zip(owners, copies) if within(path, owner)]
        if len(matches) != 1:
            raise ValueError('path dependency escapes declared source owners: ' + str(path))
        owner, target = matches[0]
        return target / path.relative_to(owner)

    for owner, target in zip(owners, copies):
        # Reject escaping links before copying, including directory symlinks.
        for base, directories, files in os.walk(owner, followlinks=False):
            directories[:] = [name for name in directories if name not in {".git", ".dart_tool", ".pub-purifier"}]
            for name in [*directories, *files]:
                entry = Path(base) / name
                if entry.is_symlink() and not within(entry.resolve(strict=True), owner):
                    raise ValueError('symlink escapes source owner: ' + str(entry))
                if not entry.is_symlink() and not entry.is_dir() and not entry.is_file():
                    raise ValueError('unsupported source entry: ' + str(entry))
        shutil.copytree(owner, target, symlinks=True, ignore=shutil.ignore_patterns(".git", ".dart_tool", ".pub-purifier"))
        for base, directories, files in os.walk(target, followlinks=False):
            os.chmod(base, Path(base).stat().st_mode | 0o700)
            for name in [*directories, *files]:
                entry = Path(base) / name
                if entry.is_symlink():
                    source = owner / entry.relative_to(target)
                    link = os.readlink(source)
                    if os.path.isabs(link):
                        entry.unlink()
                        entry.symlink_to(relocated(source.resolve(strict=True)))
    overrides = {}
    for filename in ('pubspec.yaml','pubspec_overrides.yaml'):
        path=project/filename
        if path.exists():
            declaration=yaml.safe_load(path.read_text())
            if isinstance(declaration,dict):overrides.update(declaration.get('dependency_overrides',{}))
    pending=[project]
    visited=set()
    while pending:
        package=pending.pop()
        if package in visited:continue
        visited.add(package)
        owner,target=next((a,b) for a,b in zip(owners,copies) if within(package,a))
        for filename in ('pubspec.yaml','pubspec_overrides.yaml'):
            original=package/filename
            if filename=='pubspec_overrides.yaml' and package!=project:continue
            if not original.exists():
                if filename=='pubspec.yaml':raise ValueError('missing active native manifest')
                continue
            declaration=yaml.safe_load(original.read_text())
            if not isinstance(declaration,dict):raise ValueError('invalid native manifest')
            if 'workspace' in declaration or declaration.get('resolution')=='workspace':
                raise ValueError('Pub workspaces require a separate contract')
            changed=False
            sections=('dependencies','dev_dependencies','dependency_overrides') if package==project else ('dependencies',)
            for section in sections:
                entries=declaration.get(section,{})
                if not isinstance(entries,dict):raise ValueError('invalid dependency map')
                for name,spec in entries.items():
                    if section!='dependency_overrides' and name in overrides:continue
                    if not isinstance(spec,dict) or 'path' not in spec:continue
                    if not isinstance(spec['path'],str):raise ValueError('invalid native path dependency')
                    resolved=provided[name] if name in provided else (original.parent/spec['path']).resolve(strict=True)
                    selected=relocated(resolved)
                    pending.append(resolved)
                    spec['path']=os.path.relpath(selected,target/original.parent.relative_to(owner))
                    changed=True
            if changed:
                output=(target/original.relative_to(owner)).resolve(strict=True)
                mode=original.stat().st_mode & 0o777
                output.unlink()
                output.write_text(yaml.safe_dump(declaration,sort_keys=False))
                os.chmod(output,mode)
    staged = copies[0] / project.relative_to(owners[0])
    if Path(native).exists():
        output = staged / 'pubspec.lock'
        if output.exists():
            output.unlink()
        shutil.copyfile(native, output)
    return staged
