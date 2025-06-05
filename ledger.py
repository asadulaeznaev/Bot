import aiosqlite
from database import DatabaseManager
from models import Wallet, Token, Transaction
from config import TokenConfig

class LedgerManager:
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

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
                await db.execute("UPDATE wallets SET balance = balance + ? WHERE user_id = ?", (-amount, sender_id))
                await db.execute("UPDATE wallets SET balance = balance + ? WHERE user_id = ?", (amount, receiver_id))
                await db.execute(
                    "INSERT INTO transactions (sender_id, receiver_id, amount) VALUES (?, ?, ?)",
                    (sender_id, receiver_id, amount)
                )
                await db.commit()
                return True
            except Exception:
                await db.rollback()
                return False

    async def get_token_info(self) -> Token:
        row = await self.db_manager.fetch_one("SELECT * FROM token_info WHERE id = 1")
        return Token(**row)

    async def calculate_market_cap(self) -> float:
        token_info_obj = await self.get_token_info()
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
