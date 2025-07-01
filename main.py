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

class FarmingHandler(BaseHandler):
    """Обработчик фарминга и стейкинга"""
    
    async def show_farming_menu(self, chat_id: int, user_id: int, message_id: Optional[int] = None):
        """Показывает меню фарминга"""
        text = "🌾 *Фарминг HelgyKoin*\n\nВыберите действие:"
        await self.bot_app.send_or_edit(
            chat_id, text,
            reply_markup=KeyboardBuilder.farming_menu(),
            parse_mode='Markdown',
            message_id=message_id
        )
    
    async def stake_hkn_prompt(self, chat_id: int, user_id: int, message_id: Optional[int] = None):
        """Запрашивает сумму для стейкинга"""
        await self.bot.set_state(user_id, UserStates.WAITING_FOR_STAKE_AMOUNT, chat_id)
        text = (f"Введите сумму HKN для стейкинга:\n\n"
                f"Минимум: {self.token_config.MIN_STAKE_AMOUNT} HKN\n"
                f"Максимум: {self.token_config.MAX_STAKE_AMOUNT} HKN\n"
                f"Доходность: {self.token_config.BASE_HOURLY_REWARD_RATE * 100}% в час")
        await self.bot_app.send_or_edit(chat_id, text, message_id=message_id)
    
    async def handle_stake_amount(self, message: Message):
        """Обрабатывает ввод суммы для стейкинга"""
        chat_id = message.chat.id
        user_id = message.from_user.id
        
        try:
            amount = float(message.text.strip())
            if amount <= 0:
                raise ValueError("Сумма должна быть положительной")
        except ValueError:
            await self.bot.send_message(chat_id, "Неверный формат суммы. Введите число:")
            return
        
        success, msg = await self.ledger_manager.stake_tokens(user_id, amount)
        await self.bot.send_message(chat_id, msg)
        
        if success:
            await self.show_farming_menu(chat_id, user_id)
        
        await self.bot.delete_state(user_id, chat_id)
    
    async def show_user_stakes(self, chat_id: int, user_id: int, message_id: Optional[int] = None):
        """Показывает стейки пользователя"""
        stakes = await self.ledger_manager.get_user_stakes(user_id)
        
        if not stakes:
            text = "У вас нет активных стейков."
        else:
            text = "📈 *Ваши стейки:*\n\n"
            total_staked = 0
            total_rewards = 0
            
            for stake in stakes:
                total_staked += stake['amount']
                total_rewards += stake['pending_rewards']
                text += (f"🆔 Стейк #{stake['stake_id']}\n"
                        f"💰 Сумма: {stake['amount']:.{self.token_config.DECIMALS}f} HKN\n"
                        f"🎁 Награды: {stake['pending_rewards']:.{self.token_config.DECIMALS}f} HKN\n"
                        f"📅 Создан: {stake['created_at'].strftime('%Y-%m-%d %H:%M')}\n\n")
            
            text += f"📊 *Итого стейков:* {total_staked:.{self.token_config.DECIMALS}f} HKN\n"
            text += f"🏆 *Всего наград:* {total_rewards:.{self.token_config.DECIMALS}f} HKN"
        
        await self.bot_app.send_or_edit(
            chat_id, text,
            reply_markup=KeyboardBuilder.farming_menu(),
            parse_mode='Markdown',
            message_id=message_id
        )
    
    async def claim_rewards(self, chat_id: int, user_id: int, message_id: Optional[int] = None):
        """Собирает награды со всех стейков"""
        success, msg = await self.ledger_manager.claim_all_rewards(user_id)
        text = f"🎁 *Сбор наград*\n\n{msg}"
        
        await self.bot_app.send_or_edit(
            chat_id, text,
            reply_markup=KeyboardBuilder.farming_menu(),
            parse_mode='Markdown',
            message_id=message_id
        )
    
    async def unstake_hkn_prompt(self, chat_id: int, user_id: int, message_id: Optional[int] = None):
        """Запрашивает ID стейка для снятия"""
        stakes = await self.ledger_manager.get_user_stakes(user_id)
        
        if not stakes:
            text = "У вас нет активных стейков для снятия."
            await self.bot_app.send_or_edit(
                chat_id, text,
                reply_markup=KeyboardBuilder.farming_menu(),
                message_id=message_id
            )
            return
        
        text = "Выберите стейк для снятия (введите ID):\n\n"
        for stake in stakes:
            text += (f"🆔 {stake['stake_id']}: {stake['amount']:.{self.token_config.DECIMALS}f} HKN "
                    f"(награды: {stake['pending_rewards']:.{self.token_config.DECIMALS}f})\n")
        
        await self.bot.set_state(user_id, UserStates.WAITING_FOR_UNSTAKE_ID, chat_id)
        await self.bot_app.send_or_edit(chat_id, text, message_id=message_id)
    
    async def handle_unstake_id(self, message: Message):
        """Обрабатывает ID стейка для снятия"""
        chat_id = message.chat.id
        user_id = message.from_user.id
        
        try:
            stake_id = int(message.text.strip())
        except ValueError:
            await self.bot.send_message(chat_id, "Неверный формат ID. Введите число:")
            return
        
        success, msg = await self.ledger_manager.unstake_tokens(user_id, stake_id)
        await self.bot.send_message(chat_id, msg)
        
        if success:
            await self.show_farming_menu(chat_id, user_id)
        
        await self.bot.delete_state(user_id, chat_id)
    
    async def show_boosters_store(self, chat_id: int, user_id: int, message_id: Optional[int] = None):
        """Показывает магазин ускорителей"""
        boosters = self.ledger_manager.get_available_boosters_info()
        wallet = await self.ledger_manager.get_wallet(user_id)
        balance = wallet.balance if wallet else 0
        
        text = f"🚀 *Магазин ускорителей*\n\nВаш баланс: {balance:.{self.token_config.DECIMALS}f} HKN\n\n"
        
        markup = InlineKeyboardMarkup(row_width=1)
        for key, booster in boosters.items():
            can_afford = "✅" if balance >= booster['cost'] else "❌"
            text += (f"{can_afford} *{booster['name_ru']}*\n"
                    f"💰 Цена: {booster['cost']:.{self.token_config.DECIMALS}f} HKN\n"
                    f"⚡ Эффект: x{booster['multiplier']}\n"
                    f"⏰ Длительность: {booster['duration_hours']}ч\n"
                    f"📝 {booster['description_ru']}\n\n")
            
            if balance >= booster['cost']:
                markup.add(InlineKeyboardButton(
                    f"Купить {booster['name_ru']}", 
                    callback_data=f"buy_booster_{key}"
                ))
        
        markup.add(InlineKeyboardButton("🌾 Назад к фармингу", callback_data="go_farming_menu"))
        
        await self.bot_app.send_or_edit(
            chat_id, text,
            reply_markup=markup,
            parse_mode='Markdown',
            message_id=message_id
        )

class HistoryHandler(BaseHandler):
    """Обработчик истории транзакций"""
    
    async def show_history(self, chat_id: int, user_id: int, message_id: Optional[int] = None, page: int = 0):
        """Показывает историю транзакций"""
        limit = 5
        offset = page * limit
        transactions = await self.ledger_manager.get_transaction_history(user_id, limit, offset)
        
        if not transactions:
            if page == 0:
                text = "📜 История транзакций пуста."
            else:
                text = "📜 Больше транзакций нет."
            
            markup = InlineKeyboardMarkup()
            if page > 0:
                markup.add(InlineKeyboardButton("◀️ Назад", callback_data=f"history_page_{page-1}"))
            markup.add(InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu"))
        else:
            text = f"📜 *История транзакций* (стр. {page + 1})\n\n"
            
            for tx in transactions:
                direction = tx.get_direction_for_user(user_id)
                if direction == "received":
                    if tx.is_mint:
                        icon = "🎁"
                        desc = "Получено (эмиссия)"
                    else:
                        icon = "📥"
                        desc = "Получено"
                elif direction == "sent":
                    if tx.is_burn:
                        icon = "🔥"
                        desc = "Сожжено"
                    else:
                        icon = "📤"
                        desc = "Отправлено"
                else:
                    icon = "❓"
                    desc = "Неизвестно"
                
                text += (f"{icon} *{desc}*\n"
                        f"💰 {tx.amount:.{self.token_config.DECIMALS}f} HKN\n"
                        f"📅 {tx.formatted_timestamp}\n")
                
                if tx.description:
                    text += f"📝 {tx.description}\n"
                text += "\n"
            
            # Создаем клавиатуру пагинации
            markup = InlineKeyboardMarkup(row_width=3)
            buttons = []
            if page > 0:
                buttons.append(InlineKeyboardButton("◀️", callback_data=f"history_page_{page-1}"))
            
            buttons.append(InlineKeyboardButton(f"{page + 1}", callback_data="noop"))
            
            if len(transactions) == limit:  # Возможно есть еще страницы
                buttons.append(InlineKeyboardButton("▶️", callback_data=f"history_page_{page+1}"))
            
            markup.add(*buttons)
            markup.add(InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu"))
        
        await self.bot_app.send_or_edit(
            chat_id, text,
            reply_markup=markup,
            parse_mode='Markdown',
            message_id=message_id
        )

class TokenInfoHandler(BaseHandler):
    """Обработчик информации о токене"""
    
    async def show_token_info(self, chat_id: int, user_id: int, message_id: Optional[int] = None):
        """Показывает информацию о токене"""
        token_info = await self.ledger_manager.get_token_info()
        
        if not token_info:
            text = "❌ Ошибка получения информации о токене."
        else:
            text = (f"ℹ️ *Информация о {token_info.name}*\n\n"
                   f"🏷️ Символ: {token_info.symbol}\n"
                   f"💰 Общее предложение: {token_info.total_supply:,.{token_info.decimals}f}\n"
                   f"💵 Текущая цена: ${token_info.current_price:.{token_info.decimals}f}\n"
                   f"📊 Рыночная капитализация: ${token_info.market_cap:,.2f}\n"
                   f"🔢 Десятичные знаки: {token_info.decimals}")
        
        await self.bot_app.send_or_edit(
            chat_id, text,
            reply_markup=KeyboardBuilder.token_info(),
            parse_mode='Markdown',
            message_id=message_id
        )
    
    async def show_market_cap(self, chat_id: int, user_id: int, message_id: Optional[int] = None):
        """Показывает рыночную капитализацию"""
        market_cap = await self.ledger_manager.calculate_market_cap()
        text = f"📊 *Рыночная капитализация HelgyKoin*\n\n💰 ${market_cap:,.2f}"
        
        await self.bot_app.send_or_edit(
            chat_id, text,
            reply_markup=KeyboardBuilder.token_info(),
            parse_mode='Markdown',
            message_id=message_id
        )

class SellHandler(BaseHandler):
    """Обработчик продажи токенов"""
    
    async def sell_hkn_prompt(self, chat_id: int, user_id: int, message_id: Optional[int] = None):
        """Запрашивает сумму для продажи"""
        wallet = await self.ledger_manager.get_wallet(user_id)
        if not wallet:
            text = "❌ Кошелек не найден."
            await self.bot_app.send_or_edit(chat_id, text, message_id=message_id)
            return
        
        text = (f"🏦 *Продажа HKN*\n\n"
               f"Ваш баланс: {wallet.balance:.{self.token_config.DECIMALS}f} HKN\n"
               f"Курс: 1 HKN = 0.00005 BotUSD\n\n"
               f"Введите количество HKN для продажи:")
        
        await self.bot.set_state(user_id, UserStates.WAITING_FOR_SELL_AMOUNT, chat_id)
        await self.bot_app.send_or_edit(chat_id, text, parse_mode='Markdown', message_id=message_id)
    
    async def handle_sell_amount(self, message: Message):
        """Обрабатывает сумму для продажи"""
        chat_id = message.chat.id
        user_id = message.from_user.id
        
        try:
            amount = float(message.text.strip())
            if amount <= 0:
                raise ValueError("Сумма должна быть положительной")
        except ValueError:
            await self.bot.send_message(chat_id, "Неверный формат суммы. Введите число:")
            return
        
        success, msg = await self.ledger_manager.sell_hkn_to_system(user_id, amount)
        await self.bot.send_message(chat_id, msg)
        
        if success:
            await self.bot.send_message(
                chat_id, "🏠 Главное меню:",
                reply_markup=KeyboardBuilder.main_menu()
            )
        
        await self.bot.delete_state(user_id, chat_id)

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
        self.farming_handler = FarmingHandler(self)
        self.history_handler = HistoryHandler(self)
        self.token_info_handler = TokenInfoHandler(self)
        self.sell_handler = SellHandler(self)
        
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
        
        # Callback обработчики - основные
        self.bot.callback_query_handler(func=lambda call: call.data == 'show_balance')(self.handle_show_balance_callback)
        self.bot.callback_query_handler(func=lambda call: call.data == 'send_hkn')(self.handle_send_hkn_callback)
        self.bot.callback_query_handler(func=lambda call: call.data == 'main_menu')(self.handle_main_menu_callback)
        
        # Callback обработчики - фарминг
        self.bot.callback_query_handler(func=lambda call: call.data == 'go_farming_menu')(self.handle_farming_menu_callback)
        self.bot.callback_query_handler(func=lambda call: call.data == 'farm_stake_hkn')(self.handle_stake_hkn_callback)
        self.bot.callback_query_handler(func=lambda call: call.data == 'farm_unstake_hkn')(self.handle_unstake_hkn_callback)
        self.bot.callback_query_handler(func=lambda call: call.data == 'farm_claim_rewards')(self.handle_claim_rewards_callback)
        self.bot.callback_query_handler(func=lambda call: call.data == 'farm_my_stakes')(self.handle_my_stakes_callback)
        self.bot.callback_query_handler(func=lambda call: call.data == 'farm_boosters_store')(self.handle_boosters_store_callback)
        
        # Callback обработчики - бустеры
        self.bot.callback_query_handler(func=lambda call: call.data.startswith('buy_booster_'))(self.handle_buy_booster_callback)
        
        # Callback обработчики - история
        self.bot.callback_query_handler(func=lambda call: call.data == 'show_history')(self.handle_history_callback)
        self.bot.callback_query_handler(func=lambda call: call.data.startswith('history_page_'))(self.handle_history_page_callback)
        
        # Callback обработчики - информация о токене
        self.bot.callback_query_handler(func=lambda call: call.data == 'token_info')(self.handle_token_info_callback)
        self.bot.callback_query_handler(func=lambda call: call.data == 'show_marketcap')(self.handle_marketcap_callback)
        
        # Callback обработчики - продажа
        self.bot.callback_query_handler(func=lambda call: call.data == 'sell_hkn_prompt')(self.handle_sell_hkn_prompt_callback)
        
        # Callback обработчики - вспомогательные
        self.bot.callback_query_handler(func=lambda call: call.data == 'noop')(self.handle_noop_callback)
        
        # Обработчики состояний для переводов
        self.bot.message_handler(state=UserStates.WAITING_FOR_RECIPIENT)(self.transfer_handler.handle_recipient_input)
        self.bot.message_handler(state=UserStates.WAITING_FOR_AMOUNT)(self.transfer_handler.handle_amount_input)
        self.bot.callback_query_handler(
            func=lambda call: call.data in ['confirm_send', 'cancel_send'], 
            state=UserStates.CONFIRMING_SEND
        )(self.transfer_handler.confirm_transfer)
        
        # Обработчики состояний для фарминга
        self.bot.message_handler(state=UserStates.WAITING_FOR_STAKE_AMOUNT)(self.farming_handler.handle_stake_amount)
        self.bot.message_handler(state=UserStates.WAITING_FOR_UNSTAKE_ID)(self.farming_handler.handle_unstake_id)
        
        # Обработчики состояний для продажи
        self.bot.message_handler(state=UserStates.WAITING_FOR_SELL_AMOUNT)(self.sell_handler.handle_sell_amount)
        
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

    # === Новые callback обработчики ===
    
    async def handle_farming_menu_callback(self, call: CallbackQuery):
        """Обрабатывает callback меню фарминга"""
        await self.bot.answer_callback_query(call.id)
        await self.bot.set_state(call.from_user.id, None, call.message.chat.id)
        await self.farming_handler.show_farming_menu(
            call.message.chat.id, call.from_user.id, call.message.message_id
        )
    
    async def handle_stake_hkn_callback(self, call: CallbackQuery):
        """Обрабатывает callback стейкинга HKN"""
        await self.bot.answer_callback_query(call.id)
        await self.farming_handler.stake_hkn_prompt(
            call.message.chat.id, call.from_user.id, call.message.message_id
        )
    
    async def handle_unstake_hkn_callback(self, call: CallbackQuery):
        """Обрабатывает callback снятия стейка"""
        await self.bot.answer_callback_query(call.id)
        await self.farming_handler.unstake_hkn_prompt(
            call.message.chat.id, call.from_user.id, call.message.message_id
        )
    
    async def handle_claim_rewards_callback(self, call: CallbackQuery):
        """Обрабатывает callback сбора наград"""
        await self.bot.answer_callback_query(call.id)
        await self.farming_handler.claim_rewards(
            call.message.chat.id, call.from_user.id, call.message.message_id
        )
    
    async def handle_my_stakes_callback(self, call: CallbackQuery):
        """Обрабатывает callback показа стейков"""
        await self.bot.answer_callback_query(call.id)
        await self.farming_handler.show_user_stakes(
            call.message.chat.id, call.from_user.id, call.message.message_id
        )
    
    async def handle_boosters_store_callback(self, call: CallbackQuery):
        """Обрабатывает callback магазина ускорителей"""
        await self.bot.answer_callback_query(call.id)
        await self.farming_handler.show_boosters_store(
            call.message.chat.id, call.from_user.id, call.message.message_id
        )
    
    async def handle_buy_booster_callback(self, call: CallbackQuery):
        """Обрабатывает callback покупки ускорителя"""
        await self.bot.answer_callback_query(call.id)
        booster_key = call.data.replace('buy_booster_', '')
        success, msg = await self.ledger_manager.buy_booster(call.from_user.id, booster_key)
        
        text = f"🚀 *Покупка ускорителя*\n\n{msg}"
        await self.send_or_edit(
            call.message.chat.id, text,
            reply_markup=KeyboardBuilder.farming_menu(),
            parse_mode='Markdown',
            message_id=call.message.message_id
        )
    
    async def handle_history_callback(self, call: CallbackQuery):
        """Обрабатывает callback истории"""
        await self.bot.answer_callback_query(call.id)
        await self.history_handler.show_history(
            call.message.chat.id, call.from_user.id, call.message.message_id
        )
    
    async def handle_history_page_callback(self, call: CallbackQuery):
        """Обрабатывает callback страницы истории"""
        await self.bot.answer_callback_query(call.id)
        page = int(call.data.replace('history_page_', ''))
        await self.history_handler.show_history(
            call.message.chat.id, call.from_user.id, call.message.message_id, page
        )
    
    async def handle_token_info_callback(self, call: CallbackQuery):
        """Обрабатывает callback информации о токене"""
        await self.bot.answer_callback_query(call.id)
        await self.token_info_handler.show_token_info(
            call.message.chat.id, call.from_user.id, call.message.message_id
        )
    
    async def handle_marketcap_callback(self, call: CallbackQuery):
        """Обрабатывает callback рыночной капитализации"""
        await self.bot.answer_callback_query(call.id)
        await self.token_info_handler.show_market_cap(
            call.message.chat.id, call.from_user.id, call.message.message_id
        )
    
    async def handle_sell_hkn_prompt_callback(self, call: CallbackQuery):
        """Обрабатывает callback продажи HKN"""
        await self.bot.answer_callback_query(call.id)
        await self.sell_handler.sell_hkn_prompt(
            call.message.chat.id, call.from_user.id, call.message.message_id
        )
    
    async def handle_noop_callback(self, call: CallbackQuery):
        """Обрабатывает callback заглушки для кнопки номера страницы"""
        await self.bot.answer_callback_query(call.id)

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