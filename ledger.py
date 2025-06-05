import aiosqlite
import logging # Added
from database import DatabaseManager
from models import Wallet, Token, Transaction
from config import TokenConfig
from datetime import datetime, timedelta

BASE_HOURLY_REWARD_RATE = 0.001  # 0.1%

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
    """Manages the business logic for wallets, transactions, staking, and boosters."""
    HKN_SELL_RATE_TO_BOTUSD = 0.00005 # Conceptual rate: 1 HKN = 0.00005 BotUSD
    GENERIC_ERROR_MESSAGE = "Произошла внутренняя ошибка. Пожалуйста, попробуйте позже."

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.booster_types = BOOSTER_TYPES
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info("LedgerManager initialized.")

    async def create_wallet(self, user_id: int, username: str) -> Wallet | None:
        """
        Creates a new wallet for a user with a startup bonus.
        Args:
            user_id: The user's Telegram ID.
            username: The user's Telegram username.
        Returns:
            A Wallet object if successful, None otherwise.
        """
        self.logger.info(f"Attempting to create wallet for user_id: {user_id}, username: {username}")
        try:
            success = await self.db_manager.execute_query(
                "INSERT INTO wallets (user_id, username, balance) VALUES (?, ?, ?)",
                (user_id, username, TokenConfig.STARTUP_BONUS)
            )
            if success:
                self.logger.info(f"Wallet created successfully for user_id: {user_id}")
                # Return a Wallet object. 'created_at' will be set by DB default.
                return Wallet(user_id=user_id, username=username, balance=TokenConfig.STARTUP_BONUS, created_at=datetime.now().isoformat())
            else:
                self.logger.error(f"Failed to execute query for wallet creation for user_id: {user_id}")
                return None
        except Exception as e:
            self.logger.error(f"Error in create_wallet for user {user_id}: {e}", exc_info=True)
            return None

    async def get_wallet(self, user_id: int) -> Wallet | None:
        """
        Retrieves a user's wallet.
        Args:
            user_id: The user's Telegram ID.
        Returns:
            A Wallet object if found, None otherwise.
        """
        # self.logger.debug(f"Fetching wallet for user_id: {user_id}") # Too verbose for INFO
        try:
            row = await self.db_manager.fetch_one("SELECT user_id, username, balance, created_at FROM wallets WHERE user_id = ?", (user_id,))
            if row:
                return Wallet(**row)
            return None
        except Exception as e:
            self.logger.error(f"Error in get_wallet for user {user_id}: {e}", exc_info=True)
            return None

    async def update_balance(self, user_id: int, amount: float) -> bool:
        """
        Updates a user's balance by a given amount (can be negative).
        Args:
            user_id: The user's Telegram ID.
            amount: The amount to add (or subtract if negative).
        Returns:
            True if successful, False otherwise.
        """
        self.logger.info(f"Updating balance for user {user_id} by amount {amount}")
        try:
            return await self.db_manager.execute_query(
                "UPDATE wallets SET balance = balance + ? WHERE user_id = ?",
                (amount, user_id)
            )
        except Exception as e:
            self.logger.error(f"Error in update_balance for user {user_id}: {e}", exc_info=True)
            return False


    async def execute_transfer(self, sender_id: int, receiver_id: int, amount: float) -> tuple[bool, str]:
        """
        Executes a token transfer between two users.
        Args:
            sender_id: The sender's Telegram ID.
            receiver_id: The receiver's Telegram ID.
            amount: The amount of HKN to transfer.
        Returns:
            A tuple (bool, str) indicating success and a message.
        """
        self.logger.info(f"Attempting transfer: {amount} HKN from {sender_id} to {receiver_id}")
        if amount <= 0:
            return False, "Сумма перевода должна быть положительной."

        try:
            sender_wallet = await self.get_wallet(sender_id)
            receiver_wallet = await self.get_wallet(receiver_id)

            if not sender_wallet:
                return False, "Кошелек отправителя не найден."
            if not receiver_wallet:
                return False, "Кошелек получателя не найден."
            if sender_wallet.balance < amount:
                return False, "Недостаточно средств на балансе отправителя."

            # Database transaction is handled by db_manager or explicitly here
            async with aiosqlite.connect(self.db_manager.db_path) as db: # Explicit transaction
                await db.execute("BEGIN TRANSACTION")
                try:
                    await db.execute("UPDATE wallets SET balance = balance - ? WHERE user_id = ?", (amount, sender_id))
                    await db.execute("UPDATE wallets SET balance = balance + ? WHERE user_id = ?", (amount, receiver_id))
                    await db.execute(
                        "INSERT INTO transactions (sender_id, receiver_id, amount, description) VALUES (?, ?, ?, ?)",
                        (sender_id, receiver_id, amount, "Перевод")
                    )
                    await db.commit()
                    self.logger.info(f"Transfer successful: {amount} HKN from {sender_id} to {receiver_id}")
                    return True, "Перевод успешно выполнен."
                except aiosqlite.Error as db_err: # Catch specific DB errors
                    await db.rollback()
                    self.logger.error(f"Database error during transfer from {sender_id} to {receiver_id}: {db_err}", exc_info=True)
                    return False, "Ошибка базы данных при переводе."
                except Exception as e_inner: # Catch other errors during transaction
                    await db.rollback()
                    self.logger.error(f"Unexpected error during transfer transaction from {sender_id} to {receiver_id}: {e_inner}", exc_info=True)
                    return False, self.GENERIC_ERROR_MESSAGE
        except Exception as e_outer: # Catch errors like get_wallet failing
            self.logger.error(f"Error in execute_transfer setup from {sender_id} to {receiver_id}: {e_outer}", exc_info=True)
            return False, self.GENERIC_ERROR_MESSAGE


    async def get_token_info(self) -> Token | None:
        """Retrieves the global token information."""
        try:
            row = await self.db_manager.fetch_one("SELECT name, symbol, decimals, total_supply, current_price FROM token_info WHERE id = 1")
            return Token(**row) if row else None
        except Exception as e:
            self.logger.error(f"Error in get_token_info: {e}", exc_info=True)
            return None

    async def calculate_market_cap(self) -> float:
        """Calculates the current market capitalization of the token."""
        try:
            token_info_obj = await self.get_token_info()
            if not token_info_obj:
                self.logger.warning("Token info not found for market cap calculation.")
                return 0.0
            return token_info_obj.total_supply * token_info_obj.current_price
        except Exception as e:
            self.logger.error(f"Error in calculate_market_cap: {e}", exc_info=True)
            return 0.0

    async def set_token_price(self, new_price: float) -> bool:
        """
        Sets the global token price (admin function).
        Args:
            new_price: The new price for HKN.
        Returns:
            True if successful, False otherwise.
        """
        self.logger.info(f"Admin attempting to set token price to {new_price}")
        if new_price <= 0: return False # Price must be positive
        try:
            return await self.db_manager.execute_query(
                "UPDATE token_info SET current_price = ? WHERE id = 1",
                (new_price,)
            )
        except Exception as e:
            self.logger.error(f"Error in set_token_price: {e}", exc_info=True)
            return False


    async def mint_tokens(self, user_id: int, amount: float) -> bool:
        """
        Mints new tokens to a user's wallet and updates total supply (admin function).
        Args:
            user_id: The user's Telegram ID to receive minted tokens.
            amount: The amount of HKN to mint.
        Returns:
            True if successful, False otherwise.
        """
        self.logger.info(f"Admin attempting to mint {amount} HKN for user {user_id}")
        if amount <= 0: return False
        try:
            wallet = await self.get_wallet(user_id)
            if not wallet: self.logger.warning(f"Minting target wallet not found for user {user_id}."); return False

            current_token_info = await self.get_token_info()
            if not current_token_info: self.logger.error("Failed to get token_info for minting."); return False

            new_total_supply = current_token_info.total_supply + amount

            async with aiosqlite.connect(self.db_manager.db_path) as db:
                await db.execute("BEGIN TRANSACTION")
                try:
                    await db.execute("UPDATE wallets SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
                    await db.execute("UPDATE token_info SET total_supply = ? WHERE id = 1", (new_total_supply,))
                    await db.execute(
                        "INSERT INTO transactions (sender_id, receiver_id, amount, description) VALUES (?, ?, ?, ?)",
                        (0, user_id, amount, "Эмиссия токенов администратором")
                    )
                    await db.commit()
                    self.logger.info(f"Successfully minted {amount} HKN for user {user_id}. New total supply: {new_total_supply}")
                    return True
                except aiosqlite.Error as db_err:
                    await db.rollback()
                    self.logger.error(f"Database error during mint_tokens for user {user_id}: {db_err}", exc_info=True)
                    return False
                except Exception as e_inner:
                    await db.rollback()
                    self.logger.error(f"Unexpected error in mint_tokens transaction for user {user_id}: {e_inner}", exc_info=True)
                    return False
        except Exception as e_outer:
            self.logger.error(f"Error in mint_tokens setup for user {user_id}: {e_outer}", exc_info=True)
            return False

    async def get_transaction_history(self, user_id: int, limit: int = 5, offset: int = 0) -> list[Transaction] | None:
        """
        Retrieves a user's transaction history.
        Args:
            user_id: The user's Telegram ID.
            limit: Max number of transactions to return.
            offset: Offset for pagination.
        Returns:
            A list of Transaction objects, or None on error.
        """
        try:
            rows = await self.db_manager.fetch_all(
                """
                SELECT id, timestamp, sender_id, receiver_id, amount, description FROM transactions
                WHERE sender_id = ? OR receiver_id = ?
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
                """,
                (user_id, user_id, limit, offset)
            )
            return [Transaction(**row) for row in rows] if rows is not None else [] # Return empty list if rows is None
        except Exception as e:
            self.logger.error(f"Error in get_transaction_history for user {user_id}: {e}", exc_info=True)
            return None


    # --- Staking Methods ---
    def calculate_rewards(self, stake_amount: float, start_time: datetime, end_time: datetime, booster_multiplier: float) -> float:
        """Calculates staking rewards based on amount, duration, and multiplier."""
        # self.logger.debug(f"Calculating rewards: amount={stake_amount}, start={start_time}, end={end_time}, multiplier={booster_multiplier}")
        if not isinstance(start_time, datetime) or not isinstance(end_time, datetime):
            self.logger.error("Invalid datetime objects for reward calculation.")
            raise ValueError("start_time and end_time must be datetime objects")
        duration_seconds = (end_time - start_time).total_seconds()
        if duration_seconds < 0: duration_seconds = 0
        duration_hours = duration_seconds / 3600.0
        reward = stake_amount * (duration_hours * BASE_HOURLY_REWARD_RATE) * booster_multiplier
        return reward

    async def get_active_booster_multiplier(self, user_id: int, booster_type_prefix: str = "speed") -> float:
        """Gets the active booster multiplier for a user and booster type prefix."""
        # self.logger.debug(f"Fetching active booster for user {user_id}, prefix {booster_type_prefix}")
        try:
            query = """
                SELECT effect_multiplier FROM active_boosters
                WHERE user_id = ? AND booster_type LIKE ? AND active_until > ?
                ORDER BY effect_multiplier DESC LIMIT 1
            """
            row = await self.db_manager.fetch_one(query, (user_id, f"{booster_type_prefix}%", datetime.now()))
            return float(row['effect_multiplier']) if row else 1.0
        except Exception as e:
            self.logger.error(f"Error in get_active_booster_multiplier for user {user_id}: {e}", exc_info=True)
            return 1.0 # Default to no multiplier on error


    async def stake_tokens(self, user_id: int, amount: float) -> tuple[bool, str]:
        """
        Allows a user to stake their HKN.
        Args:
            user_id: The user's Telegram ID.
            amount: The amount of HKN to stake.
        Returns:
            A tuple (bool, str) indicating success and a message.
        """
        self.logger.info(f"User {user_id} attempting to stake {amount} HKN.")
        if amount <= 0: return False, "Сумма для стейкинга должна быть положительной."
        try:
            wallet = await self.get_wallet(user_id)
            if not wallet: return False, "Кошелек не найден."
            if wallet.balance < amount: return False, f"Недостаточно средств. Ваш баланс: {wallet.balance:.{TokenConfig.DECIMALS}f} HKN."

            async with aiosqlite.connect(self.db_manager.db_path) as db:
                await db.execute("BEGIN TRANSACTION")
                try:
                    await db.execute("UPDATE wallets SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
                    current_time = datetime.now()
                    await db.execute(
                        "INSERT INTO stakes (user_id, amount, created_at, last_claimed_at) VALUES (?, ?, ?, ?)",
                        (user_id, amount, current_time, current_time)
                    )
                    await db.commit()
                    self.logger.info(f"User {user_id} successfully staked {amount} HKN.")
                    return True, f"{amount:.{TokenConfig.DECIMALS}f} HKN успешно поставлены на стейк!"
                except aiosqlite.Error as db_err:
                    await db.rollback()
                    self.logger.error(f"Database error during stake_tokens for user {user_id}: {db_err}", exc_info=True)
                    return False, "Ошибка базы данных при стейкинге."
                except Exception as e_inner:
                    await db.rollback()
                    self.logger.error(f"Unexpected error in stake_tokens transaction for user {user_id}: {e_inner}", exc_info=True)
                    return False, self.GENERIC_ERROR_MESSAGE
        except Exception as e_outer:
            self.logger.error(f"Error in stake_tokens setup for user {user_id}: {e_outer}", exc_info=True)
            return False, self.GENERIC_ERROR_MESSAGE

    async def get_user_stakes(self, user_id: int) -> list[dict] | None:
        """
        Retrieves all active stakes for a user, along with pending rewards.
        Args:
            user_id: The user's Telegram ID.
        Returns:
            A list of dictionaries, each representing a stake and its pending rewards, or None on error.
        """
        # self.logger.debug(f"Fetching stakes for user {user_id}")
        try:
            stakes_rows = await self.db_manager.fetch_all("SELECT stake_id, amount, created_at, last_claimed_at FROM stakes WHERE user_id = ?", (user_id,))
            if stakes_rows is None: return None # Error in fetch_all

            result_stakes = []
            booster_multiplier = await self.get_active_booster_multiplier(user_id, booster_type_prefix="speed_staking")
            current_time = datetime.now()

            for row_dict in stakes_rows:
                created_at_dt = datetime.fromisoformat(row_dict['created_at']) if isinstance(row_dict['created_at'], str) else row_dict['created_at']
                last_claimed_at_dt = datetime.fromisoformat(row_dict['last_claimed_at']) if isinstance(row_dict['last_claimed_at'], str) else row_dict['last_claimed_at']
                pending_rewards = self.calculate_rewards(row_dict['amount'], last_claimed_at_dt, current_time, booster_multiplier)
                result_stakes.append({
                    'stake_id': row_dict['stake_id'],
                    'amount': row_dict['amount'],
                    'created_at': created_at_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    'last_claimed_at': last_claimed_at_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    'pending_rewards': pending_rewards
                })
            return result_stakes
        except Exception as e:
            self.logger.error(f"Error in get_user_stakes for user {user_id}: {e}", exc_info=True)
            return None


    async def _calculate_and_update_rewards(self, stake_id: int, for_unstake: bool = False) -> tuple | None:
        """Helper to calculate rewards and optionally update last_claimed_at."""
        # self.logger.debug(f"Calculating rewards for stake_id {stake_id}, for_unstake={for_unstake}")
        try:
            stake_row = await self.db_manager.fetch_one("SELECT user_id, amount, last_claimed_at FROM stakes WHERE stake_id = ?", (stake_id,))
            if not stake_row: return None

            user_id, staked_amount, last_claimed_at_val = stake_row['user_id'], stake_row['amount'], stake_row['last_claimed_at']
            last_claimed_at_dt = datetime.fromisoformat(last_claimed_at_val) if isinstance(last_claimed_at_val, str) else last_claimed_at_val
            current_time = datetime.now()
            booster_multiplier = await self.get_active_booster_multiplier(user_id, booster_type_prefix="speed_staking")
            rewards = self.calculate_rewards(staked_amount, last_claimed_at_dt, current_time, booster_multiplier)

            if rewards > 0 and not for_unstake:
                if not await self.db_manager.execute_query("UPDATE stakes SET last_claimed_at = ? WHERE stake_id = ?", (current_time, stake_id)):
                    self.logger.error(f"Failed to update last_claimed_at for stake {stake_id} during reward calculation.")
                    # Decide if this should prevent reward distribution or just be logged.
                    # For now, it's logged, and reward calculation proceeds.

            return user_id, staked_amount, rewards, current_time
        except Exception as e:
            self.logger.error(f"Error in _calculate_and_update_rewards for stake {stake_id}: {e}", exc_info=True)
            return None


    async def claim_rewards(self, user_id: int, stake_id: int) -> tuple[bool, str]:
        """
        Claims pending rewards for a specific stake.
        Args:
            user_id: The user's Telegram ID claiming the rewards.
            stake_id: The ID of the stake.
        Returns:
            A tuple (bool, str) indicating success and a message.
        """
        self.logger.info(f"User {user_id} attempting to claim rewards for stake {stake_id}")
        try:
            calculation_result = await self._calculate_and_update_rewards(stake_id, for_unstake=False)
            if not calculation_result: return False, "Стейк не найден."

            s_user_id, _, calculated_rewards, _ = calculation_result
            if s_user_id != user_id: return False, "Этот стейк вам не принадлежит."
            if calculated_rewards <= 0: return False, "Нет доступных наград для получения."

            async with aiosqlite.connect(self.db_manager.db_path) as db:
                await db.execute("BEGIN TRANSACTION")
                try:
                    await db.execute("UPDATE wallets SET balance = balance + ? WHERE user_id = ?", (calculated_rewards, user_id))
                    await db.execute(
                        "INSERT INTO transactions (sender_id, receiver_id, amount, description) VALUES (?, ?, ?, ?)",
                        (0, user_id, calculated_rewards, f"Награда за стейкинг (ID: {stake_id})")
                    )
                    await db.commit()
                    self.logger.info(f"User {user_id} successfully claimed {calculated_rewards} HKN from stake {stake_id}")
                    return True, f"Вы успешно получили {calculated_rewards:.{TokenConfig.DECIMALS}f} HKN награды!"
                except aiosqlite.Error as db_err:
                    await db.rollback()
                    self.logger.error(f"Database error during claim_rewards for user {user_id}, stake {stake_id}: {db_err}", exc_info=True)
                    return False, "Ошибка базы данных при зачислении наград."
                except Exception as e_inner:
                    await db.rollback()
                    self.logger.error(f"Unexpected error in claim_rewards transaction for user {user_id}, stake {stake_id}: {e_inner}", exc_info=True)
                    return False, self.GENERIC_ERROR_MESSAGE
        except Exception as e_outer:
            self.logger.error(f"Error in claim_rewards setup for user {user_id}, stake {stake_id}: {e_outer}", exc_info=True)
            return False, self.GENERIC_ERROR_MESSAGE


    async def unstake_tokens(self, user_id: int, stake_id: int) -> tuple[bool, str]:
        """
        Unstakes tokens, returning the principal and any pending rewards.
        Args:
            user_id: The user's Telegram ID.
            stake_id: The ID of the stake to unstake.
        Returns:
            A tuple (bool, str) indicating success and a message.
        """
        self.logger.info(f"User {user_id} attempting to unstake stake_id {stake_id}")
        try:
            calculation_result = await self._calculate_and_update_rewards(stake_id, for_unstake=True)
            if not calculation_result: return False, "Стейк не найден."

            s_user_id, staked_amount, calculated_rewards, _ = calculation_result
            if s_user_id != user_id: return False, "Этот стейк вам не принадлежит."

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
                    self.logger.info(f"User {user_id} successfully unstaked {staked_amount} HKN (plus {calculated_rewards} rewards) from stake {stake_id}")
                    return True, f"Вы успешно сняли {staked_amount:.{TokenConfig.DECIMALS}f} HKN со стейка. Получено наград: {calculated_rewards:.{TokenConfig.DECIMALS}f} HKN."
                except aiosqlite.Error as db_err:
                    await db.rollback()
                    self.logger.error(f"Database error during unstake_tokens for user {user_id}, stake {stake_id}: {db_err}", exc_info=True)
                    return False, "Ошибка базы данных при анстейкинге."
                except Exception as e_inner:
                    await db.rollback()
                    self.logger.error(f"Unexpected error in unstake_tokens transaction for user {user_id}, stake {stake_id}: {e_inner}", exc_info=True)
                    return False, self.GENERIC_ERROR_MESSAGE
        except Exception as e_outer:
            self.logger.error(f"Error in unstake_tokens setup for user {user_id}, stake {stake_id}: {e_outer}", exc_info=True)
            return False, self.GENERIC_ERROR_MESSAGE

    # --- Booster Methods ---
    async def buy_booster(self, user_id: int, booster_key: str) -> tuple[bool, str]:
        """
        Allows a user to buy a booster.
        Args:
            user_id: The user's Telegram ID.
            booster_key: The key identifying the booster in BOOSTER_TYPES.
        Returns:
            A tuple (bool, str) indicating success and a message.
        """
        self.logger.info(f"User {user_id} attempting to buy booster: {booster_key}")
        if booster_key not in self.booster_types:
            self.logger.warning(f"Invalid booster_key '{booster_key}' attempt by user {user_id}")
            return False, "Неверный тип ускорителя."

        booster_config = self.booster_types[booster_key]
        cost = booster_config['cost']
        try:
            wallet = await self.get_wallet(user_id)
            if not wallet: return False, "Кошелек не найден."
            if wallet.balance < cost: return False, f"Недостаточно HKN. Нужно {cost:.{TokenConfig.DECIMALS}f}, у вас {wallet.balance:.{TokenConfig.DECIMALS}f}."

            active_until = datetime.now() + timedelta(hours=booster_config['duration_hours'])
            async with aiosqlite.connect(self.db_manager.db_path) as db:
                await db.execute("BEGIN TRANSACTION")
                try:
                    await db.execute("UPDATE wallets SET balance = balance - ? WHERE user_id = ?", (cost, user_id))
                    if booster_key.startswith("speed"): # Overwrite logic for speed boosters
                        await db.execute("DELETE FROM active_boosters WHERE user_id = ? AND booster_type LIKE 'speed%'", (user_id,))
                    await db.execute(
                        "INSERT INTO active_boosters (user_id, booster_type, active_until, effect_multiplier) VALUES (?, ?, ?, ?)",
                        (user_id, booster_key, active_until, booster_config['multiplier'])
                    )
                    await db.execute(
                        "INSERT INTO transactions (sender_id, receiver_id, amount, description) VALUES (?, ?, ?, ?)",
                        (user_id, 0, cost, f"Покупка ускорителя: {booster_config['name_ru']}")
                    )
                    await db.commit()
                    self.logger.info(f"User {user_id} successfully bought booster {booster_key}")
                    return True, f"Ускоритель '{booster_config['name_ru']}' успешно куплен и активирован!"
                except aiosqlite.Error as db_err:
                    await db.rollback()
                    self.logger.error(f"Database error during buy_booster for user {user_id}, booster {booster_key}: {db_err}", exc_info=True)
                    return False, "Ошибка базы данных при покупке ускорителя."
                except Exception as e_inner:
                    await db.rollback()
                    self.logger.error(f"Unexpected error in buy_booster transaction for user {user_id}, booster {booster_key}: {e_inner}", exc_info=True)
                    return False, self.GENERIC_ERROR_MESSAGE
        except Exception as e_outer:
            self.logger.error(f"Error in buy_booster setup for user {user_id}, booster {booster_key}: {e_outer}", exc_info=True)
            return False, self.GENERIC_ERROR_MESSAGE

    def get_available_boosters_info(self) -> dict:
        """Returns a copy of BOOSTER_TYPES for display purposes."""
        return self.booster_types.copy()

    async def sell_hkn_to_system(self, user_id: int, amount_hkn: float) -> tuple[bool, str]:
        """
        Allows a user to sell HKN to the system at a fixed rate.
        Args:
            user_id: The user's Telegram ID.
            amount_hkn: The amount of HKN to sell.
        Returns:
            A tuple (bool, str) indicating success and a message.
        """
        self.logger.info(f"User {user_id} attempting to sell {amount_hkn} HKN to system.")
        if amount_hkn <= 0: return False, "Сумма HKN должна быть положительной."
        try:
            wallet = await self.get_wallet(user_id)
            if not wallet: return False, "Кошелек не найден."
            if wallet.balance < amount_hkn: return False, f"Недостаточно HKN. Ваш баланс: {wallet.balance:.{TokenConfig.DECIMALS}f}."

            received_bot_usd = amount_hkn * self.HKN_SELL_RATE_TO_BOTUSD
            async with aiosqlite.connect(self.db_manager.db_path) as db:
                await db.execute("BEGIN TRANSACTION")
                try:
                    await db.execute("UPDATE wallets SET balance = balance - ? WHERE user_id = ?", (amount_hkn, user_id))
                    description = (f"Продажа {amount_hkn:.{TokenConfig.DECIMALS}f} HKN системе "
                                   f"за {received_bot_usd:.{TokenConfig.DECIMALS}f} BotUSD")
                    await db.execute(
                        "INSERT INTO transactions (sender_id, receiver_id, amount, description) VALUES (?, ?, ?, ?)",
                        (user_id, 0, amount_hkn, description)
                    )
                    await db.commit()
                    self.logger.info(f"User {user_id} successfully sold {amount_hkn} HKN for {received_bot_usd} BotUSD.")
                    return True, (f"Вы успешно продали {amount_hkn:.{TokenConfig.DECIMALS}f} HKN и получили "
                                  f"{received_bot_usd:.{TokenConfig.DECIMALS}f} BotUSD (концептуально).")
                except aiosqlite.Error as db_err:
                    await db.rollback()
                    self.logger.error(f"Database error during sell_hkn for user {user_id}: {db_err}", exc_info=True)
                    return False, "Ошибка базы данных при продаже HKN."
                except Exception as e_inner:
                    await db.rollback()
                    self.logger.error(f"Unexpected error in sell_hkn transaction for user {user_id}: {e_inner}", exc_info=True)
                    return False, self.GENERIC_ERROR_MESSAGE
        except Exception as e_outer:
            self.logger.error(f"Error in sell_hkn_to_system setup for user {user_id}: {e_outer}", exc_info=True)
            return False, self.GENERIC_ERROR_MESSAGE
