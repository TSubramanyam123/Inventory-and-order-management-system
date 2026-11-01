import httpx
r=httpx.get('http://localhost:8000/health/dependencies',timeout=45)
print(r.json())
r.raise_for_status()
