#!/usr/bin/env python3
"""
Пример использования PHI Helper Bot

Этот файл демонстрирует основные возможности бота
"""

from bot import PHIBot
from phi_api import PHIAPI
from data_utils import DataManager

def main():
    """Демонстрация основных функций"""
    
    print("🤖 PHI Helper Bot - Пример использования")
    print("=" * 50)
    
    # Инициализация компонентов
    bot = PHIBot()
    api = PHIAPI()
    data_manager = DataManager()
    
    # Пример работы с данными пользователей
    print("\n📊 Работа с данными пользователей:")
    
    # Добавляем тестового пользователя
    test_user_id = 123456789
    test_wallets = [
        "0xC7f9154a72524097B1323961F584f7047b875271",
        "0x1234567890123456789012345678901234567890"
    ]
    test_boards = [
        "5ced1c01-dca1-4021-8a9d-870955020444",
        "06546848-0841-4d5f-9915-9660e3d42e55"
    ]
    
    # Инициализируем пользователя
    if test_user_id not in bot.users_data:
        from bot import UserData
        bot.users_data[test_user_id] = UserData([], [])
    
    # Добавляем данные
    bot.users_data[test_user_id].wallet_addresses.extend(test_wallets)
    bot.users_data[test_user_id].board_addresses.extend(test_boards)
    
    # Сохраняем данные
    bot.save_users_data()
    bot.update_wallets_file()
    bot.update_boards_file()
    bot.update_tokens_file()
    
    print(f"✅ Добавлен пользователь {test_user_id}")
    print(f"   Кошельков: {len(bot.users_data[test_user_id].wallet_addresses)}")
    print(f"   Бордов: {len(bot.users_data[test_user_id].board_addresses)}")
    
    # Пример работы с файлами данных
    print("\n📁 Работа с файлами данных:")
    
    wallets = data_manager.read_wallets()
    boards = data_manager.read_boards()
    tokens = data_manager.read_tokens()
    
    print(f"   Кошельков в файле: {len(wallets)}")
    print(f"   Бордов в файле: {len(boards)}")
    print(f"   Токенов в файле: {len(tokens)}")
    
    # Пример получения случайных данных
    print("\n🎲 Случайные данные:")
    
    random_wallets = data_manager.get_random_wallets(2)
    print(f"   Случайные кошельки: {random_wallets}")
    
    random_tokens = data_manager.get_random_tokens(2)
    print(f"   Случайные токены: {random_tokens}")
    
    # Пример работы с API (закомментировано, так как API еще не готово)
    print("\n🌐 Работа с PHI API:")
    print("   (API функции готовы, но требуют реальные endpoints)")
    
    # Пример проверки валидности адресов
    print("\n✅ Валидация данных:")
    
    test_addresses = [
        "0xC7f9154a72524097B1323961F584f7047b875271",  # Валидный
        "0x123",  # Невалидный
        "invalid_address",  # Невалидный
        "0x1234567890123456789012345678901234567890"  # Валидный
    ]
    
    for addr in test_addresses:
        is_valid = bot.is_valid_ethereum_address(addr)
        status = "✅" if is_valid else "❌"
        print(f"   {status} {addr}")
    
    # Пример извлечения ID борда
    print("\n🎯 Извлечение ID бордов:")
    
    test_boards_input = [
        "https://phi.box/board/5ced1c01-dca1-4021-8a9d-870955020444",
        "5ced1c01-dca1-4021-8a9d-870955020444",
        "invalid_board"
    ]
    
    for board_input in test_boards_input:
        board_id = bot.extract_board_id(board_input)
        status = "✅" if board_id else "❌"
        print(f"   {status} {board_input} -> {board_id}")
    
    print("\n🚀 Бот готов к запуску!")
    print("   Запустите: python bot.py")
    print("   Или используйте: bot.run()")

if __name__ == "__main__":
    main()

