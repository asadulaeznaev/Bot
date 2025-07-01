import aiosqlite
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union
from contextlib import asynccontextmanager
from dataclasses import asdict

from config import TokenConfig, PerformanceConfig
from models import CacheEntry

class ConnectionPool:
    """Пул соединений для оптимизации производительности"""
    
    def __init__(self, db_path: str, max_size: int = 20):
        self.db_path = db_path
        self.max_size = max_size
        self._pool: asyncio.Queue = asyncio.Queue(maxsize=max_size)
        self._created_connections = 0
        self.logger = logging.getLogger(self.__class__.__name__)
    
    async def init_pool(self):
        """Инициализирует пул соединений"""
        for _ in range(min(5, self.max_size)):  # Начальный размер пула
            conn = await self._create_connection()
            await self._pool.put(conn)
    
    async def _create_connection(self) -> aiosqlite.Connection:
        """Создает новое соединение с оптимизированными настройками"""
        conn = await aiosqlite.connect(self.db_path)
        conn.row_factory = aiosqlite.Row
        
        # Оптимизация производительности
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.execute("PRAGMA cache_size=10000")
        await conn.execute("PRAGMA temp_store=memory")
        await conn.execute("PRAGMA mmap_size=268435456")  # 256MB
        
        self._created_connections += 1
        self.logger.debug(f"Created connection #{self._created_connections}")
        return conn
    
    @asynccontextmanager
    async def get_connection(self):
        """Контекстный менеджер для получения соединения"""
        conn = None
        try:
            # Пытаемся взять соединение из пула
            try:
                conn = self._pool.get_nowait()
            except asyncio.QueueEmpty:
                # Создаем новое соединение если пул пуст
                if self._created_connections < self.max_size:
                    conn = await self._create_connection()
                else:
                    # Ждем освобождения соединения
                    conn = await self._pool.get()
            
            yield conn
        finally:
            if conn:
                try:
                    self._pool.put_nowait(conn)
                except asyncio.QueueFull:
                    await conn.close()
    
    async def close_all(self):
        """Закрывает все соединения"""
        while not self._pool.empty():
            conn = await self._pool.get()
            await conn.close()

class CacheManager:
    """Менеджер кэша для ускорения запросов"""
    
    def __init__(self, default_ttl: int = 300):
        self.cache: Dict[str, CacheEntry] = {}
        self.default_ttl = default_ttl
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def get(self, key: str) -> Optional[Any]:
        """Получает значение из кэша"""
        entry = self.cache.get(key)
        if entry and not entry.is_expired:
            self.logger.debug(f"Cache hit for key: {key}")
            return entry.value
        elif entry:
            # Удаляем устаревшую запись
            del self.cache[key]
        return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Устанавливает значение в кэш"""
        ttl = ttl or self.default_ttl
        entry = CacheEntry(
            key=key,
            value=value,
            created_at=datetime.now(),
            ttl=ttl
        )
        self.cache[key] = entry
        self.logger.debug(f"Cache set for key: {key}")
    
    def invalidate(self, pattern: str = None) -> None:
        """Инвалидирует кэш по паттерну"""
        if pattern:
            keys_to_remove = [k for k in self.cache.keys() if pattern in k]
            for key in keys_to_remove:
                del self.cache[key]
                self.logger.debug(f"Cache invalidated for key: {key}")
        else:
            self.cache.clear()
            self.logger.debug("Cache cleared completely")
    
    def cleanup_expired(self) -> None:
        """Очищает устаревшие записи"""
        expired_keys = [k for k, v in self.cache.items() if v.is_expired]
        for key in expired_keys:
            del self.cache[key]
        if expired_keys:
            self.logger.debug(f"Cleaned up {len(expired_keys)} expired cache entries")

class DatabaseManager:
    """Оптимизированный менеджер базы данных с пулом соединений и кэшированием"""
    
    def __init__(self, db_path: str, performance_config: PerformanceConfig = None):
        self.db_path = db_path
        self.performance_config = performance_config or PerformanceConfig()
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Инициализация компонентов производительности
        if self.performance_config.USE_CONNECTION_POOLING:
            self.pool = ConnectionPool(db_path, self.performance_config.BATCH_SIZE)
        else:
            self.pool = None
        
        if self.performance_config.ENABLE_CACHING:
            self.cache = CacheManager()
        else:
            self.cache = None
        
        self.logger.info(f"DatabaseManager initialized with db_path: {db_path}")
        self.logger.info(f"Performance config: pooling={self.performance_config.USE_CONNECTION_POOLING}, "
                        f"caching={self.performance_config.ENABLE_CACHING}")

    async def init_db(self):
        """Инициализирует базу данных с оптимизированными индексами"""
        try:
            if self.pool:
                await self.pool.init_pool()
            
            async with self._get_connection() as db:
                # Создание таблиц
                await self._create_tables(db)
                
                # Создание индексов для производительности
                await self._create_indexes(db)
                
                # Начальные данные
                await self._insert_initial_data(db)
                
                await db.commit()
                self.logger.info("Database initialized successfully with optimizations")
        except aiosqlite.Error as e:
            self.logger.error(f"Database error in init_db: {e}", exc_info=True)
            raise

    async def _create_tables(self, db: aiosqlite.Connection):
        """Создает таблицы базы данных"""
        # Wallets Table с оптимизацией
        await db.execute('''
            CREATE TABLE IF NOT EXISTS wallets (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance REAL NOT NULL DEFAULT 0.0 CHECK (balance >= 0),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Transactions Table с улучшенной структурой
        await db.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sender_id INTEGER,
                receiver_id INTEGER,
                amount REAL NOT NULL CHECK (amount > 0),
                description TEXT,
                transaction_type TEXT DEFAULT 'transfer'
            )
        ''')
        
        # Token Info Table
        await db.execute('''
            CREATE TABLE IF NOT EXISTS token_info (
                id INTEGER PRIMARY KEY DEFAULT 1,
                current_price REAL NOT NULL CHECK (current_price >= 0),
                total_supply REAL NOT NULL CHECK (total_supply > 0),
                name TEXT NOT NULL,
                symbol TEXT NOT NULL,
                decimals INTEGER NOT NULL CHECK (decimals >= 0)
            )
        ''')
        
        # Stakes Table с улучшениями
        await db.execute('''
            CREATE TABLE IF NOT EXISTS stakes (
                stake_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL CHECK (amount > 0),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_claimed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES wallets(user_id) ON DELETE CASCADE
            )
        ''')
        
        # Active Boosters Table
        await db.execute('''
            CREATE TABLE IF NOT EXISTS active_boosters (
                booster_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                booster_type TEXT NOT NULL,
                active_until TIMESTAMP NOT NULL,
                effect_multiplier REAL NOT NULL CHECK (effect_multiplier > 0),
                FOREIGN KEY(user_id) REFERENCES wallets(user_id) ON DELETE CASCADE
            )
        ''')

    async def _create_indexes(self, db: aiosqlite.Connection):
        """Создает индексы для оптимизации запросов"""
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_wallets_username ON wallets(username)",
            "CREATE INDEX IF NOT EXISTS idx_transactions_sender ON transactions(sender_id)",
            "CREATE INDEX IF NOT EXISTS idx_transactions_receiver ON transactions(receiver_id)",
            "CREATE INDEX IF NOT EXISTS idx_transactions_timestamp ON transactions(timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_stakes_user ON stakes(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_stakes_created ON stakes(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_boosters_user ON active_boosters(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_boosters_active ON active_boosters(active_until)",
        ]
        
        for index_sql in indexes:
            await db.execute(index_sql)

    async def _insert_initial_data(self, db: aiosqlite.Connection):
        """Вставляет начальные данные"""
        token_config = TokenConfig()
        await db.execute('''
            INSERT OR IGNORE INTO token_info (id, current_price, total_supply, name, symbol, decimals)
            VALUES (1, ?, ?, ?, ?, ?)
        ''', (token_config.INITIAL_PRICE, token_config.TOTAL_SUPPLY, 
              token_config.NAME, token_config.SYMBOL, token_config.DECIMALS))

    @asynccontextmanager
    async def _get_connection(self):
        """Получает соединение с базой данных"""
        if self.pool:
            async with self.pool.get_connection() as conn:
                yield conn
        else:
            async with aiosqlite.connect(self.db_path) as conn:
                conn.row_factory = aiosqlite.Row
                yield conn

    async def execute_query(self, query: str, params: tuple = None) -> bool:
        """Выполняет запрос с retry логикой"""
        params = params or ()
        
        for attempt in range(self.performance_config.MAX_RETRIES):
            try:
                async with self._get_connection() as db:
                    await db.execute(query, params)
                    await db.commit()
                    
                    # Инвалидируем кэш при изменении данных
                    if self.cache and any(word in query.upper() for word in ['INSERT', 'UPDATE', 'DELETE']):
                        self.cache.invalidate()
                    
                    return True
            except aiosqlite.Error as e:
                self.logger.warning(f"Database error on attempt {attempt + 1}: {e}")
                if attempt == self.performance_config.MAX_RETRIES - 1:
                    self.logger.error(f"Database error after {self.performance_config.MAX_RETRIES} retries: {e}")
                    return False
                await asyncio.sleep(self.performance_config.RETRY_DELAY)
        
        return False

    async def fetch_one(self, query: str, params: tuple = None, use_cache: bool = True) -> Optional[aiosqlite.Row]:
        """Получает одну запись с кэшированием"""
        params = params or ()
        cache_key = f"fetch_one:{hash((query, params))}" if use_cache and self.cache else None
        
        # Проверяем кэш
        if cache_key:
            cached_result = self.cache.get(cache_key)
            if cached_result is not None:
                return cached_result
        
        try:
            async with self._get_connection() as db:
                cursor = await db.execute(query, params)
                result = await cursor.fetchone()
                
                # Кэшируем результат
                if cache_key and result:
                    self.cache.set(cache_key, result)
                
                return result
        except aiosqlite.Error as e:
            self.logger.error(f"Database error in fetch_one: {e}", exc_info=True)
            return None

    async def fetch_all(self, query: str, params: tuple = None, use_cache: bool = True) -> Optional[List[aiosqlite.Row]]:
        """Получает все записи с кэшированием"""
        params = params or ()
        cache_key = f"fetch_all:{hash((query, params))}" if use_cache and self.cache else None
        
        # Проверяем кэш
        if cache_key:
            cached_result = self.cache.get(cache_key)
            if cached_result is not None:
                return cached_result
        
        try:
            async with self._get_connection() as db:
                cursor = await db.execute(query, params)
                result = await cursor.fetchall()
                
                # Кэшируем результат
                if cache_key:
                    self.cache.set(cache_key, result or [])
                
                return result or []
        except aiosqlite.Error as e:
            self.logger.error(f"Database error in fetch_all: {e}", exc_info=True)
            return None

    async def execute_transaction(self, operations: List[tuple]) -> bool:
        """Выполняет несколько операций в одной транзакции"""
        try:
            async with self._get_connection() as db:
                await db.execute("BEGIN TRANSACTION")
                try:
                    for query, params in operations:
                        await db.execute(query, params or ())
                    await db.commit()
                    
                    # Инвалидируем кэш
                    if self.cache:
                        self.cache.invalidate()
                    
                    return True
                except Exception as e:
                    await db.rollback()
                    raise e
        except aiosqlite.Error as e:
            self.logger.error(f"Transaction error: {e}", exc_info=True)
            return False

    async def cleanup_cache(self):
        """Очищает устаревшие записи кэша"""
        if self.cache:
            self.cache.cleanup_expired()

    async def close(self):
        """Закрывает все соединения"""
        if self.pool:
            await self.pool.close_all()
        self.logger.info("Database manager closed")
