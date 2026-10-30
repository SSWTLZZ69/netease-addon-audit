# -*- coding: utf-8 -*-
"""Submission media checks from the public packaging error reference."""
import StringIO

from PIL import Image
from mutagen.oggvorbis import OggVorbis
from mutagen.oggopus import OggOpus
from mutagen import MutagenError


def check(files, packs, config, error, warning):
    image_count = 0
    audio_count = 0
    for path, data in sorted(files.items()):
        lower = path.lower()
        if lower.endswith('.png'):
            image_count += 1
            try:
                image = Image.open(StringIO.StringIO(data))
                image.load()
                limit = config['max_texture_pixels']
                if limit is not None and image.width * image.height > limit:
                    error(path, 'Texture exceeds configured pixel budget (local policy, code 26 risk)')
                if '/font/glyph_' in lower:
                    if image.size != (256, 256):
                        error(path, 'Bitmap font atlas must be 256x256 (code 34)')
                    if any(pixel[3] == 0 and pixel[:3] != (0, 0, 0)
                           for pixel in image.convert('RGBA').getdata()):
                        error(path, 'Transparent glyph pixels must have zero RGB channels (code 34)')
                if config['require_skin_alpha'] and '/skins/' in lower:
                    if 'A' not in image.getbands() and 'transparency' not in image.info:
                        error(path, 'Skin PNG must contain an alpha channel')
            except (IOError, ValueError, Image.DecompressionBombError) as exc:
                error(path, 'Unreadable PNG: ' + str(exc))
        if '/sounds/' not in lower:
            continue
        if lower.endswith('.ogg'):
            audio_count += 1
            try:
                if data.startswith(b'OggS') and b'OpusHead' in data[:128]:
                    info = OggOpus(StringIO.StringIO(data)).info
                else:
                    info = OggVorbis(StringIO.StringIO(data)).info
                bitrate = getattr(info, 'bitrate', None)
                if bitrate is None:
                    warning('Audio bitrate cannot be established: ' + path)
                elif bitrate > config['max_audio_bitrate']:
                    error(path, 'Audio bitrate exceeds configured maximum: {0} bps (code 33)'.format(bitrate))
                if not data.startswith(b'OggS'):
                    error(path, 'Invalid OGG container')
            except (MutagenError, IOError, ValueError) as exc:
                error(path, 'Unreadable OGG sound: ' + str(exc))
    return {'png': image_count, 'ogg': audio_count}
