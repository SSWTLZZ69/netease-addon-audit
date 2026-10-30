#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build or inspect a submission ZIP and check known NetEase rejection rules.

Run with Python 2.7 so syntax parsing matches the game's script language.
"""
from __future__ import print_function

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import tokenize
import StringIO
import sys
import uuid
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ERRORS = []
WARNINGS = []


def error(path, message, line=1):
    ERRORS.append({'path': path, 'line': line, 'message': message})
    print('ERROR {0}:{1}: {2}'.format(path, line, message))


def warning(message):
    WARNINGS.append(message)
    print('WARNING ' + message)


def strict_json(data, comments=False):
    def invalid_constant(value):
        raise ValueError('Non-JSON constant: ' + value)
    text = data.decode('utf-8-sig')
    if comments:
        # Preserve strings and line positions; JSONC comments are allowed by
        # Minecraft content files. Trailing commas remain errors.
        pattern = r'"(?:\\.|[^"\\])*"|//[^\r\n]*|/\*[\s\S]*?\*/'
        text = re.sub(pattern, lambda match: match.group(0) if match.group(0).startswith('"')
                      else re.sub(r'[^\r\n]', ' ', match.group(0)), text)
    return json.loads(text, parse_constant=invalid_constant)


def read_zip(path):
    files = {}
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            name = info.filename
            parts = name.split('/')
            if (name.startswith('/') or '\\' in name or ':' in name or
                    '..' in parts or '.' in parts or '' in parts[:-1]):
                error(path, 'Unsafe ZIP entry: ' + name)
                continue
            if name.endswith('/'):
                continue
            if name in files:
                error(path, 'Duplicate ZIP entry: ' + name)
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                error(path, 'Symbolic link in ZIP: ' + name)
            files[name] = archive.read(info)
    return files


def discover_packs(names):
    return sorted(set(name.rsplit('/', 1)[0] for name in names
                      if '/' in name and name.rsplit('/', 1)[1] in
                      ('manifest.json', 'pack_manifest.json')))


def build_zip(source, packs, path):
    names = subprocess.check_output(['git', 'ls-files', '-z', '--'],
                                    cwd=source).decode('utf-8').split('\0')
    if not packs:
        packs = discover_packs(names)
    destination = os.path.abspath(path)
    if any(os.path.abspath(os.path.join(source, name)) == destination
           for name in names if name):
        raise ValueError('Output ZIP would overwrite a tracked source file')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(filter(None, names)):
            if not any(name.startswith(pack + '/') for pack in packs):
                continue
            full = os.path.join(source, name)
            if os.path.islink(full):
                error(name, 'Symbolic links cannot be submitted')
                continue
            archive.write(full, name)
    return packs


def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = dotted(node.value)
        if parent:
            return parent + '.' + node.attr
    return None


def check_python(path, data, blocked):
    try:
        tree = ast.parse(data, filename=path)
    except SyntaxError as exc:
        error(path, str(exc), exc.lineno or 1)
        return
    for token in tokenize.generate_tokens(StringIO.StringIO(data).readline):
        if token[0] == tokenize.COMMENT and re.search(
                r'pylint\s*:\s*.*\b(disable|skip-file)\b', token[1], re.I):
            error(path, 'Pylint suppression prevents complete preflight analysis', token[2][0])
    # Collect every import, including function-local imports. Multiple bindings
    # are retained so an alias in one scope cannot hide a forbidden import.
    aliases = {}
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                local = item.asname or item.name.split('.')[0]
                target = item.name if item.asname else local
                aliases.setdefault(local, set()).add(target)
                imports.append((item.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ''
            for item in node.names:
                target = module + '.' + item.name
                aliases.setdefault(item.asname or item.name, set()).add(target)
                imports.append((target, node.lineno))
    uses = list(imports)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Name, ast.Attribute)):
            continue
        name = dotted(node)
        if name:
            head, separator, tail = name.partition('.')
            for target in aliases.get(head, ()):
                uses.append((target + (separator + tail if separator else ''),
                             node.lineno))
    reported = set()
    for name, line in uses:
        for rule in blocked:
            if (name == rule or name.startswith(rule + '.')) and (line, rule) not in reported:
                error(path, 'Known blocked Python API: ' + rule, line)
                reported.add((line, rule))


def version(value, path):
    if not isinstance(value, list) or len(value) != 3 or any(
            type(part) is not int or part < 0 for part in value):
        error(path, 'Version must be three non-negative integers')
        return None
    return tuple(value)


def manifests(files, packs):
    result = {}
    identities = {}
    for pack in packs:
        paths = [pack + '/' + name for name in ('manifest.json', 'pack_manifest.json')
                 if pack + '/' + name in files]
        if not paths:
            error(pack, 'Missing manifest.json / pack_manifest.json')
            continue
        first = None
        for path in paths:
            try:
                doc = strict_json(files[path])
                header = doc['header']
                identity = str(uuid.UUID(header['uuid']))
                current = version(header['version'], path)
                minimum = version(header['min_engine_version'], path)
                if minimum is not None and minimum < (1, 18, 0):
                    error(path, 'Minimum engine version must be at least 1.18.0 (code 37)')
                if not doc['modules']:
                    error(path, 'Manifest modules must not be empty')
                for module in doc['modules']:
                    if module['type'] not in ('data', 'resources', 'script', 'javascript', 'client_data'):
                        error(path, 'Unknown manifest module type: ' + module['type'])
                entries = [('header', identity)]
                for index, module in enumerate(doc['modules']):
                    entries.append(('module-' + str(index), module['uuid']))
                    version(module['version'], path)
                for kind, value in entries:
                    value = str(uuid.UUID(value))
                    previous = identities.get(value)
                    owner = (pack, kind)
                    if previous is not None and previous != owner:
                        error(path, 'UUID collision: ' + value)
                    identities[value.lower()] = owner
                if first is not None and doc != first:
                    error(path, 'manifest.json and pack_manifest.json disagree')
                first = doc
                result[pack] = {'uuid': identity.lower(), 'version': current,
                                'manifest': doc}
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                error(path, 'Invalid manifest: ' + str(exc))
    # A dependency UUID can refer to a declared external pack. Check versions
    # for local targets, and report external dependencies explicitly.
    headers = dict((item['uuid'], item) for item in result.values())
    for pack, item in result.items():
        for dependency in item['manifest'].get('dependencies', []):
            if 'uuid' not in dependency:
                continue
            try:
                target = headers.get(str(uuid.UUID(dependency['uuid'])))
                required = version(dependency['version'], pack + '/manifest.json')
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                error(pack, 'Invalid manifest dependency: ' + str(exc))
                continue
            if target is None:
                warning('External dependency requires separate review input: ' + dependency['uuid'])
            elif required != target['version']:
                error(pack, 'Local dependency version does not match: ' + dependency['uuid'])
    return result


def fingerprint(files, pack):
    digest = hashlib.sha256()
    prefix = pack + '/'
    for name in sorted(files):
        if name.startswith(prefix):
            digest.update(name[len(prefix):].encode('utf-8'))
            digest.update(b'\0')
            digest.update(hashlib.sha256(files[name]).digest())
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='.', help='Git project to package (tracked files only)')
    parser.add_argument('--config', help='JSON rules file; defaults to bundled conservative rules')
    parser.add_argument('--require-baseline', action='store_true', help='Fail if no accepted ZIP is provided')
    parser.add_argument('--artifact', help='Inspect this existing submission ZIP instead of building')
    parser.add_argument('--baseline', help='Previous accepted ZIP for this same work ID')
    parser.add_argument('--output', default='out/audit')
    args = parser.parse_args()
    if sys.version_info[:2] != (2, 7):
        parser.error('Run this checker with Python 2.7 (including AST syntax checks)')
    args.output = os.path.abspath(args.output)
    if not os.path.isdir(args.output):
        os.makedirs(args.output)
    payload = os.path.join(args.output, 'payload')
    if os.path.exists(payload):
        parser.error('Output payload already exists; use a fresh output directory')
    with open(args.config or os.path.join(ROOT, '.ci', 'audit.json'), 'rb') as stream:
        config = strict_json(stream.read())
    packs = config['packs']
    artifact = args.artifact or os.path.join(args.output, 'submission.zip')
    if not args.artifact:
        packs = build_zip(os.path.abspath(args.source), packs, artifact)
    files = read_zip(artifact)
    if not packs:
        packs = discover_packs(files)
    if not packs:
        error(artifact, 'No pack manifests found')
    for pack in packs:
        if (not pack or pack.startswith('/') or '\\' in pack or ':' in pack or
                any(part in ('', '.', '..') for part in pack.split('/'))):
            parser.error('Unsafe configured pack path: ' + pack)
    os.makedirs(payload)
    for name, data in files.items():
        destination = os.path.join(payload, *name.split('/'))
        parent = os.path.dirname(destination)
        if not os.path.isdir(parent):
            os.makedirs(parent)
        with open(destination, 'wb') as stream:
            stream.write(data)
    lowered = {}
    counts = {'files': len(files), 'json': 0, 'python': 0}
    for path, data in sorted(files.items()):
        if not any(path.startswith(pack + '/') for pack in packs):
            error(path, 'Unexpected file outside configured pack roots')
        if path.lower() in lowered:
            error(path, 'Case-insensitive path collision with ' + lowered[path.lower()])
        lowered[path.lower()] = path
        if any(path.lower().endswith(suffix) for suffix in config['blocked_suffixes']):
            error(path, 'Blocked submission file extension')
        if path.lower().endswith('.json'):
            counts['json'] += 1
            try:
                strict_json(data, comments=config['allow_json_comments'])
            except (ValueError, UnicodeError) as exc:
                line_match = re.search(r'line (\d+)', str(exc))
                error(path, 'Invalid JSON: ' + str(exc),
                      int(line_match.group(1)) if line_match else 1)
        if path.lower().endswith('.py'):
            counts['python'] += 1
            check_python(path, data, config['blocked_python'])
    current = manifests(files, packs)
    from content_rules import check as check_content
    from media_rules import check as check_media
    check_content(files, current, config, error, warning, strict_json)
    counts.update(check_media(files, current, config, error, warning))
    for path in files:
        try:
            path.encode('ascii')
        except UnicodeEncodeError:
            error(path, 'Non-ASCII submission path may be rejected (code 16)')
        if config['max_path_bytes'] is not None and len(path.encode('utf-8')) > config['max_path_bytes']:
            error(path, 'Path exceeds configured byte limit (local policy, code 27 risk)')
        if any(part in ('level.dat', 'level.dat_old', 'levelname.txt', 'db') for part in path.split('/')):
            error(path, 'Addon contains world data (code 13)')
    if args.baseline:
        old_files = read_zip(args.baseline)
        old = manifests(old_files, discover_packs(old_files))
        by_uuid = dict((item['uuid'], (pack, item)) for pack, item in old.items())
        for pack, item in current.items():
            previous_pair = by_uuid.get(item['uuid'])
            previous = previous_pair[1] if previous_pair else None
            if previous is None:
                error(pack, 'Baseline is missing this pack; verify work ID and package layout')
            elif item['uuid'] != previous['uuid']:
                error(pack, 'Pack identity changed from baseline; verify intentional new work identity')
            elif item['version'] is not None and previous['version'] is not None:
                changed = fingerprint(files, pack) != fingerprint(old_files, previous_pair[0])
                if item['version'] < previous['version'] or (changed and item['version'] <= previous['version']):
                    error(pack, 'Content/version regression: old={0}, new={1}, changed={2}'.format(
                        previous['version'], item['version'], changed))
    else:
        message = 'No accepted baseline supplied: error 42 and historical UUID ownership NOT checked'
        if args.require_baseline:
            error(artifact, message)
        else:
            warning(message)
    report = {'artifact': artifact, 'counts': counts, 'errors': ERRORS,
              'warnings': WARNINGS, 'baseline': args.baseline,
              'packs': dict((pack, {'uuid': item['uuid'], 'version': item['version'],
                                   'sha256': fingerprint(files, pack)})
                            for pack, item in current.items())}
    with open(os.path.join(args.output, 'report.json'), 'w') as stream:
        json.dump(report, stream, ensure_ascii=True, indent=2)
    print('Scanned {0}; errors={1}; warnings={2}'.format(counts, len(ERRORS), len(WARNINGS)))
    return 1 if ERRORS else 0


if __name__ == '__main__':
    sys.exit(main())
