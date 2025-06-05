import aiosqlite
from database import DatabaseManager
from models import Wallet, Token, Transaction
from config import TokenConfig
from datetime import datetime, timedelta

BASE_HOURLY_REWARD_RATE = 0.001  # 0.1%

BOOSTER_TYPES = {
    "speed_24h_1.5x": {
        "name_ru": "Ускоритель х1.5 (24ч)",
        "cost": 100.0,  # Cost in HKN
        "duration_hours": 24,
        "multiplier": 1.5,
        "description_ru": "Увеличивает скорость фарминга на 50% на 24 часа."
    },
    "speed_7d_2x": {
        "name_ru": "Мега Ускоритель х2.0 (7 дней)",
        "cost": 500.0,
        "duration_hours": 168, # 7 * 24
        "multiplier": 2.0,
        "description_ru": "Увеличивает скорость фарминга в 2 раза на 7 дней!"
    }
}

class LedgerManager:
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.booster_types = BOOSTER_TYPES # Make it accessible within the class

    async def create_wallet(self, user_id: int, username: str) -> Wallet:
        await self.db_manager.execute_query(
            "INSERT INTO wallets (user_id, username, balance) VALUES (?, ?, ?)",
            (user_id, username, TokenConfig.STARTUP_BONUS)
        )
        return Wallet(user_id, username, TokenConfig.STARTUP_BONUS, "now")

    async def get_wallet(self, user_id: int) -> Wallet | None:
        row = await self.db_manager.fetch_one("SELECT * FROM wallets WHERE user_id = ?", (user_id,))
        return Wallet(**row) if row else None

    async def update_balance(self, user_id: int, amount: float):
        await self.db_manager.execute_query(
            "UPDATE wallets SET balance = balance + ? WHERE user_id = ?",
            (amount, user_id)
        )

    async def execute_transfer(self, sender_id: int, receiver_id: int, amount: float) -> bool:
        sender_wallet = await self.get_wallet(sender_id)
        receiver_wallet = await self.get_wallet(receiver_id)

        if not sender_wallet or not receiver_wallet:
            return False
        if sender_wallet.balance < amount:
            return False
        if amount <= 0:
            return False

        async with aiosqlite.connect(self.db_manager.db_path) as db:
            await db.execute("BEGIN TRANSACTION")
            try:
                await db.execute("UPDATE wallets SET balance = balance - ? WHERE user_id = ?", (amount, sender_id))
                await db.execute("UPDATE wallets SET balance = balance + ? WHERE user_id = ?", (amount, receiver_id))
                await db.execute(
                    "INSERT INTO transactions (sender_id, receiver_id, amount, description) VALUES (?, ?, ?, ?)",
                    (sender_id, receiver_id, amount, "Transfer")
                )
                await db.commit()
                return True
            except Exception as e:
                await db.rollback()
                print(f"Error during transfer: {e}")
                return False

    async def get_token_info(self) -> Token | None:
        row = await self.db_manager.fetch_one("SELECT * FROM token_info WHERE id = 1")
        return Token(**row) if row else None

    async def calculate_market_cap(self) -> float:
        token_info_obj = await self.get_token_info()
        if not token_info_obj:
            return 0.0
        return token_info_obj.total_supply * token_info_obj.current_price

    async def set_token_price(self, new_price: float):
        await self.db_manager.execute_query(
            "UPDATE token_info SET current_price = ? WHERE id = 1",
            (new_price,)
        )

    async def mint_tokens(self, user_id: int, amount: float) -> bool:
        wallet = await self.get_wallet(user_id)
        if not wallet:
            return False
        if amount <= 0:
            return False

        current_token_info = await self.get_token_info()
        if not current_token_info:
             return False
        new_total_supply = current_token_info.total_supply + amount

        async with aiosqlite.connect(self.db_manager.db_path) as db:
            await db.execute("BEGIN TRANSACTION")
            try:
                await db.execute("UPDATE wallets SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
                await db.execute(
                    "UPDATE token_info SET total_supply = ? WHERE id = 1",
                    (new_total_supply,)
                )
                await db.execute(
                    "INSERT INTO transactions (sender_id, receiver_id, amount, description) VALUES (?, ?, ?, ?)",
                    (0, user_id, amount, "Minted by admin")
                )
                await db.commit()
                return True
            except Exception:
                await db.rollback()
                return False

    async def get_transaction_history(self, user_id: int, limit: int = 5, offset: int = 0):
        rows = await self.db_manager.fetch_all(
            """
            SELECT * FROM transactions
            WHERE sender_id = ? OR receiver_id = ?
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
            """,
            (user_id, user_id, limit, offset)
        )
        return [Transaction(**row) for row in rows]

    # --- Staking Methods ---

    def calculate_rewards(self, stake_amount: float, start_time: datetime, end_time: datetime, booster_multiplier: float) -> float:
        if not isinstance(start_time, datetime) or not isinstance(end_time, datetime):
            raise ValueError("start_time and end_time must be datetime objects")

        duration_seconds = (end_time - start_time).total_seconds()
        if duration_seconds < 0:
            duration_seconds = 0

        duration_hours = duration_seconds / 3600.0
        reward = stake_amount * (duration_hours * BASE_HOURLY_REWARD_RATE) * booster_multiplier
        return reward

    async def get_active_booster_multiplier(self, user_id: int, booster_type_prefix: str = "speed") -> float:
        query = """
            SELECT effect_multiplier FROM active_boosters
            WHERE user_id = ? AND booster_type LIKE ? AND active_until > ?
            ORDER BY effect_multiplier DESC LIMIT 1
        """
        # The booster_type_prefix (e.g., "speed") will be matched like "speed%"
        # This allows different categories of boosters, e.g., "speed_staking", "speed_general"
        current_time_dt = datetime.now()
        # Convert datetime to string for SQLite comparison if not automatically handled by driver
        # current_time_str = current_time_dt.isoformat() # Alternative if direct datetime comparison fails

        row = await self.db_manager.fetch_one(query, (user_id, f"{booster_type_prefix}%", current_time_dt))
        if row:
            return float(row['effect_multiplier'])
        return 1.0

    async def stake_tokens(self, user_id: int, amount: float) -> tuple[bool, str]:
        wallet = await self.get_wallet(user_id)
        if not wallet:
            return False, "Кошелек не найден."
        if wallet.balance < amount:
            return False, "Недостаточно средств"
        if amount <= 0:
            return False, "Сумма должна быть положительной"

        async with aiosqlite.connect(self.db_manager.db_path) as db:
            await db.execute("BEGIN TRANSACTION")
            try:
                # Deduct from wallet
                await db.execute("UPDATE wallets SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
                # Add to stakes
                current_time = datetime.now()
                await db.execute(
                    "INSERT INTO stakes (user_id, amount, created_at, last_claimed_at) VALUES (?, ?, ?, ?)",
                    (user_id, amount, current_time, current_time)
                )
                await db.commit()
                return True, f"{amount:.{TokenConfig.DECIMALS}f} HKN успешно поставлены на стейк!"
            except Exception as e:
                await db.rollback()
                print(f"Error staking tokens: {e}")
                return False, "Ошибка при стейкинге токенов."

    async def get_user_stakes(self, user_id: int) -> list[dict]:
        stakes_rows = await self.db_manager.fetch_all("SELECT stake_id, amount, created_at, last_claimed_at FROM stakes WHERE user_id = ?", (user_id,))

        result_stakes = []
        if not stakes_rows:
            return []

        # For staking, we usually use a specific booster type, e.g., "speed_staking"
        booster_multiplier = await self.get_active_booster_multiplier(user_id, booster_type_prefix="speed_staking")
        current_time = datetime.now()

        for row_dict in stakes_rows: # aiosqlite.Row is dict-like
            stake_id = row_dict['stake_id']
            staked_amount = row_dict['amount']

            created_at_val = row_dict['created_at']
            last_claimed_at_val = row_dict['last_claimed_at']

            created_at_dt = datetime.fromisoformat(created_at_val) if isinstance(created_at_val, str) else created_at_val
            last_claimed_at_dt = datetime.fromisoformat(last_claimed_at_val) if isinstance(last_claimed_at_val, str) else last_claimed_at_val

            pending_rewards = self.calculate_rewards(staked_amount, last_claimed_at_dt, current_time, booster_multiplier)

            result_stakes.append({
                'stake_id': stake_id,
                'amount': staked_amount,
                'created_at': created_at_dt.strftime("%Y-%m-%d %H:%M:%S"),
                'last_claimed_at': last_claimed_at_dt.strftime("%Y-%m-%d %H:%M:%S"),
                'pending_rewards': pending_rewards
            })
        return result_stakes

    async def _calculate_and_update_rewards(self, stake_id: int, for_unstake: bool = False) -> tuple | None:
        stake_row = await self.db_manager.fetch_one("SELECT user_id, amount, last_claimed_at FROM stakes WHERE stake_id = ?", (stake_id,))
        if not stake_row:
            return None

        user_id = stake_row['user_id']
        staked_amount = stake_row['amount']
        last_claimed_at_val = stake_row['last_claimed_at']

        last_claimed_at_dt = datetime.fromisoformat(last_claimed_at_val) if isinstance(last_claimed_at_val, str) else last_claimed_at_val

        current_time = datetime.now()
        booster_multiplier = await self.get_active_booster_multiplier(user_id, booster_type_prefix="speed_staking")

        rewards = self.calculate_rewards(staked_amount, last_claimed_at_dt, current_time, booster_multiplier)

        if rewards > 0 and not for_unstake:
            await self.db_manager.execute_query(
                "UPDATE stakes SET last_claimed_at = ? WHERE stake_id = ?",
                (current_time, stake_id)
            )

        return user_id, staked_amount, rewards, current_time

    async def claim_rewards(self, user_id: int, stake_id: int) -> tuple[bool, str]:
        calculation_result = await self._calculate_and_update_rewards(stake_id, for_unstake=False)
        if not calculation_result:
            return False, "Стейк не найден."

        s_user_id, _, calculated_rewards, _ = calculation_result

        if s_user_id != user_id:
            return False, "Этот стейк вам не принадлежит."

        if calculated_rewards <= 0: # Allow claiming zero rewards if last_claimed_at was just updated by another claim.
            return False, "Нет доступных наград для получения."

        async with aiosqlite.connect(self.db_manager.db_path) as db:
            await db.execute("BEGIN TRANSACTION")
            try:
                await db.execute("UPDATE wallets SET balance = balance + ? WHERE user_id = ?", (calculated_rewards, user_id))
                await db.execute(
                    "INSERT INTO transactions (sender_id, receiver_id, amount, description) VALUES (?, ?, ?, ?)",
                    (0, user_id, calculated_rewards, f"Награда за стейкинг (ID: {stake_id})")
                )
                await db.commit()
                return True, f"Вы успешно получили {calculated_rewards:.{TokenConfig.DECIMALS}f} HKN награды!"
            except Exception as e:
                await db.rollback()
                print(f"Error claiming rewards: {e}")
                return False, "Ошибка при получении наград."

    async def unstake_tokens(self, user_id: int, stake_id: int) -> tuple[bool, str]:
        calculation_result = await self._calculate_and_update_rewards(stake_id, for_unstake=True)
        if not calculation_result:
            return False, "Стейк не найден."

        s_user_id, staked_amount, calculated_rewards, _ = calculation_result

        if s_user_id != user_id:
            return False, "Этот стейк вам не принадлежит."

        total_return_amount = staked_amount + calculated_rewards

        async with aiosqlite.connect(self.db_manager.db_path) as db:
            await db.execute("BEGIN TRANSACTION")
            try:
                await db.execute("UPDATE wallets SET balance = balance + ? WHERE user_id = ?", (total_return_amount, user_id))
                await db.execute("DELETE FROM stakes WHERE stake_id = ?", (stake_id,))
                await db.execute(
                    "INSERT INTO transactions (sender_id, receiver_id, amount, description) VALUES (?, ?, ?, ?)",
                    (0, user_id, total_return_amount, f"Возврат со стейкинга (ID: {stake_id}) + награды")
                )
                await db.commit()
                return True, f"Вы успешно сняли {staked_amount:.{TokenConfig.DECIMALS}f} HKN со стейка. Получено наград: {calculated_rewards:.{TokenConfig.DECIMALS}f} HKN."
            except Exception as e:
                await db.rollback()
                print(f"Error unstaking tokens: {e}")
                return False, "Ошибка при снятии токенов со стейка."

    # --- Booster Methods ---
    async def buy_booster(self, user_id: int, booster_key: str) -> tuple[bool, str]:
        if booster_key not in self.booster_types:
            return False, "Неверный тип ускорителя."

        booster_config = self.booster_types[booster_key]
        cost = booster_config['cost']

        wallet = await self.get_wallet(user_id)
        if not wallet:
            return False, "Кошелек не найден."
        if wallet.balance < cost:
            return False, f"Недостаточно HKN для покупки. Нужно {cost:.{TokenConfig.DECIMALS}f} HKN."

        active_until = datetime.now() + timedelta(hours=booster_config['duration_hours'])

        async with aiosqlite.connect(self.db_manager.db_path) as db:
            await db.execute("BEGIN TRANSACTION")
            try:
                # Deduct cost
                await db.execute("UPDATE wallets SET balance = balance - ? WHERE user_id = ?", (cost, user_id))

                # Option A: Overwrite existing speed boosters
                # The booster_key itself (e.g., "speed_24h_1.5x") is stored as booster_type.
                # If we want to delete any "speed%" booster, the LIKE clause is correct.
                # If we want to delete only the exact same booster_key if it's reactivated, then `booster_type = ?`
                # For now, deleting any "speed%" booster on new "speed%" purchase.
                if booster_key.startswith("speed"):
                    await db.execute("DELETE FROM active_boosters WHERE user_id = ? AND booster_type LIKE 'speed%'", (user_id,))

                # Insert new booster
                await db.execute(
                    "INSERT INTO active_boosters (user_id, booster_type, active_until, effect_multiplier) VALUES (?, ?, ?, ?)",
                    (user_id, booster_key, active_until, booster_config['multiplier'])
                )

                # Record transaction
                await db.execute(
                    "INSERT INTO transactions (sender_id, receiver_id, amount, description) VALUES (?, ?, ?, ?)",
                    (user_id, 0, cost, f"Покупка ускорителя: {booster_config['name_ru']}") # sender_id is user, receiver_id=0 for system
                )
                await db.commit()
                return True, f"Ускоритель '{booster_config['name_ru']}' успешно куплен и активирован!"
            except Exception as e:
                await db.rollback()
                print(f"Error buying booster: {e}")
                return False, "Ошибка при покупке ускорителя."

    def get_available_boosters_info(self) -> dict:
        """Returns a copy of BOOSTER_TYPES for display purposes."""
        return self.booster_types.copy()

    # --- Sell HKN to System ---
    HKN_SELL_RATE_TO_BOTUSD = 0.00005 # Conceptual rate: 1 HKN = 0.00005 BotUSD

    async def sell_hkn_to_system(self, user_id: int, amount_hkn: float) -> tuple[bool, str]:
        if amount_hkn <= 0:
            return False, "Сумма HKN должна быть положительной."

        wallet = await self.get_wallet(user_id)
        if not wallet:
            # This case should ideally not be reached if user is interacting via bot commands
            # and has gone through /start.
            return False, "Кошелек не найден. Пожалуйста, используйте /start."

        if wallet.balance < amount_hkn:
            return False, f"Недостаточно HKN для продажи. Ваш баланс: {wallet.balance:.{TokenConfig.DECIMALS}f} HKN."

        received_bot_usd = amount_hkn * self.HKN_SELL_RATE_TO_BOTUSD

        async with aiosqlite.connect(self.db_manager.db_path) as db:
            await db.execute("BEGIN TRANSACTION")
            try:
                # Deduct HKN from user's wallet
                await db.execute(
                    "UPDATE wallets SET balance = balance - ? WHERE user_id = ?",
                    (amount_hkn, user_id)
                )

                # Record the transaction
                description = (f"Продажа {amount_hkn:.{TokenConfig.DECIMALS}f} HKN системе "
                               f"за {received_bot_usd:.{TokenConfig.DECIMALS}f} BotUSD") # Using HKN decimals for BotUSD display simplicity
                await db.execute(
                    "INSERT INTO transactions (sender_id, receiver_id, amount, description) VALUES (?, ?, ?, ?)",
                    (user_id, 0, amount_hkn, description) # receiver_id = 0 for system/bank
                )

                await db.commit()
                return True, (f"Вы успешно продали {amount_hkn:.{TokenConfig.DECIMALS}f} HKN системе и получили "
                              f"{received_bot_usd:.{TokenConfig.DECIMALS}f} BotUSD (концептуально).")
            except Exception as e:
                await db.rollback()
                print(f"Error selling HKN to system: {e}")
                return False, "Произошла ошибка при продаже HKN."
