import aiosqlite
import logging # Added
from config import TokenConfig

class DatabaseManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self.logger = logging.getLogger(self.__class__.__name__) # Added logger
        self.logger.info(f"DatabaseManager initialized with db_path: {db_path}")

    async def init_db(self):
        """Initializes the database and creates tables if they don't exist."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Wallets Table
                await db.execute('''
                    CREATE TABLE IF NOT EXISTS wallets (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT,
                        balance REAL NOT NULL DEFAULT 0.0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                # Transactions Table
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
                # Token Info Table
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
                # Stakes Table
                await db.execute('''
                    CREATE TABLE IF NOT EXISTS stakes (
                        stake_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        amount REAL NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_claimed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(user_id) REFERENCES wallets(user_id)
                    )
                ''')
                # Active Boosters Table
                await db.execute('''
                    CREATE TABLE IF NOT EXISTS active_boosters (
                        booster_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        booster_type TEXT NOT NULL,
                        active_until TIMESTAMP,
                        effect_multiplier REAL NOT NULL,
                        FOREIGN KEY(user_id) REFERENCES wallets(user_id)
                    )
                ''')
                # Initial Token Data
                await db.execute('''
                    INSERT OR IGNORE INTO token_info (id, current_price, total_supply, name, symbol, decimals)
                    VALUES (1, ?, ?, ?, ?, ?)
                ''', (TokenConfig.INITIAL_PRICE, TokenConfig.TOTAL_SUPPLY, TokenConfig.NAME, TokenConfig.SYMBOL, TokenConfig.DECIMALS))

                await db.commit()
                self.logger.info("Database initialized successfully.")
        except aiosqlite.Error as e:
            self.logger.error(f"Database error in init_db: {e}", exc_info=True)
            # Depending on desired behavior, might re-raise or handle differently

    async def execute_query(self, query, params=None) -> bool:
        """Executes a given SQL query (INSERT, UPDATE, DELETE). Returns True on success, False on failure."""
        params = params or ()
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(query, params)
                await db.commit()
                # self.logger.debug(f"Executed query: {query} with params: {params}") # Optional: for verbose logging
                return True
        except aiosqlite.Error as e:
            self.logger.error(f"Database error in execute_query ('{query[:50]}...'): {e}", exc_info=True)
            return False

    async def fetch_one(self, query, params=None):
        """Fetches a single row from the database. Returns a Row object or None."""
        params = params or ()
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(query, params)
                # self.logger.debug(f"Fetched one: {query} with params: {params}") # Optional
                return await cursor.fetchone()
        except aiosqlite.Error as e:
            self.logger.error(f"Database error in fetch_one ('{query[:50]}...'): {e}", exc_info=True)
            return None

    async def fetch_all(self, query, params=None):
        """Fetches all rows from the database for a given query. Returns a list of Row objects or None."""
        params = params or ()
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(query, params)
                # self.logger.debug(f"Fetched all: {query} with params: {params}") # Optional
                return await cursor.fetchall()
        except aiosqlite.Error as e:
            self.logger.error(f"Database error in fetch_all ('{query[:50]}...'): {e}", exc_info=True)
            return None
