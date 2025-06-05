import aiosqlite
from config import TokenConfig

class DatabaseManager:
    def __init__(self, db_path):
        self.db_path = db_path

    async def init_db(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS wallets (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    balance REAL NOT NULL DEFAULT 0.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    sender_id INTEGER,
                    receiver_id INTEGER,
                    amount REAL NOT NULL,
                    description TEXT
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS token_info (
                    id INTEGER PRIMARY KEY DEFAULT 1,
                    current_price REAL NOT NULL,
                    total_supply REAL NOT NULL,
                    name TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    decimals INTEGER NOT NULL
                )
            ''')
            await db.execute('''
                INSERT OR IGNORE INTO token_info (id, current_price, total_supply, name, symbol, decimals)
                VALUES (1, ?, ?, ?, ?, ?)
            ''', (TokenConfig.INITIAL_PRICE, TokenConfig.TOTAL_SUPPLY, TokenConfig.NAME, TokenConfig.SYMBOL, TokenConfig.DECIMALS))
            await db.commit()

    async def execute_query(self, query, params=None):
        params = params or ()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(query, params)
            await db.commit()

    async def fetch_one(self, query, params=None):
        params = params or ()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            return await cursor.fetchone()

    async def fetch_all(self, query, params=None):
        params = params or ()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            return await cursor.fetchall()
