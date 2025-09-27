import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from phi_api import PHIAPI
from data_utils import DataManager

@dataclass
class PendingCheck:
    """Данные о пользователе, ожидающем проверки"""
    user_id: int
    wallet_index: int
    wallet_address: str
    check_type: str  # 'followers' или 'tokens'
    target_addresses: List[str]  # Для фолловеров
    target_board_ids: List[str]  # Для токенов
    attempts: int = 0
    max_attempts: int = 30
    created_at: datetime = None
    last_check: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.last_check is None:
            self.last_check = datetime.now()

@dataclass
class WaitingUser:
    """Данные о пользователе, ожидающем новых адресов/токенов"""
    user_id: int
    wallet_index: int
    wallet_address: str
    check_type: str  # 'followers' или 'tokens'
    needed_count: int  # Сколько нужно адресов/токенов
    created_at: datetime = None
    last_check: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.last_check is None:
            self.last_check = datetime.now()

class BackgroundChecker:
    """Система фоновой проверки заданий"""
    
    def __init__(self, bot_instance):
        self.bot = bot_instance
        self.api_client = PHIAPI()
        self.data_manager = DataManager()
        self.pending_checks_file = "pending_checks.json"
        self.waiting_users_file = "waiting_users.json"
        self.pending_checks: Dict[str, PendingCheck] = {}
        self.waiting_users: Dict[str, WaitingUser] = {}
        self.check_interval = 300  # 5 минут в секундах
        self.is_running = False
        
        # Загружаем существующие проверки
        self.load_pending_checks()
        self.load_waiting_users()
    
    def load_pending_checks(self):
        """Загружает список ожидающих проверки из файла"""
        try:
            if os.path.exists(self.pending_checks_file):
                with open(self.pending_checks_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for key, check_data in data.items():
                        # Конвертируем строки дат обратно в datetime
                        check_data['created_at'] = datetime.fromisoformat(check_data['created_at'])
                        check_data['last_check'] = datetime.fromisoformat(check_data['last_check'])
                        self.pending_checks[key] = PendingCheck(**check_data)
                print(f"Загружено {len(self.pending_checks)} ожидающих проверки")
        except Exception as e:
            print(f"Ошибка загрузки ожидающих проверки: {e}")
    
    def save_pending_checks(self):
        """Сохраняет список ожидающих проверки в файл"""
        try:
            data = {}
            for key, check in self.pending_checks.items():
                check_dict = asdict(check)
                # Конвертируем datetime в строки для JSON
                check_dict['created_at'] = check.created_at.isoformat()
                check_dict['last_check'] = check.last_check.isoformat()
                data[key] = check_dict
            
            with open(self.pending_checks_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка сохранения ожидающих проверки: {e}")
    
    def load_waiting_users(self):
        """Загружает список ожидающих пользователей из файла"""
        try:
            if os.path.exists(self.waiting_users_file):
                with open(self.waiting_users_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for key, user_data in data.items():
                        # Конвертируем строки дат обратно в datetime
                        user_data['created_at'] = datetime.fromisoformat(user_data['created_at'])
                        user_data['last_check'] = datetime.fromisoformat(user_data['last_check'])
                        self.waiting_users[key] = WaitingUser(**user_data)
                print(f"Загружено {len(self.waiting_users)} ожидающих пользователей")
        except Exception as e:
            print(f"Ошибка загрузки ожидающих пользователей: {e}")
    
    def save_waiting_users(self):
        """Сохраняет список ожидающих пользователей в файл"""
        try:
            data = {}
            for key, user in self.waiting_users.items():
                user_dict = asdict(user)
                # Конвертируем datetime в строки для JSON
                user_dict['created_at'] = user.created_at.isoformat()
                user_dict['last_check'] = user.last_check.isoformat()
                data[key] = user_dict
            
            with open(self.waiting_users_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка сохранения ожидающих пользователей: {e}")
    
    def add_pending_check(self, user_id: int, wallet_index: int, wallet_address: str, 
                         check_type: str, target_addresses: List[str] = None, 
                         target_board_ids: List[str] = None):
        """Добавляет пользователя в очередь на проверку"""
        key = f"{user_id}_{wallet_index}_{check_type}"
        
        check = PendingCheck(
            user_id=user_id,
            wallet_index=wallet_index,
            wallet_address=wallet_address,
            check_type=check_type,
            target_addresses=target_addresses or [],
            target_board_ids=target_board_ids or []
        )
        
        self.pending_checks[key] = check
        self.save_pending_checks()
        print(f"Добавлена проверка для пользователя {user_id}, тип: {check_type}")
    
    def add_waiting_user(self, user_id: int, wallet_index: int, wallet_address: str, 
                        check_type: str, needed_count: int):
        """Добавляет пользователя в очередь ожидания новых адресов/токенов"""
        key = f"{user_id}_{wallet_index}_{check_type}"
        
        waiting_user = WaitingUser(
            user_id=user_id,
            wallet_index=wallet_index,
            wallet_address=wallet_address,
            check_type=check_type,
            needed_count=needed_count
        )
        
        self.waiting_users[key] = waiting_user
        self.save_waiting_users()
        print(f"Добавлен ожидающий пользователь {user_id}, тип: {check_type}, нужно: {needed_count}")
    
    def remove_waiting_user(self, user_id: int, wallet_index: int, check_type: str):
        """Удаляет пользователя из очереди ожидания"""
        key = f"{user_id}_{wallet_index}_{check_type}"
        if key in self.waiting_users:
            del self.waiting_users[key]
            self.save_waiting_users()
            print(f"Удален ожидающий пользователь {user_id}, тип: {check_type}")
    
    def remove_pending_check(self, user_id: int, wallet_index: int, check_type: str):
        """Удаляет пользователя из очереди проверки"""
        key = f"{user_id}_{wallet_index}_{check_type}"
        if key in self.pending_checks:
            del self.pending_checks[key]
            self.save_pending_checks()
            print(f"Удалена проверка для пользователя {user_id}, тип: {check_type}")
    
    async def check_followers_task(self, check: PendingCheck) -> bool:
        """Проверяет выполнение задания по фолловерам"""
        try:
            # Проверяем подписки через API
            follow_results = self.api_client.check_multiple_followers(
                check.target_addresses, check.wallet_address
            )
            
            # Разделяем на подписанные и неподписанные
            followed = [addr for addr, is_following in follow_results.items() if is_following]
            not_followed = [addr for addr, is_following in follow_results.items() if not is_following]
            
            if not not_followed:
                # Все подписки выполнены
                user_data = self.bot.users_data.get(check.user_id)
                if user_data:
                    user_data.completed_followers_tasks += len(followed)
                    self.bot.save_users_data()
                
                # Проверяем ачивку еще раз
                achievement = self.api_client.get_trendsetter_achievement(check.wallet_address)
                if achievement and achievement['completed']:
                    # Проверяем, есть ли адрес уже в общем списке
                    is_in_global_list = check.wallet_address in self.bot.data_manager.read_wallets()
                    if not is_in_global_list:
                        self.bot.add_wallet_to_global_list(check.wallet_address)
                    
                    await self.send_success_notification(check, "followers")
                else:
                    await self.send_partial_success_notification(check, "followers", len(followed))
                
                return True
            else:
                # Еще есть неподписанные адреса
                print(f"Пользователь {check.user_id} еще не подписался на {len(not_followed)} адресов")
                return False
                
        except Exception as e:
            print(f"Ошибка проверки фолловеров для пользователя {check.user_id}: {e}")
            return False
    
    async def check_tokens_task(self, check: PendingCheck) -> bool:
        """Проверяет выполнение задания по токенам"""
        try:
            # Проверяем покупки через API
            purchase_results = self.api_client.check_multiple_token_purchases(
                check.target_board_ids, check.wallet_address
            )
            
            # Разделяем на купленные и некупленные
            purchased = [board_id for board_id, is_purchased in purchase_results.items() if is_purchased]
            not_purchased = [board_id for board_id, is_purchased in purchase_results.items() if not is_purchased]
            
            if not not_purchased:
                # Все покупки выполнены
                user_data = self.bot.users_data.get(check.user_id)
                if user_data:
                    user_data.completed_token_tasks += len(purchased)
                    self.bot.save_users_data()
                
                # Проверяем ачивку еще раз
                achievement = self.api_client.get_token_holders_achievement(check.wallet_address)
                if achievement and achievement['completed']:
                    # Проверяем, есть ли адрес уже в общем списке
                    is_in_global_list = check.wallet_address in self.bot.data_manager.read_wallets()
                    if not is_in_global_list:
                        self.bot.add_wallet_to_global_list(check.wallet_address)
                    
                    await self.send_success_notification(check, "tokens")
                else:
                    await self.send_partial_success_notification(check, "tokens", len(purchased))
                
                return True
            else:
                # Еще есть некупленные токены
                print(f"Пользователь {check.user_id} еще не купил {len(not_purchased)} токенов")
                return False
                
        except Exception as e:
            print(f"Ошибка проверки токенов для пользователя {check.user_id}: {e}")
            return False
    
    async def send_success_notification(self, check: PendingCheck, task_type: str):
        """Отправляет уведомление об успешном выполнении"""
        try:
            if task_type == "followers":
                message = f"""🎉 Задание выполнено!

Ачивка "Trendsetter" успешно выполнена для адреса:
{check.wallet_address}

Ваш адрес добавлен в общий список для помощи другим пользователям."""
            else:
                message = f"""🎉 Задание выполнено!

Ачивка "They Lovin' It" успешно выполнена для адреса:
{check.wallet_address}

Ваш адрес добавлен в общий список для помощи другим пользователям."""
            
            await self.bot.application.bot.send_message(
                chat_id=check.user_id,
                text=message
            )
            
            # Удаляем из очереди
            self.remove_pending_check(check.user_id, check.wallet_index, check.check_type)
            
        except Exception as e:
            print(f"Ошибка отправки уведомления об успехе: {e}")
    
    async def send_partial_success_notification(self, check: PendingCheck, task_type: str, completed_count: int):
        """Отправляет уведомление о частичном выполнении"""
        try:
            if task_type == "followers":
                message = f"""✅ Подписки выполнены!

Вы успешно подписались на все {completed_count} профилей.
Ачивка может обновиться через некоторое время."""
            else:
                message = f"""✅ Покупки выполнены!

Вы успешно купили все {completed_count} токенов.
Ачивка может обновиться через некоторое время."""
            
            await self.bot.application.bot.send_message(
                chat_id=check.user_id,
                text=message
            )
            
            # Удаляем из очереди
            self.remove_pending_check(check.user_id, check.wallet_index, check.check_type)
            
        except Exception as e:
            print(f"Ошибка отправки уведомления о частичном успехе: {e}")
    
    async def send_failure_notification(self, check: PendingCheck):
        """Отправляет уведомление о неудачной проверке"""
        try:
            message = f"""⏰ Время истекло

К сожалению, не удалось подтвердить выполнение задания для адреса:
{check.wallet_address}

Возможно, данные еще не обновились. Попробуйте проверить задание вручную через бота."""
            
            await self.bot.application.bot.send_message(
                chat_id=check.user_id,
                text=message
            )
            
            # Удаляем из очереди
            self.remove_pending_check(check.user_id, check.wallet_index, check.check_type)
            
        except Exception as e:
            print(f"Ошибка отправки уведомления о неудаче: {e}")
    
    async def check_all_users_achievements(self):
        """Проверяет ачивки всех пользователей и отправляет уведомления"""
        try:
            for user_id, user_data in self.bot.users_data.items():
                for wallet_address in user_data.wallet_addresses:
                    # Проверяем ачивку Trendsetter
                    trendsetter_achievement = self.api_client.get_trendsetter_achievement(wallet_address)
                    if trendsetter_achievement and trendsetter_achievement['completed']:
                        # Проверяем, есть ли адрес в общем списке
                        is_in_global_list = wallet_address in self.bot.data_manager.read_wallets()
                        if not is_in_global_list:
                            self.bot.add_wallet_to_global_list(wallet_address)
                            await self.send_achievement_notification(user_id, wallet_address, "Trendsetter")
                    
                    # Проверяем ачивку They Lovin' It
                    token_achievement = self.api_client.get_token_holders_achievement(wallet_address)
                    if token_achievement and token_achievement['completed']:
                        # Проверяем, есть ли адрес в общем списке
                        is_in_global_list = wallet_address in self.bot.data_manager.read_wallets()
                        if not is_in_global_list:
                            self.bot.add_wallet_to_global_list(wallet_address)
                            await self.send_achievement_notification(user_id, wallet_address, "They Lovin' It")
                            
        except Exception as e:
            print(f"Ошибка проверки ачивок всех пользователей: {e}")
    
    async def perform_initial_check(self):
        """Проверяет ачивки всех адресов из текстовых файлов при запуске бота"""
        
        try:
            print("🔍 Выполняется первичная проверка всех адресов и токенов...")
            
            # Показываем текущее состояние файлов
            wallets = self.data_manager.read_wallets()
            boards = self.data_manager.read_boards()
            tokens = self.data_manager.read_tokens()
            
            print(f"📁 Текущее состояние файлов:")
            print(f"   📋 wallets.txt: {len(wallets)} адресов")
            print(f"   📋 boards.txt: {len(boards)} бордов")
            print(f"   📋 tokens.txt: {len(tokens)} токенов")
            
            # Проверяем все адреса из wallets.txt
            wallets_to_remove = []
            wallets_checked = 0
            wallets_with_errors = 0
            
            print(f"\n📋 Проверяем {len(wallets)} адресов кошельков...")
            
            for wallet_address in wallets:
                wallets_checked += 1
                print(f"   [{wallets_checked}/{len(wallets)}] Проверяем адрес: {wallet_address[:10]}...")
                
                # Проверяем ачивку Trendsetter
                trendsetter_achievement = self.api_client.get_trendsetter_achievement(wallet_address)
                if trendsetter_achievement and trendsetter_achievement['completed']:
                    print(f"   ✅ Адрес {wallet_address} получил ачивку Trendsetter - удаляем из wallets.txt")
                    wallets_to_remove.append(wallet_address)
                    
                    # Отправляем уведомление пользователю, если он есть в системе
                    user_id = self.find_user_by_wallet(wallet_address)
                    if user_id:
                        await self.send_achievement_notification(user_id, wallet_address, "Trendsetter")
                elif trendsetter_achievement is None:
                    wallets_with_errors += 1
                    print(f"   ⚠️ Не удалось получить данные для адреса {wallet_address}")
            
            # Удаляем адреса с полученными ачивками
            for wallet in wallets_to_remove:
                self.data_manager.remove_wallet(wallet)
            
            if wallets_to_remove:
                print(f"🗑️ Удалено {len(wallets_to_remove)} адресов из wallets.txt")
            
            # Проверяем все токены из tokens.txt
            tokens = self.data_manager.read_tokens()
            tokens_to_remove = []
            tokens_checked = 0
            tokens_with_errors = 0
            
            print(f"\n📋 Проверяем {len(tokens)} токенов...")
            
            for board_id in tokens:
                tokens_checked += 1
                print(f"   [{tokens_checked}/{len(tokens)}] Проверяем токен: {board_id[:10]}...")
                
                # Проверяем количество холдеров токена
                holders_count = self.api_client.get_token_holders_count(board_id)
                
                if holders_count is not None:
                    print(f"   📊 Токен {board_id} имеет {holders_count} холдеров")
                    if holders_count == 0:
                        print(f"   🚫 Токен {board_id} имеет 0 холдеров (нельзя купить) - удаляем из tokens.txt")
                        tokens_to_remove.append(board_id)
                    elif holders_count >= 10:
                        print(f"   ✅ Токен {board_id} имеет {holders_count} холдеров (≥10) - удаляем из tokens.txt")
                        tokens_to_remove.append(board_id)
                        
                        # Отправляем уведомление пользователю, если он есть в системе
                        user_id = self.find_user_by_board(board_id)
                        if user_id:
                            await self.send_achievement_notification(user_id, board_id, "They Lovin' It")
                    else:
                        print(f"   ⏳ Токен {board_id} имеет {holders_count} холдеров (1-9) - оставляем в tokens.txt")
                else:
                    tokens_with_errors += 1
                    print(f"   ⚠️ Не удалось проверить холдеров для токена {board_id} - пропускаем")
            
            # Удаляем токены с 0 холдеров или достаточным количеством холдеров
            for token in tokens_to_remove:
                self.data_manager.remove_token(token)
            
            if tokens_to_remove:
                print(f"🗑️ Удалено {len(tokens_to_remove)} токенов из tokens.txt")
            
            # Выводим детальное резюме
            print("\n" + "="*60)
            print("📊 РЕЗЮМЕ ПЕРВИЧНОЙ ПРОВЕРКИ")
            print("="*60)
            print(f"✅ Всего проверено адресов: {wallets_checked}")
            print(f"✅ Всего проверено токенов: {tokens_checked}")
            print(f"🗑️ Удалено адресов (выполнены ачивки): {len(wallets_to_remove)}")
            print(f"🗑️ Удалено токенов (0 или ≥10 холдеров): {len(tokens_to_remove)}")
            print(f"⚠️ Адресов с ошибками: {wallets_with_errors}")
            print(f"⚠️ Токенов с ошибками: {tokens_with_errors}")
            print(f"📈 Успешно обработано: {wallets_checked - wallets_with_errors + tokens_checked - tokens_with_errors}")
            
            # Показываем детальную статистику по токенам
            if tokens_checked > 0:
                print(f"\n📊 ДЕТАЛЬНАЯ СТАТИСТИКА ПО ТОКЕНАМ:")
                print(f"   📋 Всего токенов проверено: {tokens_checked}")
                print(f"   ✅ Токенов с 1-9 холдеров (остались): {tokens_checked - len(tokens_to_remove) - tokens_with_errors}")
                print(f"   🗑️ Токенов с 0 или ≥10 холдеров (удалены): {len(tokens_to_remove)}")
                print(f"   ⚠️ Токенов с ошибками API: {tokens_with_errors}")
            
            # Показываем финальное состояние файлов
            final_wallets = self.data_manager.read_wallets()
            final_tokens = self.data_manager.read_tokens()
            print(f"\n📁 Финальное состояние файлов:")
            print(f"   📋 wallets.txt: {len(final_wallets)} адресов (было {len(wallets)})")
            print(f"   📋 tokens.txt: {len(final_tokens)} токенов (было {len(tokens)})")
            
            print("="*60)
            print("✅ Первичная проверка завершена. В дальнейшем проверки будут выполняться только при добавлении новых адресов/токенов.")
            
        except Exception as e:
            print(f"Ошибка первичной проверки ачивок: {e}")
    
    def find_user_by_wallet(self, wallet_address: str) -> int:
        """Находит пользователя по адресу кошелька"""
        for user_id, user_data in self.bot.users_data.items():
            if wallet_address in user_data.wallet_addresses:
                return user_id
        return None
    
    def find_user_by_board(self, board_id: str) -> int:
        """Находит пользователя по ID борда"""
        for user_id, user_data in self.bot.users_data.items():
            if board_id in user_data.board_addresses:
                return user_id
        return None
    
    async def send_achievement_notification(self, user_id: int, wallet_address: str, achievement_name: str):
        """Отправляет уведомление о получении ачивки (только один раз)"""
        try:
            # Проверяем, было ли уже отправлено уведомление
            if self.bot.is_achievement_notification_sent(user_id, wallet_address, achievement_name):
                print(f"Уведомление о получении ачивки {achievement_name} для адреса {wallet_address} уже было отправлено пользователю {user_id}")
                return
            
            message = f"""🎉 Поздравляем!

Ачивка "{achievement_name}" успешно получена для адреса:
{wallet_address}

Ваш адрес добавлен в общий список для помощи другим пользователям!"""
            
            await self.bot.application.bot.send_message(
                chat_id=user_id,
                text=message
            )
            
            # Отмечаем, что уведомление было отправлено
            self.bot.mark_achievement_notification_sent(user_id, wallet_address, achievement_name)
            
            print(f"Отправлено уведомление о получении ачивки {achievement_name} пользователю {user_id}")
            
        except Exception as e:
            print(f"Ошибка отправки уведомления о получении ачивки: {e}")
    
    async def check_waiting_users(self):
        """Проверяет ожидающих пользователей на появление новых адресов/токенов"""
        users_to_remove = []
        
        for key, waiting_user in self.waiting_users.items():
            try:
                # Проверяем, прошло ли достаточно времени с последней проверки
                time_since_last_check = datetime.now() - waiting_user.last_check
                if time_since_last_check.total_seconds() < 600:  # 10 минут
                    continue
                
                waiting_user.last_check = datetime.now()
                
                # Проверяем доступность адресов/токенов
                if waiting_user.check_type == "followers":
                    # Получаем все адреса пользователя для исключения
                    user_addresses = set()
                    if waiting_user.user_id in self.bot.users_data:
                        user_addresses = set(self.bot.users_data[waiting_user.user_id].wallet_addresses)
                    user_addresses.add(waiting_user.wallet_address)
                    
                    # Получаем доступные адреса
                    available_wallets = [w for w in self.data_manager.read_wallets() if w not in user_addresses]
                    
                    if len(available_wallets) >= waiting_user.needed_count:
                        # Достаточно адресов - уведомляем пользователя
                        await self.send_new_addresses_notification(waiting_user, len(available_wallets))
                        users_to_remove.append(key)
                
                elif waiting_user.check_type == "tokens":
                    # Получаем все борды пользователя для исключения
                    user_boards = set()
                    if waiting_user.user_id in self.bot.users_data:
                        user_boards = set(self.bot.users_data[waiting_user.user_id].board_addresses)
                    
                    # Получаем доступные токены
                    available_tokens = [t for t in self.data_manager.read_tokens() if t not in user_boards]
                    
                    if len(available_tokens) >= waiting_user.needed_count:
                        # Достаточно токенов - уведомляем пользователя
                        await self.send_new_tokens_notification(waiting_user, len(available_tokens))
                        users_to_remove.append(key)
                
            except Exception as e:
                print(f"Ошибка проверки ожидающего пользователя {waiting_user.user_id}: {e}")
                users_to_remove.append(key)
        
        # Удаляем пользователей, которым отправили уведомления
        for key in users_to_remove:
            if key in self.waiting_users:
                del self.waiting_users[key]
        
        if users_to_remove:
            self.save_waiting_users()
    
    async def send_new_addresses_notification(self, waiting_user: WaitingUser, available_count: int):
        """Отправляет уведомление о появлении новых адресов"""
        try:
            # Получаем язык пользователя
            user_data = self.bot.users_data.get(waiting_user.user_id)
            language = user_data.language if user_data else 'ru'
            
            if language == 'en':
                message = f"""🎉 New addresses available!

Now {available_count} addresses are available for subscription.
You can go to the "Followers" menu and complete the task for address:
{waiting_user.wallet_address}"""
            else:
                message = f"""🎉 Появились новые адреса!

Теперь доступно {available_count} адресов для подписки.
Вы можете зайти в меню "Followers" и доделать задание для адреса:
{waiting_user.wallet_address}"""
            
            await self.bot.application.bot.send_message(
                chat_id=waiting_user.user_id,
                text=message
            )
            
            print(f"Отправлено уведомление о новых адресах пользователю {waiting_user.user_id}")
            
        except Exception as e:
            print(f"Ошибка отправки уведомления о новых адресах: {e}")
    
    async def send_new_tokens_notification(self, waiting_user: WaitingUser, available_count: int):
        """Отправляет уведомление о появлении новых токенов"""
        try:
            # Получаем язык пользователя
            user_data = self.bot.users_data.get(waiting_user.user_id)
            language = user_data.language if user_data else 'ru'
            
            if language == 'en':
                message = f"""🎉 New tokens available!

Now {available_count} tokens are available for purchase.
You can go to the "Token holders" menu and complete the task for address:
{waiting_user.wallet_address}"""
            else:
                message = f"""🎉 Появились новые токены!

Теперь доступно {available_count} токенов для покупки.
Вы можете зайти в меню "Token holders" и доделать задание для адреса:
{waiting_user.wallet_address}"""
            
            await self.bot.application.bot.send_message(
                chat_id=waiting_user.user_id,
                text=message
            )
            
            print(f"Отправлено уведомление о новых токенах пользователю {waiting_user.user_id}")
            
        except Exception as e:
            print(f"Ошибка отправки уведомления о новых токенах: {e}")
    
    async def process_pending_checks(self):
        """Обрабатывает все ожидающие проверки"""
        checks_to_remove = []
        
        for key, check in self.pending_checks.items():
            try:
                # Проверяем, не истекло ли время
                if check.attempts >= check.max_attempts:
                    await self.send_failure_notification(check)
                    checks_to_remove.append(key)
                    continue
                
                # Проверяем, прошло ли достаточно времени с последней проверки
                time_since_last_check = datetime.now() - check.last_check
                if time_since_last_check.total_seconds() < self.check_interval:
                    continue
                
                # Выполняем проверку
                check.attempts += 1
                check.last_check = datetime.now()
                
                success = False
                if check.check_type == "followers":
                    success = await self.check_followers_task(check)
                elif check.check_type == "tokens":
                    success = await self.check_tokens_task(check)
                
                if success:
                    checks_to_remove.append(key)
                else:
                    print(f"Проверка {check.attempts}/{check.max_attempts} для пользователя {check.user_id}")
                
            except Exception as e:
                print(f"Ошибка обработки проверки для пользователя {check.user_id}: {e}")
                checks_to_remove.append(key)
        
        # Удаляем завершенные проверки
        for key in checks_to_remove:
            if key in self.pending_checks:
                del self.pending_checks[key]
        
        if checks_to_remove:
            self.save_pending_checks()
    
    async def start_background_checking(self):
        """Запускает фоновую проверку"""
        if self.is_running:
            return
        
        self.is_running = True
        print("Запущена фоновая проверка заданий...")
        
        # Выполняем первичную проверку при запуске
        await self.perform_initial_check()
        
        while self.is_running:
            try:
                # Обрабатываем ожидающие проверки
                await self.process_pending_checks()
                
                # Проверяем ачивки всех пользователей (реже - каждые 10 минут)
                if hasattr(self, '_last_achievement_check'):
                    time_since_last_achievement_check = datetime.now() - self._last_achievement_check
                    if time_since_last_achievement_check.total_seconds() >= 600:  # 10 минут
                        await self.check_all_users_achievements()
                        await self.check_waiting_users()
                        self._last_achievement_check = datetime.now()
                else:
                    await self.check_all_users_achievements()
                    await self.check_waiting_users()
                    self._last_achievement_check = datetime.now()
                
                await asyncio.sleep(60)  # Проверяем каждую минуту
            except Exception as e:
                print(f"Ошибка в фоновой проверке: {e}")
                await asyncio.sleep(60)
    
    def stop_background_checking(self):
        """Останавливает фоновую проверку"""
        self.is_running = False
        print("Фоновая проверка остановлена")

# Пример использования
if __name__ == "__main__":
    # Это будет использоваться в основном боте
    pass
