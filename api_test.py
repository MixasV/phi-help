#!/usr/bin/env python3
"""
Тестирование API функций для проверки фолловеров
"""

from phi_api import PHIAPI
from data_utils import DataManager

def test_followers_api():
    """Тестирует API для проверки фолловеров"""
    
    print("🧪 Тестирование API для проверки фолловеров")
    print("=" * 50)
    
    api = PHIAPI()
    
    # Тестовые адреса
    test_target = "0xC7f9154a72524097B1323961F584f7047b875271"
    test_user = "0x1234567890123456789012345678901234567890"
    
    print(f"🎯 Целевой адрес: {test_target}")
    print(f"👤 Адрес пользователя: {test_user}")
    
    # Тест 1: Проверка одного адреса
    print("\n📋 Тест 1: Проверка подписки на один адрес")
    is_following = api.check_followers_for_address(test_target, test_user)
    print(f"   Результат: {'✅ Подписан' if is_following else '❌ Не подписан'}")
    
    # Тест 2: Проверка нескольких адресов
    print("\n📋 Тест 2: Проверка подписок на несколько адресов")
    test_addresses = [
        "0xC7f9154a72524097B1323961F584f7047b875271",
        "0x1234567890123456789012345678901234567890",
        "0xABCDEF1234567890123456789012345678901234"
    ]
    
    results = api.check_multiple_followers(test_addresses, test_user)
    
    for address, is_following in results.items():
        status = "✅ Подписан" if is_following else "❌ Не подписан"
        print(f"   {address[:10]}...{address[-4:]}: {status}")
    
    # Тест 3: Проверка ачивок
    print("\n📋 Тест 3: Проверка ачивок")
    
    # Trendsetter
    trendsetter = api.get_trendsetter_achievement(test_user)
    if trendsetter:
        print(f"   Trendsetter: {trendsetter['progress_count']}/{trendsetter['required_count']}")
        print(f"   Выполнена: {'✅' if trendsetter['completed'] else '❌'}")
        print(f"   Осталось: {trendsetter['remaining']}")
    else:
        print("   ❌ Не удалось получить данные об ачивке Trendsetter")
    
    # They Lovin' It
    token_holders = api.get_token_holders_achievement(test_user)
    if token_holders:
        print(f"   They Lovin' It: {token_holders['progress_count']}/{token_holders['required_count']}")
        print(f"   Выполнена: {'✅' if token_holders['completed'] else '❌'}")
        print(f"   Осталось: {token_holders['remaining']}")
    else:
        print("   ❌ Не удалось получить данные об ачивке They Lovin' It")
    
    # Тест 4: Проверка токенов
    print("\n📋 Тест 4: Проверка токенов")
    
    test_board_id = "5ced1c01-dca1-4021-8a9d-870955020444"
    
    # Проверка количества холдеров токена
    holders_count = api.get_token_holders_count(test_board_id)
    if holders_count is not None:
        print(f"   Холдеров токена {test_board_id[:8]}...: {holders_count}")
    else:
        print(f"   ❌ Не удалось получить количество холдеров для {test_board_id[:8]}...")
    
    # Проверка покупки токена
    purchase_check = api.check_token_purchase(test_board_id, test_user)
    print(f"   Покупка токена {test_user[:10]}...: {'✅ Купил' if purchase_check else '❌ Не купил'}")

def test_data_management():
    """Тестирует управление данными"""
    
    print("\n🗂️ Тестирование управления данными")
    print("=" * 50)
    
    dm = DataManager()
    
    # Тест 1: Чтение данных
    print("\n📋 Тест 1: Чтение данных из файлов")
    
    wallets = dm.read_wallets()
    boards = dm.read_boards()
    tokens = dm.read_tokens()
    
    print(f"   Кошельков: {len(wallets)}")
    print(f"   Бордов: {len(boards)}")
    print(f"   Токенов: {len(tokens)}")
    
    # Тест 2: Случайные данные
    print("\n📋 Тест 2: Получение случайных данных")
    
    random_wallets = dm.get_random_wallets(3)
    print(f"   Случайные кошельки: {len(random_wallets)}")
    for wallet in random_wallets:
        print(f"     {wallet[:10]}...{wallet[-4:]}")
    
    random_tokens = dm.get_random_tokens(3)
    print(f"   Случайные токены: {len(random_tokens)}")
    for board_id in random_tokens:
        print(f"     {board_id[:8]}...")

def test_integration():
    """Тестирует интеграцию всех компонентов"""
    
    print("\n🔗 Тестирование интеграции")
    print("=" * 50)
    
    api = PHIAPI()
    dm = DataManager()
    
    # Тест: Полный цикл проверки фолловеров
    print("\n📋 Тест: Полный цикл проверки фолловеров")
    
    # Получаем случайные адреса
    available_wallets = dm.get_random_wallets(3)
    
    if available_wallets:
        test_user = available_wallets[0]
        target_addresses = available_wallets[1:]
        
        print(f"   Пользователь: {test_user[:10]}...{test_user[-4:]}")
        print(f"   Целевые адреса: {len(target_addresses)}")
        
        # Проверяем подписки
        results = api.check_multiple_followers(target_addresses, test_user)
        
        followed = [addr for addr, is_following in results.items() if is_following]
        not_followed = [addr for addr, is_following in results.items() if not is_following]
        
        print(f"   Подписан на: {len(followed)}")
        print(f"   Не подписан на: {len(not_followed)}")
        
        if not_followed:
            print("   Ссылки для подписки:")
            for addr in not_followed:
                print(f"     https://phi.box/profile/{addr}")
    else:
        print("   ❌ Нет доступных адресов для тестирования")
    
    # Тест: Полный цикл проверки токенов
    print("\n📋 Тест: Полный цикл проверки токенов")
    
    # Получаем случайные токены
    available_tokens = dm.get_random_tokens(3)
    
    if available_tokens:
        test_user = "0xC7f9154a72524097B1323961F584f7047b875271"
        
        print(f"   Пользователь: {test_user[:10]}...{test_user[-4:]}")
        print(f"   Целевые токены: {len(available_tokens)}")
        
        # Проверяем покупки
        results = api.check_multiple_token_purchases(available_tokens, test_user)
        
        purchased = [board_id for board_id, is_purchased in results.items() if is_purchased]
        not_purchased = [board_id for board_id, is_purchased in results.items() if not is_purchased]
        
        print(f"   Купил токенов: {len(purchased)}")
        print(f"   Не купил токенов: {len(not_purchased)}")
        
        if not_purchased:
            print("   Ссылки для покупки:")
            for board_id in not_purchased:
                print(f"     https://phi.box/board/{board_id}")
    else:
        print("   ❌ Нет доступных токенов для тестирования")

if __name__ == "__main__":
    try:
        test_followers_api()
        test_data_management()
        test_integration()
        
        print("\n✅ Все тесты завершены!")
        
    except Exception as e:
        print(f"\n❌ Ошибка при тестировании: {e}")
        import traceback
        traceback.print_exc()
