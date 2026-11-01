"""Closed, data-only authoring schema for the expanded director."""
import copy
import math
import re

MODES = ('starting', 'live', 'brb', 'ending')
LAYOUTS = ('camera', 'content', 'pip', 'side-by-side')
MOTIONS = ('none', 'fade', 'rise', 'slide', 'pulse', 'orbit')
TEMPLATES = ('title', 'lower', 'burst', 'orbit', 'minimal')
BLUE = '#0047ff'


def obj(value, keys, required=()):
    if not isinstance(value, dict) or set(value) - set(keys) or set(required) - set(value):
        raise ValueError('Unknown or missing fields')
    return value


def text(value, limit=160, empty=True):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()) or any(ord(c) < 32 for c in value):
        raise ValueError(f'Use plain text up to {limit} characters')
    return value


def number(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'Number must be between {low} and {high}')
    return value


def choice(value, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise ValueError('Choose one of: ' + ', '.join(allowed))
    return value


def boolean(value):
    if type(value) is not bool:
        raise ValueError('Expected a boolean')
    return value


def color(value):
    if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
        raise ValueError('Color must be #RRGGBB')
    return value.lower()


def composition(value):
    obj(value, ('name', 'duration', 'repeat', 'elements'), ('elements',))
    result = {'name': text(value.get('name', 'Untitled'), 60),
              'duration': number(value.get('duration', 8), .3, 120),
              'repeat': number(value.get('repeat', 1), 1, 20), 'elements': []}
    if type(result['repeat']) is not int:
        raise ValueError('Repeat must be an integer')
    if not isinstance(value['elements'], list) or len(value['elements']) > 32:
        raise ValueError('Use at most 32 primitives')
    ids = set()
    for item in value['elements']:
        obj(item, ('id', 'kind', 'text', 'x', 'y', 'w', 'h', 'color', 'size', 'opacity', 'motion', 'start', 'end', 'radius'), ('id', 'kind'))
        ident = text(item['id'], 40, False)
        if not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_-]*', ident) or ident in ids:
            raise ValueError('Primitive IDs must be unique simple names')
        ids.add(ident)
        out = {'id': ident, 'kind': choice(item['kind'], ('text', 'rect', 'circle')),
               'text': text(item.get('text', '')), 'x': number(item.get('x', 0), 0, 1920),
               'y': number(item.get('y', 0), 0, 1080), 'w': number(item.get('w', 400), 1, 1920),
               'h': number(item.get('h', 100), 1, 1080), 'color': color(item.get('color', BLUE)),
               'size': number(item.get('size', 64), 12, 180), 'opacity': number(item.get('opacity', 1), 0, 1),
               'motion': choice(item.get('motion', 'fade'), MOTIONS),
               'start': number(item.get('start', 0), 0, result['duration']),
               'end': number(item.get('end', result['duration']), 0, result['duration']),
               'radius': number(item.get('radius', 0), 0, 200)}
        if out['end'] <= out['start']:
            raise ValueError('Primitive end must follow start')
        result['elements'].append(out)
    return result


def compose(title, subtitle='', template='title', accent=BLUE, motion='rise', duration=8):
    """Deterministic templates, never an LLM or executable output."""
    text(title); text(subtitle); choice(template, TEMPLATES); color(accent); choice(motion, MOTIONS)
    number(duration, .3, 120)
    bottom = template == 'lower'
    x, y = (100, 820) if bottom else (200, 380)
    elements = [dict(id='accent', kind='rect', x=x, y=y, w=12, h=140, color=accent, motion=motion),
                dict(id='title', kind='text', text=title, x=x+40, y=y, w=1500, h=100, color='#ffffff', size=82, motion=motion),
                dict(id='subtitle', kind='text', text=subtitle, x=x+42, y=y+100, w=1480, h=70, color='#ffffff', size=38, motion='fade')]
    if template in ('burst', 'orbit'):
        for i in range(12):
            angle = i * math.tau / 12
            elements.insert(0, dict(id=f'particle{i}', kind='circle', x=930+430*math.cos(angle),
                                   y=480+320*math.sin(angle), w=24+i*2, h=24+i*2, color=accent,
                                   opacity=.7, motion='orbit' if template == 'orbit' else 'pulse'))
    if template == 'minimal':
        elements = elements[1:]
    return composition({'name': title[:60], 'duration': duration, 'elements': elements})


def timer(value):
    obj(value, ('kind', 'seconds', 'label'), ('kind', 'seconds', 'label'))
    return {'kind': choice(value['kind'], ('countdown', 'elapsed')),
            'seconds': number(value['seconds'], 0, 86400), 'label': text(value['label'], 60)}


def vote(value):
    obj(value, ('question', 'options', 'kind'), ('question', 'options'))
    options = value['options']
    if not isinstance(options, list) or not 2 <= len(options) <= 6:
        raise ValueError('Use two to six options')
    options = [text(v, 60, False) for v in options]
    if len(set(options)) != len(options):
        raise ValueError('Vote options must differ')
    return {'question': text(value['question'], 120, False), 'options': options,
            'kind': choice(value.get('kind', 'vote'), ('vote', 'prediction'))}


def segment(value):
    obj(value, ('mode', 'layout', 'composition', 'lower', 'timer', 'vote', 'media', 'volume'), ('mode', 'layout', 'composition'))
    lower = value.get('lower')
    if lower is not None:
        obj(lower, ('title', 'subtitle'), ('title', 'subtitle'))
        lower = {k: text(lower[k]) for k in ('title', 'subtitle')}
    media = value.get('media')
    if media is not None:
        text(media, 100, False)
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_. -]{0,99}', media):
            raise ValueError('Choose an owned media filename')
    return {'mode': choice(value['mode'], MODES), 'layout': choice(value['layout'], LAYOUTS),
            'composition': composition(value['composition']), 'lower': lower,
            'timer': timer(value['timer']) if value.get('timer') is not None else None,
            'vote': vote(value['vote']) if value.get('vote') is not None else None,
            'media': media, 'volume': number(value.get('volume', .25), 0, .5)}


def default_segment():
    return segment({'mode': 'starting', 'layout': 'pip',
                    'composition': {'elements': []}})


def recipe(value):
    obj(value, ('name', 'steps'), ('name', 'steps'))
    name = text(value['name'], 60, False)
    if not isinstance(value['steps'], list) or not 1 <= len(value['steps']) <= 16:
        raise ValueError('Recipes contain one to sixteen operator-stepped segments')
    return {'name': name, 'steps': [segment(v) for v in value['steps']]}


def parse_operator(value):
    """Small documented grammar shared by typed and final local voice cues."""
    value = text(value, 400, False).strip()
    low = value.lower().rstrip('.!?')
    if low.startswith('director, '): low = low[len('director, '):]
    if low in ('undo that', 'undo camera layout'): return {'action': 'undo_camera_layout'}
    if low in ('restore segment', 'restore show', 'restore segment/show'): return {'action': 'restore'}
    if low in ('take', 'clear', 'restore', 'preview', 'pause', 'resume', 'timer pause', 'timer resume', 'timer reset', 'media stop'):
        if low in ('pause', 'resume'):
            return {'action': 'pause', 'paused': low == 'pause'}
        if low.startswith('timer '): return {'action': 'timer_control', 'operation': low.split()[1]}
        if low == 'media stop': return {'action': 'media_stop'}
        return {'action': low}
    if low in MODES: return {'action': 'scene', 'mode': low}
    if low in LAYOUTS: return {'action': 'scene', 'mode': 'live', 'layout': low}
    match = re.fullmatch(r'(starting|live|brb|ending) (obs|overlay)', low)
    if match: return {'action': 'scene', 'mode': match[1], 'target': match[2]}
    match = re.fullmatch(r'preview (obs|overlay)', low)
    if match: return {'action': 'preview', 'target': match[1]}
    for prefix, template in (('title ', 'title'), ('lower ', 'lower'), ('celebrate ', 'burst'), ('orbit ', 'orbit')):
        if value.lower().startswith(prefix):
            pieces = value[len(prefix):].split('|', 1)
            title = pieces[0].strip(); subtitle = pieces[1].strip() if len(pieces) == 2 else ''
            if template == 'lower':
                return {'action': 'stage_patch', 'fields': {'lower': {'title': text(title), 'subtitle': text(subtitle)}}}
            return {'action': 'compose', 'title': title, 'subtitle': subtitle, 'template': template}
    match = re.fullmatch(r'(countdown|elapsed) (\d{1,5})(?: (.+))?', value, re.I)
    if match:
        return {'action': 'stage_patch', 'fields': {'timer': timer({'kind': match[1].lower(), 'seconds': int(match[2]), 'label': match[3] or 'Timer'})}}
    raise ValueError('Use title TEXT | SUBTITLE, lower NAME | ROLE, celebrate TEXT, orbit TEXT, countdown SECONDS LABEL, a mode/layout, preview, take, restore, clear, pause or resume')


MODE_LOOKS = {
    'starting': {'title': 'Starting soon', 'subtitle': 'The stream will begin shortly', 'background': '#101010'},
    'brb': {'title': 'Be right back', 'subtitle': 'Taking a short break', 'background': '#101010'},
    'ending': {'title': 'Thanks for watching', 'subtitle': 'See you next time', 'background': '#101010'},
}

def mode_look(mode):
    """Persistent scene identity; independent of temporary composition lifetime."""
    choice(mode, MODES)
    return copy.deepcopy(MODE_LOOKS.get(mode))


def needs_graphics(segment):
    """Persistent mode bases and separate media never require a mutable bank."""
    return bool(segment['composition']['elements'] or any(segment[key] for key in ('lower', 'timer', 'vote')))
