import os
import asyncio
import logging # Added
from datetime import datetime
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from telebot.asyncio_filters import StateFilter

from config import BotConfig, TokenConfig
from database import DatabaseManager
from ledger import LedgerManager
from bot_states import UserStates

# --- Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
# Main application logger (can be used for general app-level logs if needed)
app_logger = logging.getLogger("HelgyKoinBotApp")


class BotApp:
    def __init__(self, token: str, admin_ids: list[int], ledger_manager: LedgerManager):
        self.bot = AsyncTeleBot(token)
        self.admin_ids = admin_ids
        self.ledger_manager = ledger_manager
        self.token_config = TokenConfig()
        self.logger = logging.getLogger(self.__class__.__name__) # Logger for BotApp class
        self.bot.add_custom_filter(StateFilter(self.bot))
        self._register_handlers()
        self.logger.info("BotApp initialized.")

    # --- Keyboard Methods ---
    def _main_menu_keyboard(self):
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton("💰 Мой Баланс", callback_data="show_balance"),
                   InlineKeyboardButton("💸 Отправить HKN", callback_data="send_hkn"),
                   InlineKeyboardButton("🌾 Фарминг", callback_data="go_farming_menu"),
                   InlineKeyboardButton("🏦 Продать HKN", callback_data="sell_hkn_prompt"),
                   InlineKeyboardButton("📜 История", callback_data="show_history"),
                   InlineKeyboardButton("ℹ️ О Токене", callback_data="token_info"))
        return markup

    def _token_info_keyboard(self):
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(InlineKeyboardButton("📊 Капитализация", callback_data="show_marketcap"),
                   InlineKeyboardButton("💰 Главное меню", callback_data="main_menu"))
        return markup

    def _confirm_send_keyboard(self):
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_send"),
                   InlineKeyboardButton("❌ Отмена", callback_data="cancel_send"))
        return markup

    def _farming_menu_keyboard(self):
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("➕ Стейкать HKN", callback_data="farm_stake_hkn"),
            InlineKeyboardButton("➖ Снять HKN со стейка", callback_data="farm_unstake_hkn"),
            InlineKeyboardButton("🎁 Забрать награды", callback_data="farm_claim_rewards"),
            InlineKeyboardButton("📈 Мои Стейки", callback_data="farm_my_stakes"),
            InlineKeyboardButton("🚀 Ускорители", callback_data="farm_boosters_store"),
            InlineKeyboardButton("💰 Главное меню", callback_data="main_menu")
        )
        return markup

    def _booster_store_keyboard(self):
        markup = InlineKeyboardMarkup(row_width=1)
        available_boosters = self.ledger_manager.get_available_boosters_info()
        for key, booster_info in available_boosters.items():
            button_text = f"Купить '{booster_info['name_ru']}' ({booster_info['cost']:.{self.token_config.DECIMALS}f} HKN)"
            markup.add(InlineKeyboardButton(button_text, callback_data=f"buy_booster_{key}"))
        markup.add(InlineKeyboardButton("🔙 Меню Фарминга", callback_data="go_farming_menu"))
        return markup

    def _select_stake_keyboard(self, stakes: list, action_prefix: str) -> InlineKeyboardMarkup:
        markup = InlineKeyboardMarkup(row_width=1)
        if not stakes:
            markup.add(InlineKeyboardButton("Нет доступных стейков", callback_data="no_stakes_to_select"))
        else:
            for stake in stakes:
                pending_rewards_float = float(stake.get('pending_rewards', 0.0))
                button_text = (f"ID {stake['stake_id']}: {stake['amount']:.{self.token_config.DECIMALS}f} HKN "
                               f"(Награда: {pending_rewards_float:.{self.token_config.DECIMALS}f})")
                markup.add(InlineKeyboardButton(button_text, callback_data=f"{action_prefix}_select_{stake['stake_id']}"))
        markup.add(InlineKeyboardButton("🔙 Меню Фарминга", callback_data="go_farming_menu"))
        return markup

    # --- Helper Methods ---
    async def _is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids

    async def _send_or_edit(self, chat_id, text, reply_markup=None, parse_mode=None, message_id=None):
        try:
            if message_id:
                await self.bot.edit_message_text(text, chat_id, message_id, reply_markup=reply_markup, parse_mode=parse_mode)
            else:
                await self.bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception as e:
            self.logger.error(f"Error in _send_or_edit (chat_id={chat_id}, message_id={message_id}): {e}", exc_info=True)
            if "message is not modified" not in str(e).lower() and message_id: # If edit failed and it wasn't "not modified"
                try: # Try sending as a new message
                    await self.bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
                except Exception as e2:
                    self.logger.error(f"Fallback send_message also failed in _send_or_edit: {e2}", exc_info=True)


    # --- Handler Registration ---
    def _register_handlers(self):
        # Global Cancel Command
        self.bot.message_handler(commands=['cancel'], state='*')(self.handle_cancel)

        # General Commands & Callbacks
        self.bot.message_handler(commands=['start'])(self.handle_start)
        self.bot.message_handler(commands=['balance'])(self.handle_balance_command)
        self.bot.callback_query_handler(func=lambda call: call.data == 'show_balance')(self.handle_show_balance_callback)
        self.bot.message_handler(commands=['send'])(self.handle_send_command)
        self.bot.callback_query_handler(func=lambda call: call.data == 'send_hkn')(self.handle_send_hkn_callback)
        self.bot.message_handler(commands=['history'])(self.handle_history_command)
        self.bot.callback_query_handler(func=lambda call: call.data == 'show_history')(self.handle_history_callback)
        self.bot.callback_query_handler(func=lambda call: call.data.startswith('history_page_'))(self.handle_history_pagination_callback)
        self.bot.message_handler(commands=['tokeninfo'])(self.handle_token_info_command)
        self.bot.callback_query_handler(func=lambda call: call.data == 'token_info')(self.handle_token_info_callback)
        self.bot.message_handler(commands=['marketcap'])(self.handle_market_cap_command)
        self.bot.callback_query_handler(func=lambda call: call.data == 'show_marketcap')(self.handle_market_cap_callback)
        self.bot.callback_query_handler(func=lambda call: call.data == 'main_menu', state='*')(self.handle_main_menu_callback) # Allow main_menu from any state

        # Send Flow States & Callbacks
        self.bot.message_handler(state=UserStates.WAITING_FOR_RECIPIENT)(self.handle_waiting_for_recipient)
        self.bot.message_handler(state=UserStates.WAITING_FOR_AMOUNT)(self.handle_waiting_for_amount)
        self.bot.callback_query_handler(func=lambda call: call.data in ['confirm_send', 'cancel_send'], state=UserStates.CONFIRMING_SEND)(self.handle_send_confirmation_callback)

        # Admin Commands & States
        self.bot.message_handler(commands=['setprice'])(self.handle_admin_set_price_command)
        self.bot.message_handler(state=UserStates.ADMIN_SET_PRICE)(self.handle_admin_set_price_input)
        self.bot.message_handler(commands=['mint'])(self.handle_admin_mint_command)
        self.bot.message_handler(state=UserStates.ADMIN_MINT_RECIPIENT)(self.handle_admin_mint_recipient_input)
        self.bot.message_handler(state=UserStates.ADMIN_MINT_AMOUNT)(self.handle_admin_mint_amount_input)

        # Farming Menu Callbacks & States
        self.bot.callback_query_handler(func=lambda call: call.data == 'go_farming_menu', state='*')(self.handle_go_farming_menu)
        self.bot.callback_query_handler(func=lambda call: call.data == 'farm_my_stakes', state=[UserStates.FARMING_MENU, None])(self.handle_farm_my_stakes)
        self.bot.callback_query_handler(func=lambda call: call.data == 'farm_stake_hkn', state=UserStates.FARMING_MENU)(self.handle_farm_stake_hkn_prompt)
        self.bot.message_handler(state=UserStates.STAKING_AMOUNT)(self.handle_staking_amount_input)

        self.bot.callback_query_handler(func=lambda call: call.data == 'farm_unstake_hkn', state=UserStates.FARMING_MENU)(self.handle_farm_unstake_hkn_prompt)
        self.bot.callback_query_handler(func=lambda call: call.data.startswith('unstake_select_'), state=UserStates.UNSTAKING_SELECT_STAKE)(self.handle_unstake_selection)

        self.bot.callback_query_handler(func=lambda call: call.data == 'farm_claim_rewards', state=UserStates.FARMING_MENU)(self.handle_farm_claim_rewards_prompt)
        self.bot.callback_query_handler(func=lambda call: call.data.startswith('claim_select_'), state=UserStates.CLAIMING_SELECT_STAKE)(self.handle_claim_rewards_selection)

        # Booster Store Callbacks & States
        self.bot.callback_query_handler(func=lambda call: call.data == 'farm_boosters_store', state=UserStates.FARMING_MENU)(self.handle_farm_boosters_store)
        self.bot.callback_query_handler(func=lambda call: call.data.startswith('buy_booster_'), state=UserStates.BOOSTER_STORE)(self.handle_buy_booster_prompt)
        self.bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_buy_booster_') or call.data == 'go_booster_store_cancel', state=UserStates.CONFIRM_BUY_BOOSTER)(self.handle_buy_booster_confirmation)

        # Sell HKN Callbacks & States
        self.bot.callback_query_handler(func=lambda call: call.data == 'sell_hkn_prompt', state='*')(self.handle_sell_hkn_prompt)
        self.bot.message_handler(state=UserStates.SELLING_HKN_AMOUNT)(self.handle_sell_hkn_amount_input)

    # --- Global Cancel Handler ---
    async def handle_cancel(self, message):
        user_id = message.from_user.id
        chat_id = message.chat.id
        current_state_str = await self.bot.get_state(user_id, chat_id)
        self.logger.info(f"User {user_id} initiated /cancel from state: {current_state_str}")

        # Define states that are considered "menus" or "neutral" and shouldn't be cancelled by simple /cancel
        # Comparing string representations of states
        non_cancelable_states = [
            None, # No state
            str(UserStates.FARMING_MENU),
            str(UserStates.BOOSTER_STORE)
        ]

        if current_state_str not in non_cancelable_states:
            await self.bot.delete_state(user_id, chat_id)
            self.logger.info(f"State for user {user_id} cleared due to /cancel.")
            await self.bot.send_message(chat_id, "Действие отменено.")
            await self.bot.send_message(chat_id, "🏠 Главное меню:", reply_markup=self._main_menu_keyboard())
        else:
            self.logger.info(f"User {user_id} in non-cancelable state {current_state_str}. Showing main menu.")
            await self.bot.send_message(chat_id, "Нет активного действия для отмены. Возврат в главное меню.", reply_markup=self._main_menu_keyboard())


    # --- General Handlers ---
    async def handle_start(self, message):
        # ... (logging can be added here if desired, e.g., self.logger.info(f"User {message.from_user.id} started bot"))
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

    async def handle_waiting_for_recipient(self, message):
        chat_id = message.chat.id
        user_id = message.from_user.id
        recipient_str = message.text.strip()
        actual_recipient_str = recipient_str
        try:
            if recipient_str.startswith('@'):
                recipient_username = recipient_str[1:]
                # TODO: Consider moving username-to-ID lookup to LedgerManager
                recipient_wallet_row = await self.ledger_manager.db_manager.fetch_one("SELECT user_id, username FROM wallets WHERE username = ?", (recipient_username,))
                if not recipient_wallet_row:
                    await self.bot.send_message(chat_id, "Получатель (username) не найден. Попробуйте ID:")
                    return
                recipient_id = recipient_wallet_row['user_id']
                actual_recipient_str = f"@{recipient_wallet_row['username']}"
            else:
                recipient_id = int(recipient_str)
                recipient_wallet_check = await self.ledger_manager.get_wallet(recipient_id)
                if not recipient_wallet_check:
                    await self.bot.send_message(chat_id, "Получатель (ID) не найден. Попробуйте снова:"); return
        except ValueError:
            await self.bot.send_message(chat_id, "Неверный формат. Введите ID (число) или username (@):")
            return
        if recipient_id == user_id:
            await self.bot.send_message(chat_id, "Нельзя отправить себе. Введите другого получателя:")
            return

        async with self.bot.retrieve_data(user_id, chat_id) as data:
            data['recipient_id'] = recipient_id
            data['recipient_str'] = actual_recipient_str
        await self.bot.set_state(user_id, UserStates.WAITING_FOR_AMOUNT, chat_id)
        await self.bot.send_message(chat_id, f"Получатель: {actual_recipient_str}. Введите сумму для перевода:")


    async def _process_send_direct(self, message, recipient_str_arg, amount_str_arg):
        user_id = message.from_user.id
        chat_id = message.chat.id
        actual_recipient_str = recipient_str_arg

        sender_wallet = await self.ledger_manager.get_wallet(user_id) # Check sender's wallet first
        if not sender_wallet:
            self.logger.error(f"Sender wallet not found for user {user_id} in _process_send_direct.")
            await self.bot.send_message(chat_id, "Ошибка: Ваш кошелек не найден. Пожалуйста, используйте /start."); return

        try:
            amount = float(amount_str_arg)
            if amount <= 0: raise ValueError("Amount must be positive")
        except ValueError:
            await self.bot.send_message(chat_id, "Неверный формат суммы."); return

        if sender_wallet.balance < amount:
            await self.bot.send_message(chat_id, "Недостаточно средств на вашем балансе."); return

        try:
            if recipient_str_arg.startswith('@'):
                recipient_username = recipient_str_arg[1:]
                # TODO: Consider moving username-to-ID lookup to LedgerManager
                recipient_wallet_row = await self.ledger_manager.db_manager.fetch_one("SELECT user_id, username FROM wallets WHERE username = ?", (recipient_username,))
                if not recipient_wallet_row:
                    await self.bot.send_message(chat_id, "Получатель (username) не найден."); return
                recipient_id = recipient_wallet_row['user_id']
                actual_recipient_str = f"@{recipient_wallet_row['username']}"
            else:
                recipient_id = int(recipient_str_arg)
                recipient_wallet_check = await self.ledger_manager.get_wallet(recipient_id)
                if not recipient_wallet_check:
                     await self.bot.send_message(chat_id, "Получатель (ID) не найден."); return
        except ValueError:
            await self.bot.send_message(chat_id, "Неверный формат ID/username получателя."); return

        if recipient_id == user_id:
            await self.bot.send_message(chat_id, "Нельзя отправить HKN самому себе."); return

        async with self.bot.retrieve_data(user_id, chat_id) as data:
            data['recipient_id'] = recipient_id
            data['amount'] = amount
            data['recipient_str'] = actual_recipient_str

        await self.bot.send_message(chat_id,
                                    f"Подтвердите перевод: `{amount:.{self.token_config.DECIMALS}f} {self.token_config.SYMBOL}` пользователю *{actual_recipient_str}*?",
                                    reply_markup=self._confirm_send_keyboard(), parse_mode='Markdown')
        await self.bot.set_state(user_id, UserStates.CONFIRMING_SEND, chat_id)

    # ... (other handlers remain largely the same, can add logging as needed) ...
    async def handle_balance_command(self, message):
        await self._show_balance(message.chat.id, message.from_user.id)

    async def handle_show_balance_callback(self, call):
        await self.bot.answer_callback_query(call.id)
        await self.bot.set_state(call.from_user.id, None, call.message.chat.id)
        await self._show_balance(call.message.chat.id, call.from_user.id, call.message.message_id)

    async def _show_balance(self, chat_id, user_id, message_id=None):
        wallet = await self.ledger_manager.get_wallet(user_id)
        text = f"Ваш баланс: `{wallet.balance:.{self.token_config.DECIMALS}f} {self.token_config.SYMBOL}`" if wallet else "Ваш кошелек не найден. Пожалуйста, используйте /start."
        await self._send_or_edit(chat_id, text, reply_markup=self._main_menu_keyboard(), parse_mode='Markdown', message_id=message_id)

    async def handle_send_confirmation_callback(self, call):
        await self.bot.answer_callback_query(call.id)
        user_id = call.from_user.id
        chat_id = call.message.chat.id
        message_id = call.message.message_id
        response_text = "Перевод отменен."
        if call.data == 'confirm_send':
            async with self.bot.retrieve_data(user_id, chat_id) as data:
                recipient_id = data.get('recipient_id')
                amount = data.get('amount')
                recipient_str = data.get('recipient_str', str(recipient_id))
            if not recipient_id or amount is None:
                response_text = "Ошибка: детали перевода не найдены. Попробуйте снова."
                self.logger.warning(f"Transfer confirmation failed for user {user_id}: missing recipient_id or amount in state data.")
            else:
                success, op_message = await self.ledger_manager.execute_transfer(user_id, recipient_id, amount)
                if success:
                    response_text = f"Перевод `{amount:.{self.token_config.DECIMALS}f} {self.token_config.SYMBOL}` для *{recipient_str}* выполнен."
                    self.logger.info(f"Transfer successful: {user_id} to {recipient_id}, amount {amount}")
                else:
                    response_text = op_message if op_message else "Ошибка при выполнении перевода."
                    self.logger.error(f"Transfer failed for user {user_id} to {recipient_id}, amount {amount}. Reason: {op_message}")

        await self._send_or_edit(chat_id, response_text, reply_markup=self._main_menu_keyboard(), parse_mode='Markdown', message_id=message_id)
        await self.bot.delete_state(user_id, chat_id)

    async def handle_history_command(self, message):
        await self._show_history(message.chat.id, message.from_user.id)
    async def handle_history_callback(self, call):
        await self.bot.answer_callback_query(call.id)
        await self.bot.set_state(call.from_user.id, None, call.message.chat.id)
        await self._show_history(call.message.chat.id, call.from_user.id, message_id=call.message.message_id)
    async def handle_history_pagination_callback(self, call):
        await self.bot.answer_callback_query(call.id)
        page = int(call.data.split('_')[-1])
        await self._show_history(call.message.chat.id, call.from_user.id, page=page, message_id=call.message.message_id)
    async def _show_history(self, chat_id, user_id, page=0, message_id=None):
        limit = 5; offset = page * limit
        transactions = await self.ledger_manager.get_transaction_history(user_id, limit, offset)
        decimals = self.token_config.DECIMALS; symbol = self.token_config.SYMBOL
        if not transactions and page == 0: text = "История транзакций пуста."
        elif not transactions and page > 0: text = "Больше транзакций нет."
        else:
            lines = ["**Ваша история транзакций:**"]
            for tx in transactions:
                ts = datetime.fromisoformat(tx.timestamp).strftime("%y-%m-%d %H:%M") if isinstance(tx.timestamp, str) else tx.timestamp.strftime("%y-%m-%d %H:%M")
                desc = tx.description or ""
                if tx.sender_id == 0: lines.append(f"• `{ts}`: `+{tx.amount:.{decimals}f} {symbol}` ({desc})")
                elif tx.receiver_id == 0: lines.append(f"• `{ts}`: `-{tx.amount:.{decimals}f} {symbol}` ({desc})")
                else:
                    direction = "получено от" if tx.receiver_id == user_id else "отправлено"
                    other_id = tx.sender_id if tx.receiver_id == user_id else tx.receiver_id
                    other_wallet = await self.ledger_manager.get_wallet(other_id)
                    other_info = other_wallet.username if other_wallet and other_wallet.username else f"ID:{other_id}"
                    sign = "+" if tx.receiver_id == user_id else "-"
                    lines.append(f"• `{ts}`: `{sign}{tx.amount:.{decimals}f} {symbol}` {direction} {other_info} ({desc})")
            text = "\n".join(lines)
        markup = InlineKeyboardMarkup(row_width=2)
        nav = []
        if page > 0: nav.append(InlineKeyboardButton("⬅️ Пред.", callback_data=f"history_page_{page-1}"))
        if len(transactions) == limit: nav.append(InlineKeyboardButton("След. ➡️", callback_data=f"history_page_{page+1}"))
        if nav: markup.add(*nav)
        markup.add(InlineKeyboardButton("💰 Главное меню", callback_data="main_menu"))
        await self._send_or_edit(chat_id, text, reply_markup=markup, parse_mode='Markdown', message_id=message_id)

    async def handle_token_info_command(self, message): await self._show_token_info(message.chat.id)
    async def handle_token_info_callback(self, call):
        await self.bot.answer_callback_query(call.id)
        await self.bot.set_state(call.from_user.id, None, call.message.chat.id)
        await self._show_token_info(call.message.chat.id, call.message.message_id)
    async def _show_token_info(self, chat_id, message_id=None):
        info = await self.ledger_manager.get_token_info()
        if not info: text = "Информация о токене недоступна."
        else: text = (f"**{info.name} ({info.symbol})**\n"
                      f"Десятичные: `{info.decimals}`\nОбщее предложение: `{info.total_supply:.{self.token_config.DECIMALS}f} {info.symbol}`\n"
                      f"Цена: `${info.current_price:.{self.token_config.DECIMALS}f}`")
        await self._send_or_edit(chat_id, text, reply_markup=self._token_info_keyboard(), parse_mode='Markdown', message_id=message_id)

    async def handle_market_cap_command(self, message): await self._show_market_cap(message.chat.id)
    async def handle_market_cap_callback(self, call):
        await self.bot.answer_callback_query(call.id)
        await self.bot.set_state(call.from_user.id, None, call.message.chat.id)
        await self._show_market_cap(call.message.chat.id, call.message.message_id)
    async def _show_market_cap(self, chat_id, message_id=None):
        cap = await self.ledger_manager.calculate_market_cap()
        text = f"Капитализация {self.token_config.SYMBOL}: `${cap:.2f}`"
        markup = InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("🔄 Обновить", callback_data="show_marketcap"), InlineKeyboardButton("💰 Главное меню", callback_data="main_menu"))
        await self._send_or_edit(chat_id, text, reply_markup=markup, parse_mode='Markdown', message_id=message_id)

    async def handle_main_menu_callback(self, call):
        await self.bot.answer_callback_query(call.id)
        await self.bot.set_state(call.from_user.id, None, call.message.chat.id)
        await self._send_or_edit(call.message.chat.id, "🏠 Главное меню:", reply_markup=self._main_menu_keyboard(), message_id=call.message.message_id)

    async def handle_admin_set_price_command(self, message):
        if not await self._is_admin(message.from_user.id): await self.bot.send_message(message.chat.id, "Нет прав."); return
        await self.bot.set_state(message.from_user.id, UserStates.ADMIN_SET_PRICE, message.chat.id)
        await self.bot.send_message(message.chat.id, f"Новая цена для {self.token_config.SYMBOL} (e.g., 0.0001):")
    async def handle_admin_set_price_input(self, message):
        user_id = message.from_user.id; chat_id = message.chat.id
        try:
            price = float(message.text.strip())
            if price <= 0: raise ValueError()
            await self.ledger_manager.set_token_price(price)
            await self.bot.send_message(chat_id, f"Цена {self.token_config.SYMBOL} установлена: ${price:.{self.token_config.DECIMALS}f}")
        except ValueError: await self.bot.send_message(chat_id, "Неверный формат цены.")
        finally:
            await self.bot.delete_state(user_id, chat_id)
            await self.bot.send_message(chat_id, "Установка цены завершена.", reply_markup=self._main_menu_keyboard())

    async def handle_admin_mint_command(self, message):
        if not await self._is_admin(message.from_user.id): await self.bot.send_message(message.chat.id, "Нет прав."); return
        await self.bot.set_state(message.from_user.id, UserStates.ADMIN_MINT_RECIPIENT, message.chat.id)
        await self.bot.send_message(message.chat.id, "ID получателя для эмиссии:")
    async def handle_admin_mint_recipient_input(self, message):
        user_id = message.from_user.id; chat_id = message.chat.id
        try:
            recipient_id = int(message.text.strip())
            if not await self.ledger_manager.get_wallet(recipient_id):
                await self.bot.send_message(chat_id, "Кошелек не найден. /start должен быть вызван получателем."); return
            async with self.bot.retrieve_data(user_id, chat_id) as data: data['mint_recipient_id'] = recipient_id
            await self.bot.set_state(user_id, UserStates.ADMIN_MINT_AMOUNT, chat_id)
            await self.bot.send_message(chat_id, f"Сумма {self.token_config.SYMBOL} для эмиссии ({recipient_id}):")
        except ValueError: await self.bot.send_message(chat_id, "Неверный ID.")
    async def handle_admin_mint_amount_input(self, message):
        user_id = message.from_user.id; chat_id = message.chat.id
        try:
            amount = float(message.text.strip())
            if amount <= 0: raise ValueError()
            async with self.bot.retrieve_data(user_id, chat_id) as data: recipient_id = data.get('mint_recipient_id')
            if not recipient_id: await self.bot.send_message(chat_id, "Ошибка ID. /mint снова."); await self.bot.delete_state(user_id, chat_id); return
            if await self.ledger_manager.mint_tokens(recipient_id, amount):
                wallet = await self.ledger_manager.get_wallet(recipient_id)
                name = wallet.username if wallet and wallet.username else str(recipient_id)
                await self.bot.send_message(chat_id, f"Эмитировано `{amount:.{self.token_config.DECIMALS}f} {self.token_config.SYMBOL}` для *{name}*.", parse_mode='Markdown')
            else: await self.bot.send_message(chat_id, "Ошибка эмиссии.")
        except ValueError: await self.bot.send_message(chat_id, "Неверная сумма.")
        finally:
            await self.bot.delete_state(user_id, chat_id)
            await self.bot.send_message(chat_id, "Эмиссия завершена.", reply_markup=self._main_menu_keyboard())

    async def handle_go_farming_menu(self, call_or_message):
        user_id = call_or_message.from_user.id
        chat_id = call_or_message.chat.id if hasattr(call_or_message, 'chat') else call_or_message.message.chat.id
        message_id = call_or_message.message.message_id if hasattr(call_or_message, 'message') else None

        if hasattr(call_or_message, 'id'): await self.bot.answer_callback_query(call_or_message.id)
        await self.bot.set_state(user_id, UserStates.FARMING_MENU, chat_id)
        await self._send_or_edit(chat_id, "🌾 Меню Фарминга и Стейкинга:", reply_markup=self._farming_menu_keyboard(), message_id=message_id)

    async def handle_farm_my_stakes(self, call):
        await self.bot.answer_callback_query(call.id)
        user_id = call.from_user.id
        stakes = await self.ledger_manager.get_user_stakes(user_id)
        text = "📈 *Ваши активные стейки:*\n\n"
        if not stakes: text = "У вас пока нет активных стейков."
        else:
            for stake in stakes:
                created_at_str = stake['created_at']
                if isinstance(stake['created_at'], datetime):
                    created_at_str = stake['created_at'].strftime('%Y-%m-%d %H:%M')
                
                text += (f"🆔 `{stake['stake_id']}`: `{stake['amount']:.{self.token_config.DECIMALS}f} {self.token_config.SYMBOL}` "
                         f"(от {created_at_str})\n"
                         f"   Ожидает: `{float(stake['pending_rewards']):.{self.token_config.DECIMALS}f} {self.token_config.SYMBOL}`\n\n")
        await self._send_or_edit(call.message.chat.id, text, reply_markup=self._farming_menu_keyboard(), parse_mode='Markdown', message_id=call.message.message_id)

    async def handle_farm_stake_hkn_prompt(self, call):
        await self.bot.answer_callback_query(call.id)
        await self.bot.set_state(call.from_user.id, UserStates.STAKING_AMOUNT, call.message.chat.id)
        await self._send_or_edit(call.message.chat.id, "Какую сумму HKN вы хотите поставить на стейк?\n\n(Введите число, например: 1000)", message_id=call.message.message_id)

    async def handle_staking_amount_input(self, message):
        user_id = message.from_user.id; chat_id = message.chat.id
        try:
            amount = float(message.text.strip())
            if amount <= 0: await self.bot.send_message(chat_id, "Сумма должна быть > 0. Попробуйте:"); return
            success, msg = await self.ledger_manager.stake_tokens(user_id, amount)
            await self.bot.send_message(chat_id, msg)
            await self.bot.delete_state(user_id, chat_id)
            await self.bot.send_message(chat_id, "🌾 Меню Фарминга и Стейкинга:", reply_markup=self._farming_menu_keyboard())
            await self.bot.set_state(user_id, UserStates.FARMING_MENU, chat_id)
        except ValueError: await self.bot.send_message(chat_id, "Введите корректное число.")

    async def handle_farm_unstake_hkn_prompt(self, call):
        await self.bot.answer_callback_query(call.id)
        user_id = call.from_user.id
        stakes = await self.ledger_manager.get_user_stakes(user_id)
        if not stakes:
            await self._send_or_edit(call.message.chat.id, "У вас нет стейков для вывода.", reply_markup=self._farming_menu_keyboard(), message_id=call.message.message_id)
            return
        await self.bot.set_state(user_id, UserStates.UNSTAKING_SELECT_STAKE, call.message.chat.id)
        await self._send_or_edit(call.message.chat.id, "Выберите стейк для вывода средств:", reply_markup=self._select_stake_keyboard(stakes, "unstake"), message_id=call.message.message_id)

    async def handle_unstake_selection(self, call):
        await self.bot.answer_callback_query(call.id)
        user_id = call.from_user.id
        stake_id = int(call.data.split('_')[-1])
        success, message = await self.ledger_manager.unstake_tokens(user_id, stake_id)
        await self._send_or_edit(call.message.chat.id, message, message_id=call.message.message_id)
        await self.bot.set_state(user_id, UserStates.FARMING_MENU, call.message.chat.id)
        await self.bot.send_message(call.message.chat.id, "🌾 Меню Фарминга и Стейкинга:", reply_markup=self._farming_menu_keyboard())


    async def handle_farm_claim_rewards_prompt(self, call):
        await self.bot.answer_callback_query(call.id)
        user_id = call.from_user.id
        stakes = await self.ledger_manager.get_user_stakes(user_id)
        claimable_stakes = [s for s in stakes if float(s.get('pending_rewards', 0.0)) > 0]
        if not claimable_stakes:
            await self._send_or_edit(call.message.chat.id, "Нет доступных наград для сбора.", reply_markup=self._farming_menu_keyboard(), message_id=call.message.message_id)
            return
        await self.bot.set_state(user_id, UserStates.CLAIMING_SELECT_STAKE, call.message.chat.id)
        await self._send_or_edit(call.message.chat.id, "Выберите стейк для сбора наград:", reply_markup=self._select_stake_keyboard(claimable_stakes, "claim"), message_id=call.message.message_id)

    async def handle_claim_rewards_selection(self, call):
        await self.bot.answer_callback_query(call.id)
        user_id = call.from_user.id
        stake_id = int(call.data.split('_')[-1])
        success, message = await self.ledger_manager.claim_rewards(user_id, stake_id)
        await self._send_or_edit(call.message.chat.id, message, message_id=call.message.message_id)
        await self.bot.set_state(user_id, UserStates.FARMING_MENU, call.message.chat.id)
        await self.bot.send_message(call.message.chat.id, "🌾 Меню Фарминга и Стейкинга:", reply_markup=self._farming_menu_keyboard())


    async def handle_farm_boosters_store(self, call):
        await self.bot.answer_callback_query(call.id)
        await self.bot.set_state(call.from_user.id, UserStates.BOOSTER_STORE, call.message.chat.id)
        store_text = "🚀 **Магазин Ускорителей** 🚀\n\nВыберите ускоритель:"
        boosters = self.ledger_manager.get_available_boosters_info()
        if not boosters: store_text = "Ускорители недоступны."
        else:
            for key, b_info in boosters.items():
                store_text += (f"\n\n✨ **{b_info['name_ru']}** ✨\n"
                               f"   Стоимость: `{b_info['cost']:.{self.token_config.DECIMALS}f} {self.token_config.SYMBOL}` | "
                               f"Длительность: `{b_info['duration_hours']}`ч.\n"
                               f"   Множитель: `x{b_info['multiplier']}`\n   _{b_info['description_ru']}_")
        await self._send_or_edit(call.message.chat.id, store_text, reply_markup=self._booster_store_keyboard(), parse_mode='Markdown', message_id=call.message.message_id)

    async def handle_buy_booster_prompt(self, call):
        await self.bot.answer_callback_query(call.id)
        user_id = call.from_user.id
        booster_key = call.data.replace("buy_booster_", "")
        if booster_key not in self.ledger_manager.booster_types:
            await self._send_or_edit(call.message.chat.id, "Ошибка: Неверный ускоритель.", reply_markup=self._booster_store_keyboard(), message_id=call.message.message_id); return
        booster_config = self.ledger_manager.booster_types[booster_key]
        markup = InlineKeyboardMarkup(row_width=2).add(
            InlineKeyboardButton(f"✅ Да ({booster_config['cost']:.{self.token_config.DECIMALS}f} HKN)", callback_data=f"confirm_buy_booster_{booster_key}"),
            InlineKeyboardButton("❌ Нет", callback_data="go_booster_store_cancel"))
        await self.bot.set_state(user_id, UserStates.CONFIRM_BUY_BOOSTER, call.message.chat.id)
        await self._send_or_edit(call.message.chat.id, f"Купить '{booster_config['name_ru']}' за {booster_config['cost']:.{self.token_config.DECIMALS}f} HKN?",
                                 reply_markup=markup, message_id=call.message.message_id)

    async def handle_buy_booster_confirmation(self, call):
        await self.bot.answer_callback_query(call.id)
        user_id = call.from_user.id
        chat_id = call.message.chat.id
        message_id = call.message.message_id

        final_text = ""
        if call.data.startswith("confirm_buy_booster_"):
            booster_key = call.data.replace("confirm_buy_booster_", "")
            success, message = await self.ledger_manager.buy_booster(user_id, booster_key)
            final_text = f"{message}\n\n🌾 Меню Фарминга и Стейкинга:" # Append menu text
        elif call.data == "go_booster_store_cancel":
             final_text = "Покупка отменена.\n\n🌾 Меню Фарминга и Стейкинга:"

        await self.bot.set_state(user_id, UserStates.FARMING_MENU, chat_id)
        # Edit the current message (which was the confirmation prompt) to show the result and the farming menu
        await self._send_or_edit(chat_id, final_text, reply_markup=self._farming_menu_keyboard(), message_id=message_id, parse_mode='Markdown')


    async def handle_sell_hkn_prompt(self, call):
        await self.bot.answer_callback_query(call.id)
        user_id = call.from_user.id
        chat_id = call.message.chat.id
        message_id = call.message.message_id
        sell_rate_info = (f"Текущий курс продажи: 1 HKN = {self.ledger_manager.HKN_SELL_RATE_TO_BOTUSD} BotUSD (концептуально).\n\n"
                          "Введите сумму HKN, которую хотите продать системе:")
        await self.bot.set_state(user_id, UserStates.SELLING_HKN_AMOUNT, chat_id)
        await self._send_or_edit(chat_id, sell_rate_info, message_id=message_id)


    async def handle_sell_hkn_amount_input(self, message):
        user_id = message.from_user.id
        chat_id = message.chat.id
        try:
            amount_hkn = float(message.text.strip())
        except ValueError:
            await self.bot.send_message(chat_id, "Неверный формат суммы. Пожалуйста, введите число (например, 100 или 50.5).")
            return
        success, response_message = await self.ledger_manager.sell_hkn_to_system(user_id, amount_hkn)
        await self.bot.send_message(chat_id, response_message)
        await self.bot.delete_state(user_id, chat_id)
        await self.bot.send_message(chat_id, "🏠 Главное меню:", reply_markup=self._main_menu_keyboard())


    def run(self):
        try:
            app_logger.info("Bot starting...")
            asyncio.run(self.bot.polling(non_stop=True, timeout=30, long_polling_timeout = 30)) # Added non_stop and timeout
        except Exception as e:
            app_logger.critical(f"Bot polling loop critical error: {e}", exc_info=True)
        finally:
            app_logger.info("Bot stopped.")


if __name__ == "__main__":
    bot_config = BotConfig()
    # Initialize DatabaseManager and LedgerManager (consider passing logger here too if they need it)
    db_manager = DatabaseManager(bot_config.DB_PATH)
    asyncio.run(db_manager.init_db()) # Ensure DB is initialized

    ledger_manager = LedgerManager(db_manager)

    bot_app = BotApp(bot_config.BOT_TOKEN, bot_config.ADMIN_IDS, ledger_manager)
    bot_app.run()

[end of main .py]
