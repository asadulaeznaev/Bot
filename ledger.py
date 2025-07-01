"""
Оптимизированный LedgerManager с кэшированием и улучшенной производительностью
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Union
from dataclasses import asdict

from database import DatabaseManager
from models import Wallet, Token, Transaction, Stake, Booster
from config import TokenConfig

# Константы для стейкинга и бустеров
BOOSTER_TYPES = {
    "speed_24h_1.5x": {
        "name_ru": "Ускоритель х1.5 (24ч)",
        "cost": 100.0,
        "duration_hours": 24,
        "multiplier": 1.5,
        "description_ru": "Увеличивает скорость фарминга на 50% на 24 часа."
    },
    "speed_7d_2x": {
        "name_ru": "Мега Ускоритель х2.0 (7 дней)",
        "cost": 500.0,
        "duration_hours": 168,
        "multiplier": 2.0,
        "description_ru": "Увеличивает скорость фарминга в 2 раза на 7 дней!"
    }
}

class LedgerManager:
    """Оптимизированный менеджер бизнес-логики с кэшированием"""
    
    def __init__(self, db_manager: DatabaseManager, token_config: TokenConfig):
        self.db_manager = db_manager
        self.token_config = token_config
        self.booster_types = BOOSTER_TYPES
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Константы для производительности
        self.HKN_SELL_RATE_TO_BOTUSD = 0.00005
        self.GENERIC_ERROR_MESSAGE = "Произошла внутренняя ошибка. Пожалуйста, попробуйте позже."
        
        self.logger.info("LedgerManager initialized with optimizations")
    
    # === Операции с кошельками ===
    
    async def create_wallet(self, user_id: int, username: Optional[str]) -> Optional[Wallet]:
        """Создает новый кошелек с стартовым бонусом"""
        self.logger.info(f"Creating wallet for user_id: {user_id}, username: {username}")
        
        try:
            operations = [
                ("INSERT INTO wallets (user_id, username, balance) VALUES (?, ?, ?)",
                 (user_id, username, self.token_config.STARTUP_BONUS)),
                ("INSERT INTO transactions (sender_id, receiver_id, amount, description) VALUES (?, ?, ?, ?)",
                 (0, user_id, self.token_config.STARTUP_BONUS, "Стартовый бонус"))
            ]
            
            if await self.db_manager.execute_transaction(operations):
                self.logger.info(f"Wallet created successfully for user_id: {user_id}")
                return Wallet(
                    user_id=user_id,
                    username=username,
                    balance=self.token_config.STARTUP_BONUS,
                    created_at=datetime.now().isoformat()
                )
            return None
        except Exception as e:
            self.logger.error(f"Error creating wallet for user {user_id}: {e}", exc_info=True)
            return None
    
    async def get_wallet(self, user_id: int, use_cache: bool = True) -> Optional[Wallet]:
        """Получает кошелек пользователя с кэшированием"""
        try:
            row = await self.db_manager.fetch_one(
                "SELECT user_id, username, balance, created_at FROM wallets WHERE user_id = ?",
                (user_id,),
                use_cache=use_cache
            )
            if row:
                return Wallet(**dict(row))
            return None
        except Exception as e:
            self.logger.error(f"Error getting wallet for user {user_id}: {e}", exc_info=True)
            return None
    
    async def update_balance(self, user_id: int, amount: float) -> bool:
        """Обновляет баланс пользователя"""
        self.logger.info(f"Updating balance for user {user_id} by amount {amount}")
        
        try:
            success = await self.db_manager.execute_query(
                "UPDATE wallets SET balance = balance + ? WHERE user_id = ?",
                (amount, user_id)
            )
            
            # Инвалидируем кэш кошелька при изменении баланса
            if success and self.db_manager.cache:
                self.db_manager.cache.invalidate(f"fetch_one:{user_id}")
            
            return success
        except Exception as e:
            self.logger.error(f"Error updating balance for user {user_id}: {e}", exc_info=True)
            return False
    
    # === Операции с переводами ===
    
    async def execute_transfer(self, sender_id: int, receiver_id: int, amount: float) -> Tuple[bool, str]:
        """Выполняет перевод между пользователями с проверками"""
        self.logger.info(f"Transfer attempt: {amount} HKN from {sender_id} to {receiver_id}")
        
        if amount <= 0:
            return False, "Сумма перевода должна быть положительной."
        
        try:
            # Получаем кошельки
            sender_wallet = await self.get_wallet(sender_id, use_cache=False)  # Не используем кэш для актуальных данных
            receiver_wallet = await self.get_wallet(receiver_id)
            
            if not sender_wallet:
                return False, "Кошелек отправителя не найден."
            if not receiver_wallet:
                return False, "Кошелек получателя не найден."
            if not sender_wallet.has_sufficient_balance(amount):
                return False, "Недостаточно средств на балансе отправителя."
            
            # Выполняем транзакцию
            operations = [
                ("UPDATE wallets SET balance = balance - ? WHERE user_id = ?", (amount, sender_id)),
                ("UPDATE wallets SET balance = balance + ? WHERE user_id = ?", (amount, receiver_id)),
                ("INSERT INTO transactions (sender_id, receiver_id, amount, description) VALUES (?, ?, ?, ?)",
                 (sender_id, receiver_id, amount, "Перевод"))
            ]
            
            if await self.db_manager.execute_transaction(operations):
                self.logger.info(f"Transfer successful: {amount} HKN from {sender_id} to {receiver_id}")
                return True, "Перевод успешно выполнен."
            else:
                return False, "Ошибка при выполнении перевода."
                
        except Exception as e:
            self.logger.error(f"Error in transfer from {sender_id} to {receiver_id}: {e}", exc_info=True)
            return False, self.GENERIC_ERROR_MESSAGE
    
    # === Операции с токеном ===
    
    async def get_token_info(self, use_cache: bool = True) -> Optional[Token]:
        """Получает информацию о токене"""
        try:
            row = await self.db_manager.fetch_one(
                "SELECT name, symbol, decimals, total_supply, current_price FROM token_info WHERE id = 1",
                use_cache=use_cache
            )
            return Token(**dict(row)) if row else None
        except Exception as e:
            self.logger.error(f"Error getting token info: {e}", exc_info=True)
            return None
    
    async def calculate_market_cap(self) -> float:
        """Вычисляет рыночную капитализацию"""
        try:
            token_info = await self.get_token_info()
            if token_info:
                return token_info.market_cap
            return 0.0
        except Exception as e:
            self.logger.error(f"Error calculating market cap: {e}", exc_info=True)
            return 0.0
    
    async def set_token_price(self, new_price: float) -> bool:
        """Устанавливает новую цену токена (админ функция)"""
        self.logger.info(f"Admin setting token price to {new_price}")
        
        if new_price < 0:
            return False
        
        try:
            success = await self.db_manager.execute_query(
                "UPDATE token_info SET current_price = ? WHERE id = 1",
                (new_price,)
            )
            
            # Инвалидируем кэш информации о токене
            if success and self.db_manager.cache:
                self.db_manager.cache.invalidate("token_info")
            
            return success
        except Exception as e:
            self.logger.error(f"Error setting token price: {e}", exc_info=True)
            return False
    
    async def mint_tokens(self, user_id: int, amount: float) -> bool:
        """Эмитирует токены (админ функция)"""
        self.logger.info(f"Admin minting {amount} HKN for user {user_id}")
        
        if amount <= 0:
            return False
        
        try:
            wallet = await self.get_wallet(user_id)
            if not wallet:
                self.logger.warning(f"Target wallet not found for user {user_id}")
                return False
            
            token_info = await self.get_token_info(use_cache=False)
            if not token_info:
                self.logger.error("Failed to get token info for minting")
                return False
            
            new_total_supply = token_info.total_supply + amount
            
            operations = [
                ("UPDATE wallets SET balance = balance + ? WHERE user_id = ?", (amount, user_id)),
                ("UPDATE token_info SET total_supply = ? WHERE id = 1", (new_total_supply,)),
                ("INSERT INTO transactions (sender_id, receiver_id, amount, description) VALUES (?, ?, ?, ?)",
                 (0, user_id, amount, "Эмиссия токенов администратором"))
            ]
            
            if await self.db_manager.execute_transaction(operations):
                self.logger.info(f"Successfully minted {amount} HKN for user {user_id}")
                return True
            return False
            
        except Exception as e:
            self.logger.error(f"Error minting tokens for user {user_id}: {e}", exc_info=True)
            return False
    
    # === История транзакций ===
    
    async def get_transaction_history(self, user_id: int, limit: int = 5, offset: int = 0) -> List[Transaction]:
        """Получает историю транзакций пользователя"""
        try:
            rows = await self.db_manager.fetch_all(
                """
                SELECT id, timestamp, sender_id, receiver_id, amount, description 
                FROM transactions
                WHERE sender_id = ? OR receiver_id = ?
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
                """,
                (user_id, user_id, limit, offset),
                use_cache=False  # История может часто обновляться
            )
            
            return [Transaction(**dict(row)) for row in rows] if rows else []
        except Exception as e:
            self.logger.error(f"Error getting transaction history for user {user_id}: {e}", exc_info=True)
            return []
    
    # === Стейкинг ===
    
    def calculate_rewards(self, stake_amount: float, start_time: datetime, 
                         end_time: datetime, booster_multiplier: float) -> float:
        """Вычисляет награды за стейкинг"""
        if not isinstance(start_time, datetime) or not isinstance(end_time, datetime):
            raise ValueError("start_time and end_time must be datetime objects")
        
        duration_hours = max(0, (end_time - start_time).total_seconds() / 3600.0)
        reward = stake_amount * duration_hours * self.token_config.BASE_HOURLY_REWARD_RATE * booster_multiplier
        return reward
    
    async def get_active_booster_multiplier(self, user_id: int, booster_type_prefix: str = "speed") -> float:
        """Получает активный множитель бустера"""
        try:
            row = await self.db_manager.fetch_one(
                """
                SELECT effect_multiplier FROM active_boosters
                WHERE user_id = ? AND booster_type LIKE ? AND active_until > ?
                ORDER BY effect_multiplier DESC LIMIT 1
                """,
                (user_id, f"{booster_type_prefix}%", datetime.now()),
                use_cache=True
            )
            return float(row['effect_multiplier']) if row else 1.0
        except Exception as e:
            self.logger.error(f"Error getting booster multiplier for user {user_id}: {e}", exc_info=True)
            return 1.0
    
    async def stake_tokens(self, user_id: int, amount: float) -> Tuple[bool, str]:
        """Стейкает токены"""
        self.logger.info(f"User {user_id} staking {amount} HKN")
        
        if amount < self.token_config.MIN_STAKE_AMOUNT:
            return False, f"Минимальная сумма для стейка: {self.token_config.MIN_STAKE_AMOUNT} HKN"
        
        if amount > self.token_config.MAX_STAKE_AMOUNT:
            return False, f"Максимальная сумма для стейка: {self.token_config.MAX_STAKE_AMOUNT} HKN"
        
        try:
            wallet = await self.get_wallet(user_id, use_cache=False)
            if not wallet:
                return False, "Кошелек не найден."
            
            if not wallet.has_sufficient_balance(amount):
                return False, f"Недостаточно средств. Ваш баланс: {wallet.balance:.{self.token_config.DECIMALS}f} HKN."
            
            current_time = datetime.now()
            operations = [
                ("UPDATE wallets SET balance = balance - ? WHERE user_id = ?", (amount, user_id)),
                ("INSERT INTO stakes (user_id, amount, created_at, last_claimed_at) VALUES (?, ?, ?, ?)",
                 (user_id, amount, current_time, current_time))
            ]
            
            if await self.db_manager.execute_transaction(operations):
                self.logger.info(f"User {user_id} successfully staked {amount} HKN")
                return True, f"{amount:.{self.token_config.DECIMALS}f} HKN успешно поставлены на стейк!"
            return False, "Ошибка при стейкинге."
            
        except Exception as e:
            self.logger.error(f"Error staking tokens for user {user_id}: {e}", exc_info=True)
            return False, self.GENERIC_ERROR_MESSAGE
    
    async def get_user_stakes(self, user_id: int) -> List[Dict]:
        """Получает стейки пользователя с вычисленными наградами"""
        try:
            stakes_rows = await self.db_manager.fetch_all(
                "SELECT stake_id, amount, created_at, last_claimed_at FROM stakes WHERE user_id = ?",
                (user_id,),
                use_cache=False  # Награды постоянно растут
            )
            
            if not stakes_rows:
                return []
            
            result_stakes = []
            booster_multiplier = await self.get_active_booster_multiplier(user_id, "speed")
            current_time = datetime.now()
            
            for row in stakes_rows:
                created_at_dt = datetime.fromisoformat(row['created_at']) if isinstance(row['created_at'], str) else row['created_at']
                last_claimed_at_dt = datetime.fromisoformat(row['last_claimed_at']) if isinstance(row['last_claimed_at'], str) else row['last_claimed_at']
                
                pending_rewards = self.calculate_rewards(
                    row['amount'], last_claimed_at_dt, current_time, booster_multiplier
                )
                
                result_stakes.append({
                    'stake_id': row['stake_id'],
                    'amount': row['amount'],
                    'created_at': created_at_dt,
                    'last_claimed_at': last_claimed_at_dt,
                    'pending_rewards': pending_rewards
                })
            
            return result_stakes
        except Exception as e:
            self.logger.error(f"Error getting stakes for user {user_id}: {e}", exc_info=True)
            return []
    
    async def unstake_tokens(self, user_id: int, stake_id: int) -> Tuple[bool, str]:
        """Снимает токены со стейка с наградами"""
        self.logger.info(f"User {user_id} attempting to unstake stake_id {stake_id}")
        
        try:
            # Получаем информацию о стейке
            stake_row = await self.db_manager.fetch_one(
                "SELECT user_id, amount, last_claimed_at FROM stakes WHERE stake_id = ?",
                (stake_id,),
                use_cache=False
            )
            
            if not stake_row:
                return False, "Стейк не найден."
            
            if stake_row['user_id'] != user_id:
                return False, "Этот стейк вам не принадлежит."
            
            # Вычисляем награды
            staked_amount = stake_row['amount']
            last_claimed_at_dt = datetime.fromisoformat(stake_row['last_claimed_at']) if isinstance(stake_row['last_claimed_at'], str) else stake_row['last_claimed_at']
            current_time = datetime.now()
            booster_multiplier = await self.get_active_booster_multiplier(user_id, "speed")
            calculated_rewards = self.calculate_rewards(staked_amount, last_claimed_at_dt, current_time, booster_multiplier)
            
            total_return_amount = staked_amount + calculated_rewards
            
            operations = [
                ("UPDATE wallets SET balance = balance + ? WHERE user_id = ?", (total_return_amount, user_id)),
                ("DELETE FROM stakes WHERE stake_id = ?", (stake_id,)),
                ("INSERT INTO transactions (sender_id, receiver_id, amount, description) VALUES (?, ?, ?, ?)",
                 (0, user_id, total_return_amount, f"Возврат со стейкинга (ID: {stake_id}) + награды"))
            ]
            
            if await self.db_manager.execute_transaction(operations):
                self.logger.info(f"User {user_id} successfully unstaked {staked_amount} HKN (plus {calculated_rewards} rewards)")
                return True, f"Вы успешно сняли {staked_amount:.{self.token_config.DECIMALS}f} HKN со стейка. Получено наград: {calculated_rewards:.{self.token_config.DECIMALS}f} HKN."
            return False, "Ошибка при снятии со стейка."
            
        except Exception as e:
            self.logger.error(f"Error unstaking tokens for user {user_id}, stake {stake_id}: {e}", exc_info=True)
            return False, self.GENERIC_ERROR_MESSAGE
    
    async def claim_rewards(self, user_id: int, stake_id: int) -> Tuple[bool, str]:
        """Забирает награды со стейка без снятия основной суммы"""
        self.logger.info(f"User {user_id} attempting to claim rewards for stake {stake_id}")
        
        try:
            # Получаем информацию о стейке
            stake_row = await self.db_manager.fetch_one(
                "SELECT user_id, amount, last_claimed_at FROM stakes WHERE stake_id = ?",
                (stake_id,),
                use_cache=False
            )
            
            if not stake_row:
                return False, "Стейк не найден."
            
            if stake_row['user_id'] != user_id:
                return False, "Этот стейк вам не принадлежит."
            
            # Вычисляем награды
            staked_amount = stake_row['amount']
            last_claimed_at_dt = datetime.fromisoformat(stake_row['last_claimed_at']) if isinstance(stake_row['last_claimed_at'], str) else stake_row['last_claimed_at']
            current_time = datetime.now()
            booster_multiplier = await self.get_active_booster_multiplier(user_id, "speed")
            calculated_rewards = self.calculate_rewards(staked_amount, last_claimed_at_dt, current_time, booster_multiplier)
            
            if calculated_rewards <= 0:
                return False, "Нет доступных наград для получения."
            
            operations = [
                ("UPDATE wallets SET balance = balance + ? WHERE user_id = ?", (calculated_rewards, user_id)),
                ("UPDATE stakes SET last_claimed_at = ? WHERE stake_id = ?", (current_time, stake_id)),
                ("INSERT INTO transactions (sender_id, receiver_id, amount, description) VALUES (?, ?, ?, ?)",
                 (0, user_id, calculated_rewards, f"Награда за стейкинг (ID: {stake_id})"))
            ]
            
            if await self.db_manager.execute_transaction(operations):
                self.logger.info(f"User {user_id} successfully claimed {calculated_rewards} HKN from stake {stake_id}")
                return True, f"Вы успешно получили {calculated_rewards:.{self.token_config.DECIMALS}f} HKN награды!"
            return False, "Ошибка при получении наград."
            
        except Exception as e:
            self.logger.error(f"Error claiming rewards for user {user_id}, stake {stake_id}: {e}", exc_info=True)
            return False, self.GENERIC_ERROR_MESSAGE

    # === Бустеры ===
    
    async def buy_booster(self, user_id: int, booster_key: str) -> Tuple[bool, str]:
        """Покупает бустер"""
        self.logger.info(f"User {user_id} buying booster: {booster_key}")
        
        if booster_key not in self.booster_types:
            return False, "Неверный тип ускорителя."
        
        booster_config = self.booster_types[booster_key]
        cost = booster_config['cost']
        
        try:
            wallet = await self.get_wallet(user_id, use_cache=False)
            if not wallet:
                return False, "Кошелек не найден."
            
            if not wallet.has_sufficient_balance(cost):
                return False, f"Недостаточно HKN. Нужно {cost:.{self.token_config.DECIMALS}f}, у вас {wallet.balance:.{self.token_config.DECIMALS}f}."
            
            active_until = datetime.now() + timedelta(hours=booster_config['duration_hours'])
            
            operations = [
                ("UPDATE wallets SET balance = balance - ? WHERE user_id = ?", (cost, user_id)),
                ("INSERT INTO active_boosters (user_id, booster_type, active_until, effect_multiplier) VALUES (?, ?, ?, ?)",
                 (user_id, booster_key, active_until, booster_config['multiplier'])),
                ("INSERT INTO transactions (sender_id, receiver_id, amount, description) VALUES (?, ?, ?, ?)",
                 (user_id, 0, cost, f"Покупка ускорителя: {booster_config['name_ru']}"))
            ]
            
            # Удаляем старые ускорители того же типа
            if booster_key.startswith("speed"):
                await self.db_manager.execute_query(
                    "DELETE FROM active_boosters WHERE user_id = ? AND booster_type LIKE 'speed%'",
                    (user_id,)
                )
            
            if await self.db_manager.execute_transaction(operations):
                self.logger.info(f"User {user_id} successfully bought booster {booster_key}")
                return True, f"Ускоритель '{booster_config['name_ru']}' успешно куплен и активирован!"
            return False, "Ошибка при покупке ускорителя."
            
        except Exception as e:
            self.logger.error(f"Error buying booster for user {user_id}: {e}", exc_info=True)
            return False, self.GENERIC_ERROR_MESSAGE
    
    def get_available_boosters_info(self) -> Dict:
        """Возвращает информацию о доступных бустерах"""
        return self.booster_types.copy()
    
    # === Продажа токенов ===
    
    async def sell_hkn_to_system(self, user_id: int, amount_hkn: float) -> Tuple[bool, str]:
        """Продает HKN системе"""
        self.logger.info(f"User {user_id} selling {amount_hkn} HKN to system")
        
        if amount_hkn <= 0:
            return False, "Сумма HKN должна быть положительной."
        
        try:
            wallet = await self.get_wallet(user_id, use_cache=False)
            if not wallet:
                return False, "Кошелек не найден."
            
            if not wallet.has_sufficient_balance(amount_hkn):
                return False, f"Недостаточно HKN. Ваш баланс: {wallet.balance:.{self.token_config.DECIMALS}f}."
            
            received_bot_usd = amount_hkn * self.HKN_SELL_RATE_TO_BOTUSD
            description = f"Продажа {amount_hkn:.{self.token_config.DECIMALS}f} HKN системе за {received_bot_usd:.{self.token_config.DECIMALS}f} BotUSD"
            
            operations = [
                ("UPDATE wallets SET balance = balance - ? WHERE user_id = ?", (amount_hkn, user_id)),
                ("INSERT INTO transactions (sender_id, receiver_id, amount, description) VALUES (?, ?, ?, ?)",
                 (user_id, 0, amount_hkn, description))
            ]
            
            if await self.db_manager.execute_transaction(operations):
                self.logger.info(f"User {user_id} successfully sold {amount_hkn} HKN")
                return True, f"Вы успешно продали {amount_hkn:.{self.token_config.DECIMALS}f} HKN и получили {received_bot_usd:.{self.token_config.DECIMALS}f} BotUSD (концептуально)."
            return False, "Ошибка при продаже HKN."
            
        except Exception as e:
            self.logger.error(f"Error selling HKN for user {user_id}: {e}", exc_info=True)
            return False, self.GENERIC_ERROR_MESSAGE
