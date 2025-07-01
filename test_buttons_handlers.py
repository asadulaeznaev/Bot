#!/usr/bin/env python3
"""
Тестирование всех callback обработчиков кнопок без Telegram API
"""

import asyncio
import sys
import os
from unittest.mock import AsyncMock, MagicMock

# Добавляем путь к проекту
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import BotApp
from config import BotConfig, TokenConfig
from database import DatabaseManager
from ledger import LedgerManager

class MockTeleBot:
    """Мок-объект для Telegram бота"""
    
    def __init__(self):
        self.callbacks = {}
        self.message_handlers = {}
        self.custom_filters = []
    
    def add_custom_filter(self, filter_obj):
        self.custom_filters.append(filter_obj)
    
    def callback_query_handler(self, func):
        def decorator(handler):
            self.callbacks[func.__name__] = (func, handler)
            return handler
        return decorator
    
    def message_handler(self, commands=None, state=None):
        def decorator(handler):
            key = f"commands_{commands}_state_{state}"
            self.message_handlers[key] = handler
            return handler
        return decorator
    
    async def answer_callback_query(self, callback_id):
        print(f"✅ answer_callback_query({callback_id})")
    
    async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
        print(f"✅ send_message(chat_id={chat_id}, text='{text[:50]}...', markup={bool(reply_markup)})")
    
    async def edit_message_text(self, text, chat_id, message_id, reply_markup=None, parse_mode=None):
        print(f"✅ edit_message_text(chat_id={chat_id}, message_id={message_id}, text='{text[:50]}...', markup={bool(reply_markup)})")
    
    async def set_state(self, user_id, state, chat_id):
        print(f"✅ set_state(user_id={user_id}, state={state})")
    
    async def delete_state(self, user_id, chat_id):
        print(f"✅ delete_state(user_id={user_id}, chat_id={chat_id})")

class MockCallbackQuery:
    """Мок-объект для callback query"""
    
    def __init__(self, callback_data, user_id=12345, chat_id=67890, message_id=111):
        self.data = callback_data
        self.id = "test_callback_id"
        self.from_user = MagicMock()
        self.from_user.id = user_id
        self.message = MagicMock()
        self.message.chat = MagicMock()
        self.message.chat.id = chat_id
        self.message.message_id = message_id

async def test_callback_handlers():
    """Тестирует все callback обработчики"""
    
    print("🚀 Инициализация тестовой среды...")
    
    # Создаем тестовую базу данных
    config = BotConfig()
    config.DB_PATH = "test_callbacks.db"
    
    try:
        # Инициализируем компоненты
        from config import PerformanceConfig
        db_manager = DatabaseManager(config.DB_PATH, PerformanceConfig())
        await db_manager.init_db()
        
        token_config = TokenConfig()
        ledger_manager = LedgerManager(db_manager, token_config)
        
        # Создаем BotApp с мок-ботом
        bot_app = BotApp(config, token_config, ledger_manager)
        bot_app.bot = MockTeleBot()
        
        # Пересоздаем обработчики с мок-ботом
        bot_app._register_handlers()
        
        print(f"✅ Зарегистрировано callback обработчиков: {len(bot_app.bot.callbacks)}")
        print(f"✅ Зарегистрировано message обработчиков: {len(bot_app.bot.message_handlers)}")
        
        # Создаем тестового пользователя
        test_user_id = 12345
        test_wallet = await ledger_manager.create_wallet(test_user_id, "test_user")
        print(f"✅ Создан тестовый кошелек: {test_wallet.balance} HKN")
        
        # Список callback_data для тестирования
        test_callbacks = [
            ("show_balance", "Показ баланса"),
            ("send_hkn", "Отправка HKN"),
            ("main_menu", "Главное меню"),
            ("go_farming_menu", "Меню фарминга"),
            ("farm_stake_hkn", "Стейкинг HKN"),
            ("farm_unstake_hkn", "Снятие стейка"),
            ("farm_claim_rewards", "Сбор наград"),
            ("farm_my_stakes", "Мои стейки"),
            ("farm_boosters_store", "Магазин ускорителей"),
            ("show_history", "История транзакций"),
            ("token_info", "Информация о токене"),
            ("show_marketcap", "Рыночная капитализация"),
            ("sell_hkn_prompt", "Продажа HKN"),
            ("buy_booster_speed_24h_1.5x", "Покупка ускорителя"),
            ("history_page_1", "Страница истории"),
            ("noop", "Заглушка")
        ]
        
        print("\n🧪 Тестирование callback обработчиков:\n")
        
        success_count = 0
        for callback_data, description in test_callbacks:
            try:
                print(f"🔍 Тестирую: {description} (callback_data='{callback_data}')")
                
                # Находим подходящий обработчик
                handler_found = False
                
                for func_name, (condition_func, handler_func) in bot_app.bot.callbacks.items():
                    mock_call = MockCallbackQuery(callback_data)
                    
                    # Проверяем условие
                    try:
                        if condition_func(mock_call):
                            print(f"  ✅ Найден обработчик: {handler_func.__name__}")
                            
                            # Вызываем обработчик
                            await handler_func(mock_call)
                            print(f"  ✅ Обработчик выполнен успешно")
                            
                            handler_found = True
                            success_count += 1
                            break
                    except Exception as e:
                        print(f"  ❌ Ошибка в условии: {e}")
                
                if not handler_found:
                    print(f"  ❌ Обработчик не найден для '{callback_data}'")
                
                print()
                
            except Exception as e:
                print(f"  ❌ Ошибка при тестировании '{callback_data}': {e}")
                import traceback
                traceback.print_exc()
                print()
        
        print(f"\n📊 Результаты тестирования:")
        print(f"✅ Успешно: {success_count}/{len(test_callbacks)}")
        print(f"❌ Ошибок: {len(test_callbacks) - success_count}")
        
        if success_count == len(test_callbacks):
            print("\n🎉 ВСЕ КНОПКИ РАБОТАЮТ КОРРЕКТНО!")
        else:
            print(f"\n⚠️ Некоторые кнопки требуют дополнительной настройки")
        
        await db_manager.close()
        
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Удаляем тестовую БД
        if os.path.exists(config.DB_PATH):
            os.remove(config.DB_PATH)
            print(f"🧹 Удалена тестовая БД: {config.DB_PATH}")

if __name__ == "__main__":
    print("🔧 Тестирование callback обработчиков кнопок...")
    asyncio.run(test_callback_handlers())