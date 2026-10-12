#!/usr/bin/env python3
"""Deploy only Forme's named site and a new isolated database. Root on authorized server."""
import json,os,shutil,sqlite3,subprocess,sys,time,tarfile,secrets,hashlib
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import quote
import pymysql
SOURCE=Path(__file__).resolve().parent.parent
SITE=Path('/www/wwwroot/my-robot-home.com')
SERVICE=Path('/www/forme-service')
VHOST=Path('/www/server/panel/vhost/nginx/html_my-robot-home.com.conf')
PANEL=Path('/www/server/panel')
DBNAME='forme_production';DBUSER='forme_app'
STAMP=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
BACKUP=Path('/www/backup/forme-deployment')/STAMP
os.umask(0o077)
assert sys.version_info >= (3,11), 'PYTHON_3_11_REQUIRED'
assert subprocess.run(['python3','-c','import sys; assert sys.version_info >= (3,11)'],check=False).returncode==0, 'PYTHON_3_11_REQUIRED'
def run(args,**kwargs):return subprocess.run(args,check=True,**kwargs)
def log(value):print(value,flush=True)
assert SITE.is_dir() and VHOST.is_file(), 'TARGET_NOT_FOUND'
CERTDIR=Path('/www/server/panel/vhost/cert/my-robot-home.com')
assert (CERTDIR/'fullchain.pem').is_file() and (CERTDIR/'privkey.pem').is_file(), 'VALID_SITE_CERTIFICATE_REQUIRED_BEFORE_DEPLOYMENT'
assert not SERVICE.exists(), 'SERVICE_ALREADY_EXISTS_INSPECT_BEFORE_CONTINUING'
BACKUP.mkdir(parents=True)
with tarfile.open(BACKUP/'original-site.tar.gz','w:gz') as t:t.add(SITE,arcname='my-robot-home.com')
shutil.copy2(VHOST,BACKUP/'original-vhost.conf')
# Record hashes of other vhosts, so verification can prove they are unchanged.
other={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in VHOST.parent.glob('*.conf') if p!=VHOST}
(BACKUP/'other-vhost-hashes.json').write_text(json.dumps(other,indent=2))
log('TARGET_BACKUP_OK '+str(BACKUP))
# Public module opens the current panel database abstraction (modern panel uses split DBs).
proc=subprocess.run([str(PANEL/'pyenv/bin/python'),'-c',"import sys;sys.path.insert(0,'/www/server/panel/class');sys.path.insert(0,'/www/server/panel');import public;print(public.M('config').where('id=?',(1,)).getField('mysql_root'))"],cwd=PANEL,capture_output=True,text=True,check=True)
root_password=proc.stdout.strip()
assert root_password and root_password not in ('None','False'), 'PANEL_MYSQL_ROOT_NOT_AVAILABLE'
root=pymysql.connect(host='localhost',user='root',password=root_password,charset='utf8mb4',autocommit=True)
with root.cursor() as c:
    c.execute('SHOW DATABASES LIKE %s',(DBNAME,));assert not c.fetchone(),'DATABASE_ALREADY_EXISTS'
    c.execute('SELECT User,Host FROM mysql.user WHERE User=%s',(DBUSER,));assert not c.fetchone(),'DB_USER_ALREADY_EXISTS'
    dbpassword=secrets.token_urlsafe(32)
    c.execute('CREATE DATABASE `forme_production` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
    c.execute("CREATE USER 'forme_app'@'localhost' IDENTIFIED BY %s",(dbpassword,))
    c.execute("GRANT ALL PRIVILEGES ON `forme_production`.* TO 'forme_app'@'localhost'")
root.close();del root_password
SERVICE.mkdir(mode=0o750)
for file in ['app.py','requirements.txt','backup.py']:shutil.copy2(SOURCE/'cloud'/file,SERVICE/file)
(SERVICE/'private-data').mkdir(mode=0o700)
admin_password=secrets.token_urlsafe(24)
admin_salt=secrets.token_hex(16)
admin_hash='scrypt$16384$8$1$'+admin_salt+'$'+hashlib.scrypt(admin_password.encode(),salt=bytes.fromhex(admin_salt),n=16384,r=8,p=1).hex()
config={'database_url':'mysql+pymysql://forme_app:'+quote(dbpassword,safe='')+'@127.0.0.1/forme_production?charset=utf8mb4','data_dir':str(SERVICE/'private-data'),'secure_cookie':True,'origins':['https://my-robot-home.com','https://www.my-robot-home.com'],'worker_key':secrets.token_urlsafe(48),'admin_password_hash':admin_hash,'local_operator_token':secrets.token_urlsafe(48),'local_operator_url':'http://127.0.0.1:18001'}
(SERVICE/'config.json').write_text(json.dumps(config,indent=2));(SERVICE/'config.json').chmod(0o600)
# Register only this new database through the panel's own ORM; do not modify other rows.
register_code="""import sys,json,time
sys.path.insert(0,'/www/server/panel/class')
sys.path.insert(0,'/www/server/panel')
import public
v=json.load(sys.stdin)
m=public.M('databases')
assert not m.where('name=?',('forme_production',)).count()
print(m.add('pid,name,username,password,accept,ps,addtime',(2,'forme_production','forme_app',v['password'],'127.0.0.1','Forme - my-robot-home.com',time.strftime('%Y-%m-%d %H:%M:%S'))))
"""
run([str(PANEL/'pyenv/bin/python'),'-c',register_code],cwd=PANEL,input=json.dumps({'password':dbpassword}),text=True)
del dbpassword
run(['python3','-m','venv',str(SERVICE/'.venv')])
run([str(SERVICE/'.venv/bin/python'),'-c','import sys; assert sys.version_info >= (3, 11), "PYTHON_3_11_REQUIRED"'])
run([str(SERVICE/'.venv/bin/pip'),'install','-r',str(SERVICE/'requirements.txt')])
run(['chown','-R','www:www',str(SERVICE)])
Path('/root/forme-admin-initial-password').write_text(admin_password+'\n')
Path('/root/forme-admin-initial-password').chmod(0o600)
del admin_password
# Initialize once before starting multiple web workers.
run([str(SERVICE/'.venv/bin/python'),'-c','import app'],cwd=SERVICE,env={**os.environ,'FORME_CONFIG':str(SERVICE/'config.json')})
# Service metadata is private; only dist assets are published. Unknown old files remain on disk.
for source in (SOURCE/'dist').rglob('*'):
    if source.is_file():
        relative=source.relative_to(SOURCE/'dist');dest=SITE/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest);dest.chmod(0o644)
run(['chown','-R','www:www',str(SITE/'assets'),str(SITE/'css'),str(SITE/'js')])
unit='''[Unit]
Description=Forme cloud accounts designs and orders
After=network.target mysqld.service
[Service]
Type=simple
User=www
Group=www
WorkingDirectory=/www/forme-service
Environment=FORME_CONFIG=/www/forme-service/config.json
ExecStart=/www/forme-service/.venv/bin/uvicorn app:app --host 127.0.0.1 --port 18086 --workers 2 --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-access-log
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/www/forme-service/private-data
[Install]
WantedBy=multi-user.target
'''
Path('/etc/systemd/system/forme-cloud.service').write_text(unit)
Path('/etc/systemd/system/forme-backup.service').write_text('''[Unit]
Description=Forme MySQL and private uploads backup
[Service]
Type=oneshot
ExecStart=/www/forme-service/.venv/bin/python /www/forme-service/backup.py
UMask=0077
''')
Path('/etc/systemd/system/forme-backup.timer').write_text('''[Unit]
Description=Daily Forme database and media backup
[Timer]
OnCalendar=*-*-* 03:30:00 Asia/Shanghai
Persistent=true
[Install]
WantedBy=timers.target
''')
run(['systemctl','daemon-reload']);run(['systemctl','enable','--now','forme-cloud.service','forme-backup.timer'])
for _ in range(40):
    time.sleep(1)
    r=subprocess.run(['curl','-sf','http://127.0.0.1:18086/api/health'],capture_output=True,text=True)
    if r.returncode==0:break
else:raise RuntimeError('BACKEND_HEALTH_FAILED')
log('BACKEND_HEALTH_OK '+r.stdout)
# HTTP vhost is kept for challenge + redirects. Site TLS is a separate, site-specific file.
old=VHOST.read_text()
assert 'server_name my-robot-home.com' in old, 'UNEXPECTED_SITE_CONFIG'
http=f'''server {{
 listen 80;
 server_name my-robot-home.com www.my-robot-home.com;
 root /www/wwwroot/my-robot-home.com;
 location ^~ /.well-known/acme-challenge/ {{ try_files $uri =404; }}
 location / {{ return 301 https://my-robot-home.com$request_uri; }}
}}
'''
# TLS certificate is provisioned separately with explicit approval if ACME registration is needed.
certdir=Path('/www/server/panel/vhost/cert/my-robot-home.com')
assert (certdir/'fullchain.pem').is_file() and (certdir/'privkey.pem').is_file(),'VALID_SITE_CERTIFICATE_REQUIRED'
ssl=f'''server {{
 listen 443 ssl;
 server_name my-robot-home.com www.my-robot-home.com;
 root /www/wwwroot/my-robot-home.com;
 index index.html;
 ssl_certificate {certdir}/fullchain.pem;
 ssl_certificate_key {certdir}/privkey.pem;
 ssl_protocols TLSv1.2 TLSv1.3;
 client_max_body_size 520m;
 add_header X-Content-Type-Options nosniff always;
 add_header X-Frame-Options DENY always;
 add_header Referrer-Policy same-origin always;
 add_header Strict-Transport-Security "max-age=31536000" always;
 location = /admin {{ return 302 /admin.html; }}
 location ^~ /api/ {{
   proxy_pass http://127.0.0.1:18086;
   proxy_http_version 1.1;
   proxy_set_header Host $host;
   proxy_set_header X-Forwarded-For $remote_addr;
   proxy_set_header X-Forwarded-Proto $scheme;
   proxy_request_buffering off;
   proxy_read_timeout 600s;
   proxy_send_timeout 600s;
 }}
 location ~* ^/(server\\.py|output\\.log|stock\\.html|index2\\.html|cloud/|database/|deploy/|docs/|.*\\.(?:sql|tar|gz|zip|py|db)) {{ return 404; }}
 location ~ /\\.(?!well-known) {{ return 404; }}
 location = / {{ try_files /index.html =404; }}
 location / {{ try_files $uri $uri/ =404; }}
 location ~* \\.(js|css)$ {{ expires -1; }}
 access_log /www/wwwlogs/my-robot-home.com.log;
 error_log /www/wwwlogs/my-robot-home.com.error.log;
}}
'''
VHOST.write_text(http+'\n'+ssl)
try:run(['nginx','-t'])
except Exception:shutil.copy2(BACKUP/'original-vhost.conf',VHOST);raise
run(['nginx','-s','reload'])
run(['systemctl','start','forme-backup.service'])
assert all(Path(p).exists() and hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in other.items()), 'OTHER_VHOST_CHANGED'
log('DEPLOYMENT_OK site=https://my-robot-home.com database=forme_production backup='+str(BACKUP))
