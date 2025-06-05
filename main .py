import os
import asyncio
# Removed aiosqlite and dataclass as they are no longer directly used in main .py
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
# Removed State, StatesGroup as they are in bot_states.py
from telebot.asyncio_filters import StateFilter

# Imports from new modules
from config import BotConfig, TokenConfig
# from models import Token, Wallet, Transaction # Removed as they are not directly used in main.py
from database import DatabaseManager
from ledger import LedgerManager
from bot_states import UserStates

class BotApp:
    def __init__(self, token: str, admin_ids: list[int], ledger_manager: LedgerManager):
        self.bot = AsyncTeleBot(token)
        self.admin_ids = admin_ids
        self.ledger_manager = ledger_manager
        # Make sure TokenConfig is available for formatting strings
        self.token_config = TokenConfig()
        self.bot.add_custom_filter(StateFilter(self.bot))
        self._register_handlers()

    def _main_menu_keyboard(self):
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("💰 Мой Баланс", callback_data="show_balance"))
        markup.row(InlineKeyboardButton("💸 Отправить HKN", callback_data="send_hkn"))
        markup.row(InlineKeyboardButton("ℹ️ О Токене", callback_data="token_info"))
        return markup

    def _balance_menu_keyboard(self):
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("🔄 Обновить", callback_data="show_balance"))
        markup.row(InlineKeyboardButton("💸 Отправить HKN", callback_data="send_hkn"))
        markup.row(InlineKeyboardButton("📜 История", callback_data="show_history"))
        return markup

    def _token_info_keyboard(self):
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("📊 Капитализация", callback_data="show_marketcap"))
        markup.row(InlineKeyboardButton("💰 Главное меню", callback_data="main_menu"))
        return markup

    def _confirm_send_keyboard(self):
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_send"),
                   InlineKeyboardButton("❌ Отмена", callback_data="cancel_send"))
        return markup

    async def _is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids

    def _register_handlers(self):
        self.bot.message_handler(commands=['start'])(self.handle_start)
        self.bot.message_handler(commands=['balance'])(self.handle_balance_command)
        self.bot.message_handler(commands=['tokeninfo'])(self.handle_token_info_command)
        self.bot.message_handler(commands=['marketcap'])(self.handle_market_cap_command)
        self.bot.message_handler(commands=['send'])(self.handle_send_command)
        self.bot.message_handler(commands=['setprice'])(self.handle_admin_set_price_command)
        self.bot.message_handler(commands=['mint'])(self.handle_admin_mint_command)
        self.bot.message_handler(commands=['history'])(self.handle_history_command)

        self.bot.callback_query_handler(func=lambda call: call.data == 'show_balance')(self.handle_show_balance_callback)
        self.bot.callback_query_handler(func=lambda call: call.data == 'send_hkn')(self.handle_send_hkn_callback)
        self.bot.callback_query_handler(func=lambda call: call.data == 'token_info')(self.handle_token_info_callback)
        self.bot.callback_query_handler(func=lambda call: call.data == 'show_marketcap')(self.handle_market_cap_callback)
        self.bot.callback_query_handler(func=lambda call: call.data == 'main_menu')(self.handle_main_menu_callback)
        self.bot.callback_query_handler(func=lambda call: call.data in ['confirm_send', 'cancel_send'])(self.handle_send_confirmation_callback)
        self.bot.callback_query_handler(func=lambda call: call.data.startswith('history_page_'))(self.handle_history_pagination_callback)

        self.bot.message_handler(state=UserStates.WAITING_FOR_RECIPIENT)(self.handle_waiting_for_recipient)
        self.bot.message_handler(state=UserStates.WAITING_FOR_AMOUNT)(self.handle_waiting_for_amount)
        self.bot.message_handler(state=UserStates.ADMIN_SET_PRICE)(self.handle_admin_set_price_input)
        self.bot.message_handler(state=UserStates.ADMIN_MINT_RECIPIENT)(self.handle_admin_mint_recipient_input)
        self.bot.message_handler(state=UserStates.ADMIN_MINT_AMOUNT)(self.handle_admin_mint_amount_input)

    async def handle_start(self, message):
        user_id = message.from_user.id
        username = message.from_user.username
        wallet = await self.ledger_manager.get_wallet(user_id)
        if not wallet:
            await self.ledger_manager.create_wallet(user_id, username)
            await self.bot.send_message(user_id,
                                        f"Добро пожаловать в HelgyKoin! "
                                        f"Ваш кошелек создан, и вы получили {self.token_config.STARTUP_BONUS:.{self.token_config.DECIMALS}f} {self.token_config.SYMBOL} в качестве стартового бонуса.",
                                        reply_markup=self._main_menu_keyboard())
        else:
            await self.bot.send_message(user_id, "Снова здравствуйте!", reply_markup=self._main_menu_keyboard())

    async def handle_balance_command(self, message):
        await self._show_balance(message.chat.id, message.from_user.id)

    async def handle_show_balance_callback(self, call):
        await self.bot.answer_callback_query(call.id)
        await self._show_balance(call.message.chat.id, call.from_user.id, call.message.message_id)

    async def _show_balance(self, chat_id, user_id, message_id=None):
        wallet = await self.ledger_manager.get_wallet(user_id)
        if wallet:
            balance_str = f"Ваш баланс: `{wallet.balance:.{self.token_config.DECIMALS}f} {self.token_config.SYMBOL}`"
            if message_id:
                await self.bot.edit_message_text(balance_str, chat_id, message_id, reply_markup=self._balance_menu_keyboard(), parse_mode='Markdown')
            else:
                await self.bot.send_message(chat_id, balance_str, reply_markup=self._balance_menu_keyboard(), parse_mode='Markdown')
        else:
            await self.bot.send_message(chat_id, "Ваш кошелек не найден. Пожалуйста, используйте /start для регистрации.", reply_markup=self._main_menu_keyboard())

    async def handle_send_command(self, message):
        args = message.text.split()
        if len(args) == 3:
            recipient_str = args[1]
            amount_str = args[2]
            await self._process_send_direct(message, recipient_str, amount_str)
        else:
            await self.bot.send_message(message.chat.id, "Для перевода укажите получателя (username или ID) и сумму. Пример: `/send @username 100` или `/send 123456789 100`", parse_mode='Markdown')
            await self.bot.set_state(message.from_user.id, UserStates.WAITING_FOR_RECIPIENT, message.chat.id)
            await self.bot.send_message(message.chat.id, "Введите Telegram ID или username получателя:")

    async def handle_send_hkn_callback(self, call):
        await self.bot.answer_callback_query(call.id)
        await self.bot.set_state(call.from_user.id, UserStates.WAITING_FOR_RECIPIENT, call.message.chat.id)
        await self.bot.send_message(call.message.chat.id, "Введите Telegram ID или username получателя:")

    async def handle_waiting_for_recipient(self, message):
        chat_id = message.chat.id
        user_id = message.from_user.id
        recipient_str = message.text.strip()

        try:
            recipient_id = int(recipient_str)
        except ValueError:
            if recipient_str.startswith('@'):
                recipient_username = recipient_str[1:]
                recipient_wallet = await self.ledger_manager.db_manager.fetch_one("SELECT user_id FROM wallets WHERE username = ?", (recipient_username,))
                if recipient_wallet:
                    recipient_id = recipient_wallet['user_id']
                else:
                    await self.bot.send_message(chat_id, "Пользователь с таким username не найден. Пожалуйста, попробуйте еще раз или введите ID:")
                    return
            else:
                await self.bot.send_message(chat_id, "Неверный формат получателя. Пожалуйста, введите корректный Telegram ID или username:")
                return

        if recipient_id == user_id:
            await self.bot.send_message(chat_id, "Вы не можете отправить токены самому себе. Пожалуйста, введите другого получателя:")
            return

        recipient_wallet_exists = await self.ledger_manager.get_wallet(recipient_id)
        if not recipient_wallet_exists:
            await self.bot.send_message(chat_id, "Кошелек получателя не существует. Пожалуйста, попробуйте еще раз или введите ID:")
            return

        async with self.bot.retrieve_data(user_id, chat_id) as data:
            data['recipient_id'] = recipient_id
        await self.bot.set_state(user_id, UserStates.WAITING_FOR_AMOUNT, chat_id)
        await self.bot.send_message(chat_id, "Введите сумму для перевода:")

    async def handle_waiting_for_amount(self, message):
        chat_id = message.chat.id
        user_id = message.from_user.id
        amount_str = message.text.strip()

        try:
            amount = float(amount_str)
            if amount <= 0:
                raise ValueError
        except ValueError:
            await self.bot.send_message(chat_id, "Неверный формат суммы. Пожалуйста, введите положительное число:")
            return

        async with self.bot.retrieve_data(user_id, chat_id) as data:
            recipient_id = data.get('recipient_id')
            data['amount'] = amount

        sender_wallet = await self.ledger_manager.get_wallet(user_id)
        if not sender_wallet or sender_wallet.balance < amount:
            await self.bot.send_message(chat_id, "Недостаточно средств на вашем балансе. Пожалуйста, введите меньшую сумму или отмените операцию.")
            await self.bot.delete_state(user_id, chat_id)
            return

        recipient_wallet = await self.ledger_manager.get_wallet(recipient_id)
        recipient_info = recipient_wallet.username if recipient_wallet and recipient_wallet.username else str(recipient_id)

        await self.bot.send_message(chat_id,
                                    f"Подтвердите перевод `{amount:.{self.token_config.DECIMALS}f} {self.token_config.SYMBOL}` пользователю *{recipient_info}*?",
                                    reply_markup=self._confirm_send_keyboard(), parse_mode='Markdown')
        await self.bot.set_state(user_id, UserStates.CONFIRMING_SEND, chat_id)

    async def handle_send_confirmation_callback(self, call):
        await self.bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        user_id = call.from_user.id

        if call.data == 'confirm_send':
            async with self.bot.retrieve_data(user_id, chat_id) as data:
                recipient_id = data.get('recipient_id')
                amount = data.get('amount')

            success = await self.ledger_manager.execute_transfer(user_id, recipient_id, amount)
            if success:
                recipient_wallet = await self.ledger_manager.get_wallet(recipient_id)
                recipient_info = recipient_wallet.username if recipient_wallet and recipient_wallet.username else str(recipient_id)
                await self.bot.edit_message_text(f"Перевод `{amount:.{self.token_config.DECIMALS}f} {self.token_config.SYMBOL}` пользователю *{recipient_info}* успешно выполнен.",
                                                 chat_id, call.message.message_id, parse_mode='Markdown', reply_markup=self._main_menu_keyboard())
            else:
                await self.bot.edit_message_text("Ошибка при выполнении перевода. Пожалуйста, убедитесь, что у вас достаточно средств и получатель существует.",
                                                 chat_id, call.message.message_id, reply_markup=self._main_menu_keyboard())
        else:
            await self.bot.edit_message_text("Перевод отменен.", chat_id, call.message.message_id, reply_markup=self._main_menu_keyboard())

        await self.bot.delete_state(user_id, chat_id)

    async def _process_send_direct(self, message, recipient_str, amount_str):
        user_id = message.from_user.id
        chat_id = message.chat.id

        try:
            recipient_id = int(recipient_str)
        except ValueError:
            if recipient_str.startswith('@'):
                recipient_username = recipient_str[1:]
                recipient_wallet = await self.ledger_manager.db_manager.fetch_one("SELECT user_id FROM wallets WHERE username = ?", (recipient_username,))
                if recipient_wallet:
                    recipient_id = recipient_wallet['user_id']
                else:
                    await self.bot.send_message(chat_id, "Пользователь с таким username не найден.")
                    return
            else:
                await self.bot.send_message(chat_id, "Неверный формат получателя.")
                return

        try:
            amount = float(amount_str)
            if amount <= 0:
                raise ValueError
        except ValueError:
            await self.bot.send_message(chat_id, "Неверный формат суммы.")
            return

        if recipient_id == user_id:
            await self.bot.send_message(chat_id, "Вы не можете отправить токены самому себе.")
            return

        sender_wallet = await self.ledger_manager.get_wallet(user_id)
        if not sender_wallet or sender_wallet.balance < amount:
            await self.bot.send_message(chat_id, "Недостаточно средств на вашем балансе.")
            return

        recipient_wallet_exists = await self.ledger_manager.get_wallet(recipient_id)
        if not recipient_wallet_exists:
            await self.bot.send_message(chat_id, "Кошелек получателя не существует.")
            return

        async with self.bot.retrieve_data(user_id, chat_id) as data:
            data['recipient_id'] = recipient_id
            data['amount'] = amount

        recipient_info = recipient_wallet_exists.username if recipient_wallet_exists.username else str(recipient_id)

        await self.bot.send_message(chat_id,
                                    f"Подтвердите перевод `{amount:.{self.token_config.DECIMALS}f} {self.token_config.SYMBOL}` пользователю *{recipient_info}*?",
                                    reply_markup=self._confirm_send_keyboard(), parse_mode='Markdown')
        await self.bot.set_state(user_id, UserStates.CONFIRMING_SEND, chat_id)

    async def handle_token_info_command(self, message):
        await self._show_token_info(message.chat.id, message.message_id)

    async def handle_token_info_callback(self, call):
        await self.bot.answer_callback_query(call.id)
        await self._show_token_info(call.message.chat.id, call.message.message_id)

    async def _show_token_info(self, chat_id, message_id=None):
        token_info_obj = await self.ledger_manager.get_token_info()
        info_message = (
            f"**Информация о токене {token_info_obj.name}:**\n"
            f"Символ: `{token_info_obj.symbol}`\n"
            f"Десятичные знаки: `{token_info_obj.decimals}`\n"
            f"Общее предложение: `{token_info_obj.total_supply:.{token_info_obj.decimals}f} {token_info_obj.symbol}`\n"
            f"Текущая цена: `${token_info_obj.current_price:.{self.token_config.DECIMALS}f}`"
        )
        if message_id:
            await self.bot.edit_message_text(info_message, chat_id, message_id, parse_mode='Markdown', reply_markup=self._token_info_keyboard())
        else:
            await self.bot.send_message(chat_id, info_message, parse_mode='Markdown', reply_markup=self._token_info_keyboard())

    async def handle_market_cap_command(self, message):
        await self._show_market_cap(message.chat.id, message.message_id)

    async def handle_market_cap_callback(self, call):
        await self.bot.answer_callback_query(call.id)
        await self._show_market_cap(call.message.chat.id, call.message.message_id)

    async def _show_market_cap(self, chat_id, message_id=None):
        market_cap = await self.ledger_manager.calculate_market_cap()
        cap_message = f"Текущая рыночная капитализация {self.token_config.SYMBOL}: `${market_cap:.2f}`"
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("ℹ️ О Токене", callback_data="token_info"))
        markup.row(InlineKeyboardButton("💰 Главное меню", callback_data="main_menu"))
        if message_id:
            await self.bot.edit_message_text(cap_message, chat_id, message_id, parse_mode='Markdown', reply_markup=markup)
        else:
            await self.bot.send_message(chat_id, cap_message, parse_mode='Markdown', reply_markup=markup)

    async def handle_main_menu_callback(self, call):
        await self.bot.answer_callback_query(call.id)
        await self.bot.edit_message_text("Главное меню:", call.message.chat.id, call.message.message_id, reply_markup=self._main_menu_keyboard())

    async def handle_admin_set_price_command(self, message):
        if not await self._is_admin(message.from_user.id):
            await self.bot.send_message(message.chat.id, "У вас нет прав для выполнения этой команды.")
            return
        await self.bot.set_state(message.from_user.id, UserStates.ADMIN_SET_PRICE, message.chat.id)
        await self.bot.send_message(message.chat.id, "Введите новую цену для HKN (например, 0.0001):")

    async def handle_admin_set_price_input(self, message):
        user_id = message.from_user.id
        chat_id = message.chat.id
        try:
            new_price = float(message.text.strip())
            if new_price <= 0:
                raise ValueError
            await self.ledger_manager.set_token_price(new_price)
            await self.bot.send_message(chat_id, f"Новая цена HKN установлена: `${new_price:.{self.token_config.DECIMALS}f}`")
        except ValueError:
            await self.bot.send_message(chat_id, "Неверный формат цены. Пожалуйста, введите положительное число.")
        finally:
            await self.bot.delete_state(user_id, chat_id)
            await self.bot.send_message(chat_id, "Операция завершена.", reply_markup=self._main_menu_keyboard())

    async def handle_admin_mint_command(self, message):
        if not await self._is_admin(message.from_user.id):
            await self.bot.send_message(message.chat.id, "У вас нет прав для выполнения этой команды.")
            return
        await self.bot.set_state(message.from_user.id, UserStates.ADMIN_MINT_RECIPIENT, message.chat.id)
        await self.bot.send_message(message.chat.id, "Введите Telegram ID получателя для эмиссии:")

    async def handle_admin_mint_recipient_input(self, message):
        user_id = message.from_user.id
        chat_id = message.chat.id
        recipient_str = message.text.strip()
        try:
            recipient_id = int(recipient_str)
            recipient_wallet = await self.ledger_manager.get_wallet(recipient_id)
            if not recipient_wallet:
                await self.bot.send_message(chat_id, "Кошелек получателя не найден. Пожалуйста, попробуйте еще раз или создайте кошелек командой /start.")
                await self.bot.delete_state(user_id, chat_id)
                await self.bot.send_message(chat_id, "Операция отменена.", reply_markup=self._main_menu_keyboard())
                return

            async with self.bot.retrieve_data(user_id, chat_id) as data:
                data['mint_recipient_id'] = recipient_id
            await self.bot.set_state(user_id, UserStates.ADMIN_MINT_AMOUNT, chat_id)
            await self.bot.send_message(chat_id, "Введите сумму HKN для эмиссии:")
        except ValueError:
            await self.bot.send_message(chat_id, "Неверный формат ID получателя. Пожалуйста, введите числовой ID.")
            await self.bot.delete_state(user_id, chat_id)
            await self.bot.send_message(chat_id, "Операция отменена.", reply_markup=self._main_menu_keyboard())

    async def handle_admin_mint_amount_input(self, message):
        user_id = message.from_user.id
        chat_id = message.chat.id
        try:
            amount = float(message.text.strip())
            if amount <= 0:
                raise ValueError

            async with self.bot.retrieve_data(user_id, chat_id) as data:
                recipient_id = data.get('mint_recipient_id')

            success = await self.ledger_manager.mint_tokens(recipient_id, amount)
            if success:
                recipient_wallet = await self.ledger_manager.get_wallet(recipient_id)
                recipient_info = recipient_wallet.username if recipient_wallet and recipient_wallet.username else str(recipient_id)
                await self.bot.send_message(chat_id,
                                            f"Успешно эмитировано `{amount:.{self.token_config.DECIMALS}f} {self.token_config.SYMBOL}` на кошелек *{recipient_info}*.",
                                            parse_mode='Markdown')
            else:
                await self.bot.send_message(chat_id, "Ошибка при эмиссии токенов.")
        except ValueError:
            await self.bot.send_message(chat_id, "Неверный формат суммы. Пожалуйста, введите положительное число.")
        finally:
            await self.bot.delete_state(user_id, chat_id)
            await self.bot.send_message(chat_id, "Операция завершена.", reply_markup=self._main_menu_keyboard())

    async def handle_history_command(self, message):
        await self._show_history(message.chat.id, message.from_user.id)

    async def handle_history_pagination_callback(self, call):
        await self.bot.answer_callback_query(call.id)
        page = int(call.data.split('_')[-1])
        await self._show_history(call.message.chat.id, call.from_user.id, page=page, message_id=call.message.message_id)

    async def _show_history(self, chat_id, user_id, page=0, message_id=None):
        limit = 5
        offset = page * limit
        transactions = await self.ledger_manager.get_transaction_history(user_id, limit, offset)
        
        if not transactions:
            history_text = "История транзакций пуста." if page == 0 else "Больше транзакций нет."
        else:
            history_lines = ["**Ваша история транзакций:**"]
            for tx in transactions:
                direction = "получено" if tx.receiver_id == user_id else "отправлено"
                target_id = tx.sender_id if tx.receiver_id == user_id else tx.receiver_id
                
                target_wallet = await self.ledger_manager.get_wallet(target_id)
                target_info = target_wallet.username if target_wallet and target_wallet.username else f"ID {target_id}"
                
                if tx.sender_id == 0:
                    history_lines.append(f"• `{tx.timestamp[:16]}`: `{tx.amount:.{self.token_config.DECIMALS}f} {self.token_config.SYMBOL}` эмитировано Вам.")
                else:
                    history_lines.append(f"• `{tx.timestamp[:16]}`: `{tx.amount:.{self.token_config.DECIMALS}f} {self.token_config.SYMBOL}` {direction} {target_info}")
            history_text = "\n".join(history_lines)
            
        markup = InlineKeyboardMarkup()
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"history_page_{page - 1}"))
        if len(transactions) == limit:
            nav_buttons.append(InlineKeyboardButton("Вперед ➡️", callback_data=f"history_page_{page + 1}"))
        if nav_buttons:
            markup.row(*nav_buttons)
        markup.row(InlineKeyboardButton("💰 Главное меню", callback_data="main_menu"))

        if message_id:
            await self.bot.edit_message_text(history_text, chat_id, message_id, parse_mode='Markdown', reply_markup=markup)
        else:
            await self.bot.send_message(chat_id, history_text, parse_mode='Markdown', reply_markup=markup)

    def run(self):
        asyncio.run(self.bot.polling())

if __name__ == "__main__":
    # Initialize BotConfig and TokenConfig
    bot_config = BotConfig()
    # TokenConfig is already instantiated in BotApp if needed for string formatting there

    db_manager = DatabaseManager(bot_config.DB_PATH)
    asyncio.run(db_manager.init_db())
    ledger_manager = LedgerManager(db_manager)
    bot_app = BotApp(bot_config.BOT_TOKEN, bot_config.ADMIN_IDS, ledger_manager)
    bot_app.run()
