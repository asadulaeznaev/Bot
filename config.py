import os
from dataclasses import dataclass
from typing import List

@dataclass
class BotConfig:
    """Конфигурация бота с улучшенными настройками производительности"""
    BOT_TOKEN: str = "7861260810:AAEuI-huruUCJyNPgnMbck2t2AnY4pJejD8"
    ADMIN_IDS: List[int] = None
    DB_PATH: str = "helgykoin.db"
    
    # Настройки производительности
    MAX_CONCURRENT_USERS: int = 100
    CACHE_TTL: int = 300  # 5 минут
    CONNECTION_POOL_SIZE: int = 20
    POLLING_TIMEOUT: int = 30
    LONG_POLLING_TIMEOUT: int = 30
    
    def __post_init__(self):
        if self.ADMIN_IDS is None:
            self.ADMIN_IDS = [6328016694]

@dataclass
class TokenConfig:
    """Конфигурация токена с дополнительными параметрами"""
    NAME: str = "HelgyKoin"
    SYMBOL: str = "HKN"
    DECIMALS: int = 8
    TOTAL_SUPPLY: float = 1_000_000_000.0
    INITIAL_PRICE: float = 0.0001
    STARTUP_BONUS: float = 100.0
    
    # Стейкинг конфигурация
    BASE_HOURLY_REWARD_RATE: float = 0.001  # 0.1% в час
    MIN_STAKE_AMOUNT: float = 10.0
    MAX_STAKE_AMOUNT: float = 1_000_000.0

@dataclass
class PerformanceConfig:
    """Настройки производительности"""
    USE_CONNECTION_POOLING: bool = True
    ENABLE_CACHING: bool = True
    BATCH_SIZE: int = 50
    MAX_RETRIES: int = 3
    RETRY_DELAY: float = 1.0
