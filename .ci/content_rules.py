# -*- coding: utf-8 -*-
"""NetEase submission content checks over the exact archived file mapping."""
from __future__ import print_function

import ast
import re

REPEATED = re.compile(r'(.)\1{5,}')
NUMERIC_SUFFIX = re.compile(r':([+-]?[0-9]+)$')
AUDIO_SUFFIXES = ('.wav', '.mp3', '.flac', '.aac', '.m4a', '.wma', '.aiff',
                  '.aif', '.opus', '.ogg')


def check(files, packs, config, error, warning, parse_json):
    """Report errors through error(path, message, line=1); warnings take text.

    A structures path is interpreted conservatively: at most two components
    after structures/, including the filename (structures/group/file is valid).
    Directory presence can only be inferred from archived files, so a missing
    required folder produces a warning rather than rejecting an empty folder.
    """
    manifests = {}
    for pack in packs:
        for basename in ('manifest.json', 'pack_manifest.json'):
            path = pack + '/' + basename
            if path not in files:
                continue
            try:
                manifests[pack] = parse_json(files[path])
            except (ValueError, TypeError):
                # The main manifest checker owns malformed manifest messages.
                continue
            break

    for pack, manifest in manifests.items():
        prefix = pack + '/'
        relative = [path[len(prefix):] for path in files if path.startswith(prefix)]
        types = set(module.get('type') for module in manifest.get('modules', []))
        has = lambda folder: any(path.startswith(folder + '/') for path in relative)
        if 'resources' in types:
            if not has('textures') and not has('shaders') and not has('shader'):
                warning(pack + ': resource pack has no archived textures/shader files; '
                        'required directories may be empty and absent from ZIP entries')
            if has('entities'):
                error(pack, 'Resource pack contains behavior-only entities/ directory')
        if 'data' in types and not has('entities'):
            warning(pack + ': behavior pack has no archived entities files; '
                    'required directory may be empty and absent from ZIP entries')
        if not config.get('allow_sapi', False):
            if types.intersection(('script', 'javascript')) or any(
                    dependency.get('module_name', '').startswith('@minecraft/')
                    for dependency in manifest.get('dependencies', [])):
                error(pack, 'Code 43: Script API modules/dependencies require allow_sapi=true')

    for path, data in sorted(files.items()):
        basename = path.rsplit('/', 1)[-1]
        if REPEATED.search(basename):
            error(path, 'Code 35: filename contains more than five identical consecutive characters')
        for pack in packs:
            prefix = pack + '/structures/'
            if path.startswith(prefix) and len(path[len(prefix):].split('/')) > 2:
                error(path, 'Structure path exceeds two components after structures/ '
                      '(including filename)')
            pack_manifest = manifests.get(pack, {})
            is_resource = any(module.get('type') == 'resources'
                              for module in pack_manifest.get('modules', []))
            if is_resource and path.startswith(pack + '/sounds/'):
                lower = path.lower()
                if lower.endswith(AUDIO_SUFFIXES) and not lower.endswith('.ogg'):
                    error(path, 'Code 33: sound audio must use OGG format')
        if path.lower().endswith('.py'):
            check_identifiers(path, data, error)
        if path.lower().endswith('.json'):
            try:
                document = parse_json(data, comments=True)
            except (ValueError, TypeError):
                continue
            check_numeric_keys(path, document, error)
            if basename.lower() == 'player.entity.json':
                check_player_controllers(path, document, error)


def check_player_controllers(path, document, error):
    required = {
        'controller.render.player.first_person': 'variable.is_first_person',
        'controller.render.player.third_person':
            '!variable.is_first_person && !variable.map_face_icon',
        'controller.render.player.first_person_bloom': 'variable.is_first_person',
        'controller.render.player.third_person_bloom':
            '!variable.is_first_person && !variable.map_face_icon',
    }
    if not isinstance(document, dict):
        error(path, 'Player entity definition must be a JSON object')
        return
    entity = document.get('minecraft:client_entity', {})
    if not isinstance(entity, dict) or not isinstance(entity.get('description', {}), dict):
        error(path, 'Player entity requires a client entity description object')
        return
    controllers = entity.get('description', {}).get('render_controllers', [])
    if not isinstance(controllers, list):
        error(path, 'Player render_controllers must be an array')
        return
    entries = {}
    for controller in controllers:
        if isinstance(controller, dict):
            entries.update(controller)
    for name, condition in sorted(required.items()):
        actual = entries.get(name)
        # Whitespace around Molang operators does not alter the expression.
        if not isinstance(actual, basestring) or re.sub(r'\s+', '', actual) != re.sub(r'\s+', '', condition):
            error(path, 'Player render_controllers requires %s: %s' % (name, condition))


def check_identifiers(path, data, error):
    try:
        tree = ast.parse(data, filename=path)
    except SyntaxError:
        return
    seen = set()
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.append(node.name)
        elif isinstance(node, ast.Attribute):
            names.append(node.attr)
        elif isinstance(node, ast.alias):
            names.extend((node.name.split('.')[-1], node.asname))
        elif isinstance(node, ast.arguments):
            names.extend((node.vararg, node.kwarg))
        for name in names:
            if name and REPEATED.search(name):
                line = getattr(node, 'lineno', 1)
                if (line, name) not in seen:
                    error(path, 'Code 35: Python identifier has more than five '
                          'identical consecutive characters: ' + name, line)
                    seen.add((line, name))


def check_numeric_keys(path, value, error):
    if isinstance(value, dict):
        for key, child in value.items():
            match = NUMERIC_SUFFIX.search(key)
            if match and not -2147483648 <= int(match.group(1)) <= 2147483647:
                error(path, 'Code 40: JSON key numeric suffix exceeds signed Int32: ' + key)
            check_numeric_keys(path, child, error)
    elif isinstance(value, list):
        for child in value:
            check_numeric_keys(path, child, error)
