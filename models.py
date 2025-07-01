from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
import json

@dataclass
class Token:
    """Модель токена с валидацией"""
    name: str
    symbol: str
    decimals: int
    total_supply: float
    current_price: float
    
    def __post_init__(self):
        if self.decimals < 0:
            raise ValueError("Decimals must be non-negative")
        if self.total_supply <= 0:
            raise ValueError("Total supply must be positive")
        if self.current_price < 0:
            raise ValueError("Price must be non-negative")
    
    @property
    def market_cap(self) -> float:
        """Вычисляет рыночную капитализацию"""
        return self.total_supply * self.current_price

@dataclass
class Wallet:
    """Модель кошелька с дополнительными методами"""
    user_id: int
    username: Optional[str]
    balance: float
    created_at: str
    
    def __post_init__(self):
        if self.balance < 0:
            raise ValueError("Balance cannot be negative")
    
    @property
    def display_name(self) -> str:
        """Возвращает отображаемое имя пользователя"""
        return f"@{self.username}" if self.username else f"ID:{self.user_id}"
    
    def has_sufficient_balance(self, amount: float) -> bool:
        """Проверяет достаточность баланса"""
        return self.balance >= amount
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертирует в словарь для кэширования"""
        return {
            'user_id': self.user_id,
            'username': self.username,
            'balance': self.balance,
            'created_at': self.created_at
        }

@dataclass
class Transaction:
    """Модель транзакции с улучшенной функциональностью"""
    id: int
    timestamp: str
    sender_id: int
    receiver_id: int
    amount: float
    description: Optional[str] = None
    
    @property
    def is_mint(self) -> bool:
        """Проверяет является ли транзакция эмиссией"""
        return self.sender_id == 0
    
    @property
    def is_burn(self) -> bool:
        """Проверяет является ли транзакция сжиганием"""
        return self.receiver_id == 0
    
    @property
    def formatted_timestamp(self) -> str:
        """Возвращает отформатированное время"""
        try:
            dt = datetime.fromisoformat(self.timestamp)
            return dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return self.timestamp
    
    def get_direction_for_user(self, user_id: int) -> str:
        """Возвращает направление транзакции для пользователя"""
        if self.is_mint and self.receiver_id == user_id:
            return "received"
        elif self.is_burn and self.sender_id == user_id:
            return "sent"
        elif self.receiver_id == user_id:
            return "received"
        elif self.sender_id == user_id:
            return "sent"
        else:
            return "unknown"

@dataclass
class Stake:
    """Модель стейка с расчетом наград"""
    stake_id: int
    user_id: int
    amount: float
    created_at: datetime
    last_claimed_at: datetime
    pending_rewards: float = 0.0
    
    @property
    def age_hours(self) -> float:
        """Возвращает возраст стейка в часах"""
        return (datetime.now() - self.created_at).total_seconds() / 3600
    
    @property
    def time_since_last_claim_hours(self) -> float:
        """Возвращает время с последнего сбора наград в часах"""
        return (datetime.now() - self.last_claimed_at).total_seconds() / 3600
    
    def calculate_pending_rewards(self, hourly_rate: float, multiplier: float = 1.0) -> float:
        """Вычисляет ожидающие награды"""
        hours = self.time_since_last_claim_hours
        return self.amount * hours * hourly_rate * multiplier

@dataclass
class Booster:
    """Модель ускорителя"""
    booster_id: int
    user_id: int
    booster_type: str
    active_until: datetime
    effect_multiplier: float
    
    @property
    def is_active(self) -> bool:
        """Проверяет активен ли ускоритель"""
        return datetime.now() < self.active_until
    
    @property
    def remaining_hours(self) -> float:
        """Возвращает оставшееся время в часах"""
        if not self.is_active:
            return 0.0
        return (self.active_until - datetime.now()).total_seconds() / 3600

@dataclass
class CacheEntry:
    """Модель записи кэша"""
    key: str
    value: Any
    created_at: datetime
    ttl: int  # seconds
    
    @property
    def is_expired(self) -> bool:
        """Проверяет истек ли кэш"""
        age = (datetime.now() - self.created_at).total_seconds()
        return age > self.ttl
