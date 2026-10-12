#!/usr/bin/env python3
"""Private, self-contained MySQL + media + service backup. Run as root."""
import hashlib,json,os,subprocess,tarfile,time,tempfile
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlparse,unquote
BASE=Path('/www/forme-service')
DEST=Path('/www/backup/database/forme_production')
DEST.mkdir(parents=True,exist_ok=True);DEST.chmod(0o700)
config=json.loads((BASE/'config.json').read_text()); url=urlparse(config['database_url'])
stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');name='forme-'+stamp
work=DEST/(name+'.working');work.mkdir(mode=0o700)
os.umask(0o077)
# Credential options live in an ephemeral root-only file, never in process arguments or logs.
options=work/'client.cnf'
options.write_text('[client]\nuser='+unquote(url.username)+'\npassword='+unquote(url.password)+'\nhost=127.0.0.1\n')
options.chmod(0o600)
try:
    with (work/'database.sql').open('wb') as f:
        subprocess.run(['mysqldump','--defaults-extra-file='+str(options),'--single-transaction','--quick','--no-tablespaces','--set-gtid-purged=OFF','--skip-lock-tables',url.path.lstrip('/')],stdout=f,check=True)
finally: options.unlink(missing_ok=True)
manifest={'created_utc':datetime.now(timezone.utc).isoformat(),'database':'forme_production','schema_version':'2026.10.12','media_hashes':{},'database_sha256':hashlib.sha256((work/'database.sql').read_bytes()).hexdigest()}
for path in (BASE/'private-data').glob('*'):
    if path.is_file() and not path.name.endswith('.part'):
        h=hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda:f.read(1024**2),b''):h.update(chunk)
        manifest['media_hashes'][path.name]=h.hexdigest()
(work/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
archive=DEST/(name+'.tar.gz.part')
with tarfile.open(archive,'w:gz') as tar:
    tar.add(work/'database.sql',arcname='database.sql');tar.add(work/'manifest.json',arcname='manifest.json')
    for path in (BASE/'private-data').glob('*'):
        if path.name in manifest['media_hashes']:tar.add(path,arcname='private-data/'+path.name)
    for file in ['app.py','requirements.txt','config.json','backup.py']:
        tar.add(BASE/file,arcname='service/'+file)
archive.rename(DEST/(name+'.tar.gz'))
# Keep all completed copies. Retention is deliberately manual to avoid deleting user data.
import shutil
shutil.rmtree(work)
print('BACKUP_OK',name+'.tar.gz', 'media_files='+str(len(manifest['media_hashes'])))
