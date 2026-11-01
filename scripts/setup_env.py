"""Create a private local .env without overwriting existing configuration."""
import secrets
from pathlib import Path
root=Path(__file__).resolve().parents[1]
path=root/'.env'
if path.exists():
    print('.env already exists. Keeping your configuration.')
else:
    content=(root/'.env.example').read_text()
    content=content.replace('replace-with-at-least-32-random-characters',secrets.token_urlsafe(48))
    content=content.replace('replace-with-a-different-32-character-secret',secrets.token_urlsafe(48))
    for role in ['ADMIN','MANAGER','CUSTOMER']:
        content=content.replace(f'{role}_PASSWORD=\n',f'{role}_PASSWORD={secrets.token_urlsafe(15)}\n')
    path.write_text(content)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    print('Created .env with random secrets. Demo emails and passwords are in .env.')
