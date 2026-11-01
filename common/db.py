"""SQLite ownership boundary: each process opens ONLY its own service database.
JSON documents retain typed Pydantic contracts; SQLite supplies ACID writes,
unique expression indexes, WAL, and CHECK constraints. Money is integer paise.
"""
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

TABLES = {
    'auth': ['users', 'refresh_tokens'],
    'products': ['products', 'categories', 'recent_views'],
    'inventory': ['inventory', 'reservations', 'transactions'],
    'cart': ['carts', 'cart_items', 'wishlists'],
    'orders': ['orders', 'order_items', 'operations'],
    'payments': ['payments', 'refunds'],
    'notifications': ['notifications'],
    'reviews': ['reviews'],
    'coupons': ['coupons', 'redemptions'],
    'returns': ['returns', 'refund_records'],
    'analytics': ['projections'],
}


def uid():
    return uuid.uuid4().hex


class Store:
    def __init__(self, name, root=None):
        self.name = name
        root = Path(root or os.getenv('DATA_DIR', './data'))
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / f'{name}.sqlite3'
        with self.connect() as c:
            c.execute('PRAGMA journal_mode=WAL')
            for table in TABLES.get(name, []) + ['outbox', 'inbox', 'audit_logs', 'schema_migrations']:
                c.execute(f'''CREATE TABLE IF NOT EXISTS {table} (
                    id TEXT PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)),
                    created_at REAL NOT NULL, updated_at REAL NOT NULL)''')
                c.execute(f'CREATE INDEX IF NOT EXISTS {table}_updated ON {table}(updated_at)')
            if name == 'auth':
                c.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_email ON users(json_extract(data,'$.email'))")
                c.execute("CREATE UNIQUE INDEX IF NOT EXISTS refresh_hash ON refresh_tokens(json_extract(data,'$.digest'))")
            if name == 'orders':
                c.execute("CREATE UNIQUE INDEX IF NOT EXISTS order_key ON orders(json_extract(data,'$.user_id'),json_extract(data,'$.idempotency_key'))")
            if name == 'payments':
                c.execute("CREATE UNIQUE INDEX IF NOT EXISTS pay_order ON payments(json_extract(data,'$.order_id'))")
            if name == 'reviews':
                c.execute("CREATE UNIQUE INDEX IF NOT EXISTS review_owner_product ON reviews(json_extract(data,'$.user_id'),json_extract(data,'$.product_id'))")
            if name == 'inventory':
                c.execute("CREATE UNIQUE INDEX IF NOT EXISTS reservation_order ON reservations(json_extract(data,'$.order_id'))")
            self.put(c, 'schema_migrations', '1', {'version': 1, 'description': 'Initial service-owned schema'})

    def connect(self):
        c = sqlite3.connect(self.path, timeout=20, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA busy_timeout=20000')
        return c

    @contextmanager
    def tx(self):
        c = self.connect()
        c.execute('BEGIN IMMEDIATE')
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def get(self, table, id, c=None):
        if c is None:
            with self.connect() as conn:
                return self.get(table, id, conn)
        r = c.execute(f'SELECT data FROM {table} WHERE id=?', (str(id),)).fetchone()
        return json.loads(r[0]) if r else None

    def all(self, table, c=None):
        if c is None:
            with self.connect() as conn:
                return self.all(table, conn)
        return [json.loads(r[0]) for r in c.execute(f'SELECT data FROM {table} ORDER BY created_at DESC')]

    def put(self, c, table, id, value):
        value = dict(value, id=str(id))
        now = time.time()
        value.setdefault('created_at', now)
        value['updated_at'] = now
        c.execute(f'''INSERT INTO {table} VALUES (?,?,?,?) ON CONFLICT(id)
            DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at''',
                  (str(id), json.dumps(value, allow_nan=False), value['created_at'], now))
        return value

    def delete(self, c, table, id):
        c.execute(f'DELETE FROM {table} WHERE id=?', (str(id),))

    def emit(self, c, kind, payload):
        event = {'event_id': uid(), 'type': kind, 'payload': payload, 'source': self.name,
                 'timestamp': time.time(), 'attempt': 0}
        self.put(c, 'outbox', event['event_id'], dict(event, published=False))
        return event

    def audit(self, c, actor, action, target):
        self.put(c, 'audit_logs', uid(), {'actor': actor, 'action': action, 'target': str(target)})
