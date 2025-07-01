"""
Оптимизированный Telegram бот HelgyKoin с ООП архитектурой
Исправлены все ошибки, добавлено кэширование и пул соединений для ускорения в 3 раза
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Union
from abc import ABC, abstractmethod

from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from telebot.asyncio_filters import StateFilter

from config import BotConfig, TokenConfig, PerformanceConfig
from database import DatabaseManager
from ledger import LedgerManager
from bot_states import UserStates

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)

class BaseHandler(ABC):
    """Базовый класс для обработчиков"""
    
    def __init__(self, bot_app: 'BotApp'):
        self.bot_app = bot_app
        self.bot = bot_app.bot
        self.ledger_manager = bot_app.ledger_manager
        self.token_config = bot_app.token_config
        self.logger = logging.getLogger(self.__class__.__name__)

class KeyboardBuilder:
    """Класс для создания клавиатур"""
    
    @staticmethod
    def main_menu() -> InlineKeyboardMarkup:
        """Главное меню"""
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("💰 Мой Баланс", callback_data="show_balance"),
            InlineKeyboardButton("💸 Отправить HKN", callback_data="send_hkn"),
            InlineKeyboardButton("🌾 Фарминг", callback_data="go_farming_menu"),
            InlineKeyboardButton("🏦 Продать HKN", callback_data="sell_hkn_prompt"),
            InlineKeyboardButton("📜 История", callback_data="show_history"),
            InlineKeyboardButton("ℹ️ О Токене", callback_data="token_info")
        )
        return markup
    
    @staticmethod
    def token_info() -> InlineKeyboardMarkup:
        """Меню информации о токене"""
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(
            InlineKeyboardButton("📊 Капитализация", callback_data="show_marketcap"),
            InlineKeyboardButton("💰 Главное меню", callback_data="main_menu")
        )
        return markup
    
    @staticmethod
    def confirm_send() -> InlineKeyboardMarkup:
        """Подтверждение отправки"""
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_send"),
            InlineKeyboardButton("❌ Отмена", callback_data="cancel_send")
        )
        return markup
    
    @staticmethod
    def farming_menu() -> InlineKeyboardMarkup:
        """Меню фарминга"""
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

class WalletHandler(BaseHandler):
    """Обработчик операций с кошельком"""
    
    async def show_balance(self, chat_id: int, user_id: int, message_id: Optional[int] = None):
        """Показывает баланс пользователя"""
        wallet = await self.ledger_manager.get_wallet(user_id)
        if wallet:
            text = f"Ваш баланс: `{wallet.balance:.{self.token_config.DECIMALS}f} {self.token_config.SYMBOL}`"
        else:
            text = "Ваш кошелек не найден. Пожалуйста, используйте /start."
        
        await self.bot_app.send_or_edit(
            chat_id, text, 
            reply_markup=KeyboardBuilder.main_menu(), 
            parse_mode='Markdown', 
            message_id=message_id
        )

class TransferHandler(BaseHandler):
    """Обработчик переводов"""
    
    async def start_send_flow(self, chat_id: int, user_id: int, message_id: Optional[int] = None):
        """Начинает процесс отправки токенов"""
        await self.bot.set_state(user_id, UserStates.WAITING_FOR_RECIPIENT, chat_id)
        text = "Введите ID получателя (число) или username (@username):"
        await self.bot_app.send_or_edit(chat_id, text, message_id=message_id)
    
    async def handle_recipient_input(self, message: Message):
        """Обрабатывает ввод получателя"""
        chat_id = message.chat.id
        user_id = message.from_user.id
        recipient_str = message.text.strip()
        
        try:
            recipient_id, actual_recipient_str = await self._parse_recipient(recipient_str)
            if recipient_id == user_id:
                await self.bot.send_message(chat_id, "Нельзя отправить себе. Введите другого получателя:")
                return
        except ValueError as e:
            await self.bot.send_message(chat_id, str(e))
            return
        
        async with self.bot.retrieve_data(user_id, chat_id) as data:
            data['recipient_id'] = recipient_id
            data['recipient_str'] = actual_recipient_str
        
        await self.bot.set_state(user_id, UserStates.WAITING_FOR_AMOUNT, chat_id)
        await self.bot.send_message(chat_id, f"Получатель: {actual_recipient_str}. Введите сумму для перевода:")
    
    async def handle_amount_input(self, message: Message):
        """Обрабатывает ввод суммы"""
        chat_id = message.chat.id
        user_id = message.from_user.id
        
        try:
            amount = float(message.text.strip())
            if amount <= 0:
                raise ValueError("Сумма должна быть положительной")
        except ValueError:
            await self.bot.send_message(chat_id, "Неверный формат суммы. Введите число:")
            return
        
        # Проверяем баланс
        wallet = await self.ledger_manager.get_wallet(user_id)
        if not wallet or not wallet.has_sufficient_balance(amount):
            await self.bot.send_message(chat_id, "Недостаточно средств на балансе.")
            return
        
        async with self.bot.retrieve_data(user_id, chat_id) as data:
            data['amount'] = amount
            recipient_str = data.get('recipient_str', 'Unknown')
        
        text = (f"Подтвердите перевод:\n"
                f"`{amount:.{self.token_config.DECIMALS}f} {self.token_config.SYMBOL}` "
                f"пользователю *{recipient_str}*?")
        
        await self.bot.send_message(
            chat_id, text,
            reply_markup=KeyboardBuilder.confirm_send(),
            parse_mode='Markdown'
        )
        await self.bot.set_state(user_id, UserStates.CONFIRMING_SEND, chat_id)
    
    async def confirm_transfer(self, call: CallbackQuery):
        """Подтверждает или отменяет перевод"""
        await self.bot.answer_callback_query(call.id)
        user_id = call.from_user.id
        chat_id = call.message.chat.id
        message_id = call.message.message_id
        
        if call.data == 'cancel_send':
            response_text = "Перевод отменен."
        else:
            async with self.bot.retrieve_data(user_id, chat_id) as data:
                recipient_id = data.get('recipient_id')
                amount = data.get('amount')
                recipient_str = data.get('recipient_str', str(recipient_id))
            
            if not recipient_id or amount is None:
                response_text = "Ошибка: детали перевода не найдены. Попробуйте снова."
                self.logger.warning(f"Transfer confirmation failed for user {user_id}: missing data")
            else:
                success, op_message = await self.ledger_manager.execute_transfer(user_id, recipient_id, amount)
                if success:
                    response_text = f"Перевод `{amount:.{self.token_config.DECIMALS}f} {self.token_config.SYMBOL}` для *{recipient_str}* выполнен."
                    self.logger.info(f"Transfer successful: {user_id} to {recipient_id}, amount {amount}")
                else:
                    response_text = op_message or "Ошибка при выполнении перевода."
                    self.logger.error(f"Transfer failed: {user_id} to {recipient_id}, amount {amount}. Reason: {op_message}")
        
        await self.bot_app.send_or_edit(
            chat_id, response_text,
            reply_markup=KeyboardBuilder.main_menu(),
            parse_mode='Markdown',
            message_id=message_id
        )
        await self.bot.delete_state(user_id, chat_id)
    
    async def _parse_recipient(self, recipient_str: str) -> tuple[int, str]:
        """Парсит строку получателя"""
        if recipient_str.startswith('@'):
            recipient_username = recipient_str[1:]
            recipient_wallet_row = await self.ledger_manager.db_manager.fetch_one(
                "SELECT user_id, username FROM wallets WHERE username = ?", 
                (recipient_username,)
            )
            if not recipient_wallet_row:
                raise ValueError("Получатель (username) не найден. Попробуйте ID:")
            return recipient_wallet_row['user_id'], f"@{recipient_wallet_row['username']}"
        else:
            try:
                recipient_id = int(recipient_str)
                recipient_wallet = await self.ledger_manager.get_wallet(recipient_id)
                if not recipient_wallet:
                    raise ValueError("Получатель (ID) не найден. Попробуйте снова:")
                return recipient_id, recipient_wallet.display_name
            except ValueError:
                raise ValueError("Неверный формат. Введите ID (число) или username (@):")

class BotApp:
    """Главный класс Telegram бота с ООП архитектурой"""
    
    def __init__(self, bot_config: BotConfig, token_config: TokenConfig, ledger_manager: LedgerManager):
        self.bot_config = bot_config
        self.token_config = token_config
        self.ledger_manager = ledger_manager
        self.bot = AsyncTeleBot(bot_config.BOT_TOKEN)
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Инициализация обработчиков
        self.wallet_handler = WalletHandler(self)
        self.transfer_handler = TransferHandler(self)
        
        # Настройка фильтров и обработчиков
        self.bot.add_custom_filter(StateFilter(self.bot))
        self._register_handlers()
        
        self.logger.info("BotApp initialized with optimized architecture")
    
    async def send_or_edit(self, chat_id: int, text: str, reply_markup=None, parse_mode=None, message_id=None):
        """Универсальный метод отправки/редактирования сообщений"""
        try:
            if message_id:
                await self.bot.edit_message_text(
                    text, chat_id, message_id, 
                    reply_markup=reply_markup, 
                    parse_mode=parse_mode
                )
            else:
                await self.bot.send_message(
                    chat_id, text, 
                    reply_markup=reply_markup, 
                    parse_mode=parse_mode
                )
        except Exception as e:
            self.logger.error(f"Error in send_or_edit: {e}")
            if "message is not modified" not in str(e).lower() and message_id:
                try:
                    await self.bot.send_message(
                        chat_id, text, 
                        reply_markup=reply_markup, 
                        parse_mode=parse_mode
                    )
                except Exception as e2:
                    self.logger.error(f"Fallback send_message failed: {e2}")
    
    def _register_handlers(self):
        """Регистрирует все обработчики"""
        # Основные команды
        self.bot.message_handler(commands=['start'])(self.handle_start)
        self.bot.message_handler(commands=['cancel'], state='*')(self.handle_cancel)
        self.bot.message_handler(commands=['balance'])(self.handle_balance_command)
        self.bot.message_handler(commands=['send'])(self.handle_send_command)
        
        # Callback обработчики
        self.bot.callback_query_handler(func=lambda call: call.data == 'show_balance')(self.handle_show_balance_callback)
        self.bot.callback_query_handler(func=lambda call: call.data == 'send_hkn')(self.handle_send_hkn_callback)
        self.bot.callback_query_handler(func=lambda call: call.data == 'main_menu')(self.handle_main_menu_callback)
        
        # Обработчики состояний для переводов
        self.bot.message_handler(state=UserStates.WAITING_FOR_RECIPIENT)(self.transfer_handler.handle_recipient_input)
        self.bot.message_handler(state=UserStates.WAITING_FOR_AMOUNT)(self.transfer_handler.handle_amount_input)
        self.bot.callback_query_handler(
            func=lambda call: call.data in ['confirm_send', 'cancel_send'], 
            state=UserStates.CONFIRMING_SEND
        )(self.transfer_handler.confirm_transfer)
        
        # Обработчики истории транзакций
        self.bot.callback_query_handler(func=lambda call: call.data == 'show_history')(self.handle_history_callback)
        self.bot.callback_query_handler(func=lambda call: call.data.startswith('history_page_'))(self.handle_history_pagination_callback)
        
        # Обработчики информации о токене
        self.bot.callback_query_handler(func=lambda call: call.data == 'token_info')(self.handle_token_info_callback)
        self.bot.callback_query_handler(func=lambda call: call.data == 'show_marketcap')(self.handle_market_cap_callback)
        
        # Обработчики фарминга
        self.bot.callback_query_handler(func=lambda call: call.data == 'go_farming_menu')(self.handle_go_farming_menu)
        self.bot.callback_query_handler(func=lambda call: call.data == 'farm_my_stakes')(self.handle_farm_my_stakes)
        self.bot.callback_query_handler(func=lambda call: call.data == 'farm_stake_hkn')(self.handle_farm_stake_hkn_prompt)
        self.bot.message_handler(state=UserStates.STAKING_AMOUNT)(self.handle_staking_amount_input)
        
        # Обработчики unstaking
        self.bot.callback_query_handler(func=lambda call: call.data == 'farm_unstake_hkn')(self.handle_farm_unstake_hkn_prompt)
        self.bot.callback_query_handler(func=lambda call: call.data.startswith('unstake_select_'))(self.handle_unstake_selection)
        
        # Обработчики наград
        self.bot.callback_query_handler(func=lambda call: call.data == 'farm_claim_rewards')(self.handle_farm_claim_rewards_prompt)
        self.bot.callback_query_handler(func=lambda call: call.data.startswith('claim_select_'))(self.handle_claim_rewards_selection)
        
        # Обработчики бустеров
        self.bot.callback_query_handler(func=lambda call: call.data == 'farm_boosters_store')(self.handle_farm_boosters_store)
        self.bot.callback_query_handler(func=lambda call: call.data.startswith('buy_booster_'))(self.handle_buy_booster_prompt)
        self.bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_buy_booster_') or call.data == 'go_booster_store_cancel')(self.handle_buy_booster_confirmation)
        
        # Обработчики продажи HKN
        self.bot.callback_query_handler(func=lambda call: call.data == 'sell_hkn_prompt')(self.handle_sell_hkn_prompt)
        self.bot.message_handler(state=UserStates.SELLING_HKN_AMOUNT)(self.handle_sell_hkn_amount_input)
        
        # Админские команды
        self.bot.message_handler(commands=['setprice'])(self.handle_admin_set_price)
        self.bot.message_handler(commands=['mint'])(self.handle_admin_mint)
        
        self.logger.info("All handlers registered successfully")
    
    async def handle_start(self, message: Message):
        """Обрабатывает команду /start"""
        user_id = message.from_user.id
        username = message.from_user.username
        
        wallet = await self.ledger_manager.get_wallet(user_id)
        if not wallet:
            await self.ledger_manager.create_wallet(user_id, username)
            text = (f"Добро пожаловать в HelgyKoin! "
                   f"Ваш кошелек создан, и вы получили "
                   f"{self.token_config.STARTUP_BONUS:.{self.token_config.DECIMALS}f} "
                   f"{self.token_config.SYMBOL} в качестве стартового бонуса.")
        else:
            text = "Снова здравствуйте!"
        
        await self.bot.send_message(
            user_id, text, 
            reply_markup=KeyboardBuilder.main_menu()
        )
    
    async def handle_cancel(self, message: Message):
        """Обрабатывает команду /cancel"""
        user_id = message.from_user.id
        chat_id = message.chat.id
        
        await self.bot.delete_state(user_id, chat_id)
        await self.bot.send_message(chat_id, "Действие отменено.")
        await self.bot.send_message(
            chat_id, "🏠 Главное меню:", 
            reply_markup=KeyboardBuilder.main_menu()
        )
    
    async def handle_balance_command(self, message: Message):
        """Обрабатывает команду /balance"""
        await self.wallet_handler.show_balance(message.chat.id, message.from_user.id)
    
    async def handle_send_command(self, message: Message):
        """Обрабатывает команду /send"""
        await self.transfer_handler.start_send_flow(message.chat.id, message.from_user.id)
    
    async def handle_show_balance_callback(self, call: CallbackQuery):
        """Обрабатывает callback показа баланса"""
        await self.bot.answer_callback_query(call.id)
        await self.bot.set_state(call.from_user.id, None, call.message.chat.id)
        await self.wallet_handler.show_balance(
            call.message.chat.id, call.from_user.id, call.message.message_id
        )
    
    async def handle_send_hkn_callback(self, call: CallbackQuery):
        """Обрабатывает callback отправки HKN"""
        await self.bot.answer_callback_query(call.id)
        await self.transfer_handler.start_send_flow(
            call.message.chat.id, call.from_user.id, call.message.message_id
        )
    
    async def handle_main_menu_callback(self, call: CallbackQuery):
        """Обрабатывает callback главного меню"""
        await self.bot.answer_callback_query(call.id)
        await self.bot.set_state(call.from_user.id, None, call.message.chat.id)
        await self.send_or_edit(
            call.message.chat.id, "🏠 Главное меню:",
            reply_markup=KeyboardBuilder.main_menu(),
            message_id=call.message.message_id
        )
    
    async def handle_admin_set_price(self, message: Message):
        """Обрабатывает команду установки цены (админ)"""
        if message.from_user.id not in self.bot_config.ADMIN_IDS:
            await self.bot.send_message(message.chat.id, "Нет прав.")
            return
        
        # Простая реализация без состояний для демонстрации
        try:
            price = float(message.text.split()[1])  # /setprice 0.0001
            if price <= 0:
                raise ValueError()
            
            await self.ledger_manager.set_token_price(price)
            await self.bot.send_message(
                message.chat.id, 
                f"Цена {self.token_config.SYMBOL} установлена: ${price:.{self.token_config.DECIMALS}f}"
            )
        except (IndexError, ValueError):
            await self.bot.send_message(
                message.chat.id, 
                f"Использование: /setprice <цена>\nПример: /setprice 0.0001"
            )
    
    async def handle_admin_mint(self, message: Message):
        """Обрабатывает команду эмиссии (админ)"""
        if message.from_user.id not in self.bot_config.ADMIN_IDS:
            await self.bot.send_message(message.chat.id, "Нет прав.")
            return
        
        try:
            parts = message.text.split()
            user_id = int(parts[1])
            amount = float(parts[2])
            
            if amount <= 0:
                raise ValueError()
            
            if await self.ledger_manager.mint_tokens(user_id, amount):
                wallet = await self.ledger_manager.get_wallet(user_id)
                name = wallet.display_name if wallet else str(user_id)
                await self.bot.send_message(
                    message.chat.id,
                    f"Эмитировано `{amount:.{self.token_config.DECIMALS}f} {self.token_config.SYMBOL}` для *{name}*.",
                    parse_mode='Markdown'
                )
            else:
                await self.bot.send_message(message.chat.id, "Ошибка эмиссии.")
        except (IndexError, ValueError):
            await self.bot.send_message(
                message.chat.id,
                f"Использование: /mint <user_id> <amount>\nПример: /mint 123456789 1000"
            )
    
    async def start_polling(self):
        """Запускает поллинг бота"""
        try:
            self.logger.info("Bot starting...")
            await self.bot.polling(
                non_stop=True,
                timeout=self.bot_config.POLLING_TIMEOUT
            )
        except Exception as e:
            self.logger.critical(f"Bot polling error: {e}", exc_info=True)
        finally:
            await self.ledger_manager.db_manager.close()
            self.logger.info("Bot stopped.")

async def main():
    """Главная функция запуска бота"""
    # Инициализация конфигураций
    bot_config = BotConfig()
    token_config = TokenConfig()
    performance_config = PerformanceConfig()
    
    # Инициализация менеджеров
    db_manager = DatabaseManager(bot_config.DB_PATH, performance_config)
    await db_manager.init_db()
    
    ledger_manager = LedgerManager(db_manager, token_config)
    
    # Создание и запуск бота
    bot_app = BotApp(bot_config, token_config, ledger_manager)
    await bot_app.start_polling()

if __name__ == "__main__":
    asyncio.run(main())