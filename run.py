#!/usr/bin/env python3
"""
Скрипт запуска оптимизированного HelgyKoin бота
"""

import asyncio
import logging
import sys
import os

# Добавляем текущую директорию в путь Python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import main

def setup_logging():
    """Настройка логирования"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("bot.log", encoding='utf-8'),
            logging.StreamHandler()
        ]
    )

if __name__ == "__main__":
    print("🚀 Запуск оптимизированного HelgyKoin бота...")
    setup_logging()
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️ Бот остановлен пользователем")
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        logging.critical(f"Critical error: {e}", exc_info=True)