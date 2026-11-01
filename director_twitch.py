"""Read-chat-only interactive receiver for the expanded director approval inbox."""
import argparse
import asyncio
import getpass
import json
from pathlib import Path
import re
import sys
import warnings

import twitch_eventsub as twitch
from director_chat import QueueSink, run as queue_run


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # Do not echo unknown arguments, config values or possibly pasted secrets.
        raise ValueError('Invalid launcher arguments')


def _interactive_terminal():
    return sys.stdin.isatty() and sys.stderr.isatty()


def _config(path):
    return public_config(json.loads(Path(path).read_text()))


def public_client_id(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9]{1,128}',value):
        raise ValueError('Invalid public client ID')
    return value


def public_config(value):
    """Shared public launcher identifiers; never a secret-bearing configuration."""
    allowed = {'client_id', 'broadcaster_user_id', 'reader_user_id', 'rewards'}
    if not isinstance(value, dict) or set(value)-allowed:
        raise ValueError('Use public identifiers only')
    public_client_id(value.get('client_id'))
    for key in ('broadcaster_user_id', 'reader_user_id'):
        if not isinstance(value.get(key), str) or not re.fullmatch(r'[0-9]{1,32}', value[key]):
            raise ValueError('Use numeric user identities')
    if 'rewards' in value and (not isinstance(value['rewards'], dict) or value['rewards']):
        raise ValueError('This launcher supports read-chat only; rewards must be empty')
    return twitch.Config(**{**value, 'rewards': {}})


def main(argv=None):
    token = None
    try:
        parser = _Parser(description='Expanded director operator-approved Twitch requests; dry-run unless --live.')
        parser.add_argument('--config', required=True, help='Token-free JSON with public Twitch identifiers')
        parser.add_argument('--port', type=int, default=8880, help='Expanded director loopback HTTP port')
        parser.add_argument('--live', action='store_true', help='Connect to Twitch after a TTY-only secret prompt')
        parser.add_argument('--enable-events', action='store_true', help='Permit validated chat request queueing during this live session')
        parser.add_argument('--enable-local-director-polls',action='store_true',help='DEFAULT OFF: route exact !vote 1..6 to an operator-enabled taken local poll, never native Twitch Polls')
        args = parser.parse_args(argv)
        cfg = _config(args.config)
        sink = QueueSink(args.port,enable_local_director_polls=args.enable_local_director_polls)  # Constructor validates the port; does not connect.
        if not args.live:
            print(json.dumps({'dry_run': True, 'enabled': False, 'local_director_polls':args.enable_local_director_polls, 'types': cfg.types(), 'director': sink.url}))
            return 0
        if not _interactive_terminal():
            print('Live input requires an interactive TTY; no secret was requested.', file=sys.stderr)
            return 2
        # getpass may fall back to echoed stdin if /dev/tty becomes unavailable.
        # Treat that warning as failure before its fallback can read anything.
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            token = getpass.getpass('Twitch user access token (memory only): ')
        if not token or token != token.strip() or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise ValueError('Invalid secret input')
        # No transport trace/result reason is printed: external errors may contain secrets.
        asyncio.run(queue_run(cfg, twitch.LIVE, lambda: token, sink,
                               enabled=args.enable_events, log=lambda _entry: None))
        print('Twitch session ended. No transport diagnostics displayed; no live acceptance implied.')
        return 0
    except KeyboardInterrupt:
        print('Twitch launcher interrupted.', file=sys.stderr)
        return 130
    except Exception:
        print('Twitch launcher could not complete. Check public configuration, terminal and service availability; details withheld.', file=sys.stderr)
        return 2
    finally:
        token = None  # No file/environment/config persistence; not a secure-erasure guarantee.


if __name__ == '__main__':
    raise SystemExit(main())
