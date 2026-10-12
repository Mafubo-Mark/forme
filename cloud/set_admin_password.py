#!/usr/bin/env python3
"""Set a private admin password without putting plaintext in shell history."""
import getpass
import hashlib
import json
import os
import secrets
from pathlib import Path

path = Path(os.environ.get('FORME_CONFIG', '/www/forme-service/config.json'))
password = getpass.getpass('New Forme admin password: ')
confirm = getpass.getpass('Repeat password: ')
if password != confirm or len(password) < 16:
    raise SystemExit('Passwords must match and contain at least 16 characters')
salt = secrets.token_hex(16)
digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
with path.open('r+', encoding='utf-8') as handle:
    config = json.load(handle)
    config['admin_password_hash'] = f'scrypt$16384$8$1${salt}${digest}'
    handle.seek(0)
    json.dump(config, handle, indent=2)
    handle.truncate()
os.chmod(path, 0o600)
print('Admin password hash saved. Restart forme-cloud.service.')
