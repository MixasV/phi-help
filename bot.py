import os
import json
import random
import re
from typing import Dict, List, Optional
from dataclasses import dataclass
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
from phi_api import PHIAPI
from data_utils import DataManager
from background_checker import BackgroundChecker

# Загружаем переменные окружения
load_dotenv()

@dataclass
class UserData:
    wallet_addresses: List[str]
    board_addresses: List[str]
    completed_followers_tasks: int = 0  # Количество выполненных заданий по фолловерам
    completed_token_tasks: int = 0      # Количество выполненных заданий по токенам

class PHIBot:
    def __init__(self):
        self.bot_token = os.getenv('BOT_TOKEN')
        self.wallets_file = os.getenv('WALLETS_FILE', 'wallets.txt')
        self.boards_file = os.getenv('BOARDS_FILE', 'boards.txt')
        self.tokens_file = os.getenv('TOKENS_FILE', 'tokens.txt')
        self.users_data_file = os.getenv('USERS_DATA_FILE', 'users_data.json')
        self.followers_threshold = int(os.getenv('FOLLOWERS_THRESHOLD', '10'))
        self.token_holders_threshold = int(os.getenv('TOKEN_HOLDERS_THRESHOLD', '10'))
        
        # Инициализируем API клиент и менеджер данных
        self.api_client = PHIAPI()
        self.data_manager = DataManager(self.wallets_file, self.boards_file, self.tokens_file)
        
        # Инициализируем систему фоновой проверки
        self.background_checker = None
        
        # Загружаем данные пользователей
        self.users_data = self.load_users_data()
        
        # Создаем файлы данных если их нет
        self.ensure_data_files()
    
    def load_users_data(self) -> Dict[int, UserData]:
        """Загружает данные пользователей из JSON файла"""
        try:
            if os.path.exists(self.users_data_file):
                with open(self.users_data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return {
                        int(user_id): UserData(
                            wallet_addresses=user_data.get('wallet_addresses', []),
                            board_addresses=user_data.get('board_addresses', []),
                            completed_followers_tasks=user_data.get('completed_followers_tasks', 0),
                            completed_token_tasks=user_data.get('completed_token_tasks', 0)
                        )
                        for user_id, user_data in data.items()
                    }
        except Exception as e:
            print(f"Ошибка загрузки данных пользователей: {e}")
        return {}
    
    def save_users_data(self):
        """Сохраняет данные пользователей в JSON файл"""
        try:
            data = {
                str(user_id): {
                    'wallet_addresses': user_data.wallet_addresses,
                    'board_addresses': user_data.board_addresses,
                    'completed_followers_tasks': user_data.completed_followers_tasks,
                    'completed_token_tasks': user_data.completed_token_tasks
                }
                for user_id, user_data in self.users_data.items()
            }
            with open(self.users_data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка сохранения данных пользователей: {e}")
    
    def ensure_data_files(self):
        """Создает файлы данных если их нет"""
        for file_path in [self.wallets_file, self.boards_file, self.tokens_file]:
            if not os.path.exists(file_path):
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write('')
    
    def is_valid_ethereum_address(self, address: str) -> bool:
        """Проверяет валидность Ethereum адреса"""
        pattern = r'^0x[a-fA-F0-9]{40}$'
        return bool(re.match(pattern, address))
    
    def extract_board_id(self, board_input: str) -> Optional[str]:
        """Извлекает ID борда из ссылки или адреса"""
        # Если это ссылка
        if 'phi.box/board/' in board_input:
            return board_input.split('phi.box/board/')[-1]
        # Если это UUID
        uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        if re.match(uuid_pattern, board_input, re.IGNORECASE):
            return board_input
        return None
    
    def get_main_menu_keyboard(self, user_id: int) -> InlineKeyboardMarkup:
        """Создает клавиатуру главного меню"""
        user_data = self.users_data.get(user_id, UserData([], []))
        wallet_count = len(user_data.wallet_addresses)
        board_count = len(user_data.board_addresses)
        
        keyboard = [
            [InlineKeyboardButton("Мои данные", callback_data="my_data")],
            [InlineKeyboardButton("Фолловеры", callback_data="followers")],
            [InlineKeyboardButton("Token holders", callback_data="token_holders")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def get_main_menu_message(self, user_id: int) -> str:
        """Создает сообщение главного меню"""
        user_data = self.users_data.get(user_id, UserData([], []))
        wallet_count = len(user_data.wallet_addresses)
        board_count = len(user_data.board_addresses)
        
        message = f"""🤖 Добро пожаловать в PHI Helper Bot!

Вы можете добавить свои адреса кошельков для выполнения ачивок, а также свои борды.

📊 Ваша статистика:
• Адресов кошельков: {wallet_count}
• Бордов: {board_count}

Выберите действие:"""
        return message
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        user_id = update.effective_user.id
        
        # Инициализируем пользователя если его нет
        if user_id not in self.users_data:
            self.users_data[user_id] = UserData([], [])
            self.save_users_data()
        
        message = self.get_main_menu_message(user_id)
        keyboard = self.get_main_menu_keyboard(user_id)
        
        await update.message.reply_text(message, reply_markup=keyboard)
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик нажатий на кнопки"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        data = query.data
        
        if data == "my_data":
            await self.show_my_data_menu(query)
        elif data == "add_wallets":
            await self.show_add_wallets_menu(query)
            # Устанавливаем режим для обработки адресов
            context.user_data['mode'] = 'добавление адресов'
        elif data == "add_boards":
            await self.show_add_boards_menu(query)
            # Устанавливаем режим для обработки бордов
            context.user_data['mode'] = 'добавление бордов'
        elif data == "followers":
            await self.show_followers_menu(query)
        elif data == "token_holders":
            await self.show_token_holders_menu(query)
        elif data == "back_to_main":
            await self.show_main_menu(query)
        elif data.startswith("followers_wallet_"):
            wallet_index = int(data.split("_")[2])
            await self.handle_followers_wallet_selection(query, wallet_index)
        elif data.startswith("token_wallet_"):
            wallet_index = int(data.split("_")[2])
            await self.handle_token_wallet_selection(query, wallet_index)
        elif data.startswith("followers_refresh_"):
            wallet_index = int(data.split("_")[2])
            await self.handle_followers_refresh(query, wallet_index)
        elif data.startswith("followers_done_"):
            wallet_index = int(data.split("_")[2])
            await self.handle_followers_done(query, wallet_index)
        elif data.startswith("followers_continue_"):
            wallet_index = int(data.split("_")[2])
            await self.handle_followers_continue(query, wallet_index)
        elif data.startswith("token_refresh_"):
            wallet_index = int(data.split("_")[2])
            await self.handle_token_refresh(query, wallet_index)
        elif data.startswith("token_done_"):
            wallet_index = int(data.split("_")[2])
            await self.handle_token_done(query, wallet_index)
        elif data.startswith("token_continue_"):
            wallet_index = int(data.split("_")[2])
            await self.handle_token_continue(query, wallet_index)
    
    async def show_main_menu(self, query):
        """Показывает главное меню"""
        user_id = query.from_user.id
        message = self.get_main_menu_message(user_id)
        keyboard = self.get_main_menu_keyboard(user_id)
        
        await query.edit_message_text(message, reply_markup=keyboard)
    
    async def show_my_data_menu(self, query):
        """Показывает меню 'Мои данные'"""
        user_id = query.from_user.id
        user_data = self.users_data.get(user_id, UserData([], []))
        
        message = f"""📋 Мои данные

Адресов кошельков: {len(user_data.wallet_addresses)}
Бордов: {len(user_data.board_addresses)}

Выберите действие:"""
        
        keyboard = [
            [InlineKeyboardButton("Добавить адреса", callback_data="add_wallets")],
            [InlineKeyboardButton("Добавить борды", callback_data="add_boards")],
            [InlineKeyboardButton("← Назад", callback_data="back_to_main")]
        ]
        
        await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def show_add_wallets_menu(self, query):
        """Показывает меню добавления адресов"""
        message = """💳 Добавление адресов кошельков

Отправьте адреса кошельков в формате EVM (начинающиеся с 0x).
Можно отправить несколько адресов, каждый с новой строки.

Пример:
0xC7f9154a72524097B1323961F584f7047b875271
0x1234567890123456789012345678901234567890

Отправьте адреса или нажмите "Отмена":"""
        
        keyboard = [
            [InlineKeyboardButton("Отмена", callback_data="my_data")]
        ]
        
        await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def show_add_boards_menu(self, query):
        """Показывает меню добавления бордов"""
        message = """🎯 Добавление бордов

Отправьте ссылки на борды или их ID.
Можно отправить несколько бордов, каждый с новой строки.

Примеры:
https://phi.box/board/5ced1c01-dca1-4021-8a9d-870955020444
5ced1c01-dca1-4021-8a9d-870955020444

Отправьте борды или нажмите "Отмена":"""
        
        keyboard = [
            [InlineKeyboardButton("Отмена", callback_data="my_data")]
        ]
        
        await query.edit_message_text(
            text=message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )
    
    async def show_followers_menu(self, query):
        """Показывает меню фолловеров"""
        user_id = query.from_user.id
        user_data = self.users_data.get(user_id, UserData([], []))
        
        if not user_data.wallet_addresses:
            message = """👥 Фолловеры

У вас пока нет добавленных адресов кошельков.
Сначала добавьте адреса, чтобы получить фолловеров."""
            
            keyboard = [
                [InlineKeyboardButton("Добавить адреса", callback_data="add_wallets")],
                [InlineKeyboardButton("← Назад", callback_data="back_to_main")]
            ]
        else:
            message = """👥 Фолловеры

Выберите адрес кошелька для получения фолловеров:"""
            
            keyboard = []
            for i, address in enumerate(user_data.wallet_addresses):
                short_address = f"{address[:6]}...{address[-4:]}"
                keyboard.append([InlineKeyboardButton(
                    f"📱 {short_address}", 
                    callback_data=f"followers_wallet_{i}"
                )])
            
            keyboard.append([InlineKeyboardButton("← Назад", callback_data="back_to_main")])
        
        await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def show_token_holders_menu(self, query):
        """Показывает меню token holders"""
        user_id = query.from_user.id
        user_data = self.users_data.get(user_id, UserData([], []))
        
        if not user_data.wallet_addresses or not user_data.board_addresses:
            message = """🪙 Token holders

У вас пока нет добавленных адресов кошельков или бордов.
Сначала добавьте их, чтобы получить холдеров токенов."""
            
            keyboard = [
                [InlineKeyboardButton("Добавить адреса", callback_data="add_wallets")],
                [InlineKeyboardButton("Добавить борды", callback_data="add_boards")],
                [InlineKeyboardButton("← Назад", callback_data="back_to_main")]
            ]
        else:
            message = """🪙 Token holders

Выберите адрес кошелька для получения холдеров токенов:"""
            
            keyboard = []
            for i, address in enumerate(user_data.wallet_addresses):
                short_address = f"{address[:6]}...{address[-4:]}"
                keyboard.append([InlineKeyboardButton(
                    f"📱 {short_address}", 
                    callback_data=f"token_wallet_{i}"
                )])
            
            keyboard.append([InlineKeyboardButton("← Назад", callback_data="back_to_main")])
        
        await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def handle_followers_wallet_selection(self, query, wallet_index: int):
        """Обрабатывает выбор кошелька для фолловеров"""
        user_id = query.from_user.id
        user_data = self.users_data.get(user_id, UserData([], []))
        
        if wallet_index >= len(user_data.wallet_addresses):
            await query.edit_message_text("❌ Ошибка: неверный индекс кошелька")
            return
        
        wallet_address = user_data.wallet_addresses[wallet_index]
        
        # Проверяем ачивку Trendsetter
        achievement = self.api_client.get_trendsetter_achievement(wallet_address)
        
        if not achievement:
            message = f"""❌ Ошибка проверки ачивки

Не удалось получить информацию об ачивке для адреса:
{wallet_address}

Попробуйте позже."""
            
            keyboard = [
                [InlineKeyboardButton("← Назад", callback_data="followers")]
            ]
        elif achievement['completed']:
            # Ачивка уже выполнена - проверяем, есть ли адрес в общем списке
            is_in_global_list = wallet_address in self.data_manager.read_wallets()
            
            if is_in_global_list:
                # Адрес уже в общем списке - не показываем это пользователю
                message = f"""✅ Ачивка уже выполнена!

🎉 Поздравляем! Ачивка "Trendsetter" уже выполнена для адреса:
{wallet_address}

Хотите продолжить и помочь другим пользователям?"""
            else:
                # Адрес не в общем списке - добавляем его
                self.add_wallet_to_global_list(wallet_address)
                message = f"""✅ Ачивка уже выполнена!

🎉 Поздравляем! Ачивка "Trendsetter" уже выполнена для адреса:
{wallet_address}

Ваш адрес добавлен в общий список для помощи другим пользователям.
Хотите продолжить помогать?"""
            
            keyboard = [
                [InlineKeyboardButton("Продолжить", callback_data=f"followers_continue_{wallet_index}")],
                [InlineKeyboardButton("← Назад", callback_data="followers")]
            ]
        else:
            remaining = achievement['remaining']
            progress = achievement['progress_count']
            required = achievement['required_count']
            
            # Учитываем уже выполненные задания пользователем
            user_data = self.users_data.get(user_id, UserData([], []))
            completed_tasks = user_data.completed_followers_tasks
            
            # Если пользователь уже выполнял задания, уменьшаем количество
            if completed_tasks > 0:
                remaining = max(0, remaining - completed_tasks)
            
            message = f"""📊 Статус ачивки "Trendsetter"

Адрес: {wallet_address}
Прогресс: {progress}/{required}
Осталось получить: {remaining} фолловеров
Выполнено заданий: {completed_tasks}

Генерируем ссылки для подписки..."""
            
            await query.edit_message_text(message)
            
            # Генерируем ссылки на профили
            profile_links = self.generate_followers_links(remaining, wallet_address, user_id)
            
            if profile_links:
                # Сохраняем список адресов для проверки
                target_addresses = self.extract_addresses_from_links(profile_links)
                
                # Сохраняем в контексте пользователя для последующей проверки
            # Сохраняем данные в контексте пользователя
            if user_id not in self.users_data:
                self.users_data[user_id] = UserData([], [])
            
            # Сохраняем цели для фолловеров в данных пользователя
            user_data = self.users_data[user_id]
            if not hasattr(user_data, 'followers_targets'):
                user_data.followers_targets = {}
            if not hasattr(user_data, 'followers_user_wallet'):
                user_data.followers_user_wallet = {}
            
            user_data.followers_targets[wallet_index] = target_addresses
            user_data.followers_user_wallet[wallet_index] = wallet_address
            self.save_users_data()
            
            # Показываем все доступные адреса
            message = f"""👥 Фолловеры для адреса {wallet_address[:10]}...

📋 Доступно адресов: {len(profile_links)} из {remaining} необходимых

Подпишитесь на следующие профили:
{chr(10).join([f"{i+1}. {link}" for i, link in enumerate(profile_links)])}

После подписки нажмите "Готово"."""
            
            keyboard = [
                [InlineKeyboardButton("🔄 Обновить", callback_data=f"followers_refresh_{wallet_index}")],
                [InlineKeyboardButton("✅ Готово", callback_data=f"followers_done_{wallet_index}")],
                [InlineKeyboardButton("❌ Отмена", callback_data="followers")]
            ]
            
            # Если недостаточно адресов, добавляем в очередь ожидания
            if len(profile_links) < remaining:
                self.add_wallet_to_global_list(wallet_address)
                
                if self.background_checker:
                    self.background_checker.add_waiting_user(
                        user_id=user_id,
                        wallet_index=wallet_index,
                        wallet_address=wallet_address,
                        check_type="followers",
                        needed_count=remaining
                    )
                
                # Добавляем информацию о том, что недостаточно адресов
                message += f"""

⏳ Недостаточно адресов для полного выполнения задания.
Мы уведомим вас, когда появятся новые адреса."""
        
        await query.edit_message_text(
            text=message,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )
    
    async def handle_token_wallet_selection(self, query, wallet_index: int):
        """Обрабатывает выбор кошелька для token holders"""
        user_id = query.from_user.id
        user_data = self.users_data.get(user_id, UserData([], []))
        
        if wallet_index >= len(user_data.wallet_addresses):
            await query.edit_message_text("❌ Ошибка: неверный индекс кошелька")
            return
        
        wallet_address = user_data.wallet_addresses[wallet_index]
        
        # Проверяем ачивку They Lovin' It
        achievement = self.api_client.get_token_holders_achievement(wallet_address)
        
        if not achievement:
            message = f"""❌ Ошибка проверки ачивки

Не удалось получить информацию об ачивке для адреса:
{wallet_address}

Попробуйте позже."""
            
            keyboard = [
                [InlineKeyboardButton("← Назад", callback_data="token_holders")]
            ]
        elif achievement['completed']:
            # Ачивка уже выполнена - проверяем, есть ли адрес в общем списке
            is_in_global_list = wallet_address in self.data_manager.read_wallets()
            
            if is_in_global_list:
                # Адрес уже в общем списке - не показываем это пользователю
                message = f"""✅ Ачивка уже выполнена!

🎉 Поздравляем! Ачивка "They Lovin' It" уже выполнена для адреса:
{wallet_address}

Хотите продолжить и помочь другим пользователям?"""
            else:
                # Адрес не в общем списке - добавляем его
                self.add_wallet_to_global_list(wallet_address)
                message = f"""✅ Ачивка уже выполнена!

🎉 Поздравляем! Ачивка "They Lovin' It" уже выполнена для адреса:
{wallet_address}

Ваш адрес добавлен в общий список для помощи другим пользователям.
Хотите продолжить помогать?"""
            
            keyboard = [
                [InlineKeyboardButton("Продолжить", callback_data=f"token_continue_{wallet_index}")],
                [InlineKeyboardButton("← Назад", callback_data="token_holders")]
            ]
        else:
            remaining = achievement['remaining']
            progress = achievement['progress_count']
            required = achievement['required_count']
            
            # Учитываем уже выполненные задания пользователем
            user_data = self.users_data.get(user_id, UserData([], []))
            completed_tasks = user_data.completed_token_tasks
            
            # Если пользователь уже выполнял задания, уменьшаем количество
            if completed_tasks > 0:
                remaining = max(0, remaining - completed_tasks)
            
            message = f"""📊 Статус ачивки "They Lovin' It"

Адрес: {wallet_address}
Прогресс: {progress}/{required}
Осталось получить: {remaining} холдеров
Выполнено заданий: {completed_tasks}

Генерируем ссылки для покупки токенов..."""
            
            await query.edit_message_text(message)
            
            # Генерируем ссылки на токены
            token_links = self.generate_token_links(remaining, wallet_address, user_id)
            
            if token_links:
                # Сохраняем список токенов для проверки
                target_board_ids = self.extract_board_ids_from_links(token_links)
                
                # Сохраняем в контексте пользователя для последующей проверки
            # Сохраняем данные в контексте пользователя
            if user_id not in self.users_data:
                self.users_data[user_id] = UserData([], [])
            
            # Сохраняем цели для токенов в данных пользователя
            user_data = self.users_data[user_id]
            if not hasattr(user_data, 'token_targets'):
                user_data.token_targets = {}
            if not hasattr(user_data, 'token_user_wallet'):
                user_data.token_user_wallet = {}
            
            user_data.token_targets[wallet_index] = target_board_ids
            user_data.token_user_wallet[wallet_index] = wallet_address
            self.save_users_data()
            
            # Показываем все доступные токены
            message = f"""🪙 Token holders для адреса {wallet_address[:10]}...

📋 Доступно токенов: {len(token_links)} из {remaining} необходимых

Купите следующие токены:
{chr(10).join([f"{i+1}. {link}" for i, link in enumerate(token_links)])}

После покупки нажмите "Готово"."""
            
            keyboard = [
                [InlineKeyboardButton("🔄 Обновить", callback_data=f"token_refresh_{wallet_index}")],
                [InlineKeyboardButton("✅ Готово", callback_data=f"token_done_{wallet_index}")],
                [InlineKeyboardButton("❌ Отмена", callback_data="token_holders")]
            ]
            
            # Если недостаточно токенов, добавляем в очередь ожидания
            if len(token_links) < remaining:
                self.add_wallet_to_global_list(wallet_address)
                
                if self.background_checker:
                    self.background_checker.add_waiting_user(
                        user_id=user_id,
                        wallet_index=wallet_index,
                        wallet_address=wallet_address,
                        check_type="tokens",
                        needed_count=remaining
                    )
                
                # Добавляем информацию о том, что недостаточно токенов
                message += f"""

⏳ Недостаточно токенов для полного выполнения задания.
Мы уведомим вас, когда появятся новые токены."""
        
        await query.edit_message_text(
            text=message,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )
    
    def generate_followers_links(self, count: int, exclude_wallet: str, user_id: int = None) -> List[str]:
        """Генерирует ссылки на профили для подписки"""
        try:
            # Получаем все адреса пользователя для исключения
            user_addresses = set()
            if user_id and user_id in self.users_data:
                user_addresses = set(self.users_data[user_id].wallet_addresses)
            
            # Добавляем выбранный кошелек в исключения
            user_addresses.add(exclude_wallet)
            
            # Получаем случайные кошельки, исключая все адреса пользователя
            available_wallets = self.data_manager.get_random_wallets(count, user_addresses)
            
            if len(available_wallets) < count:
                # Если недостаточно кошельков, берем все доступные
                all_wallets = self.data_manager.read_wallets()
                available_wallets = [w for w in all_wallets if w not in user_addresses]
            
            # Создаем HTML-ссылки на профили
            links = []
            for wallet in available_wallets[:count]:
                links.append(f'<a href="https://phi.box/profile/{wallet}">{wallet}</a>')
            
            return links
            
        except Exception as e:
            print(f"Ошибка генерации ссылок на профили: {e}")
            return []
    
    def generate_token_links(self, count: int, exclude_wallet: str, user_id: int = None) -> List[str]:
        """Генерирует ссылки на токены для покупки"""
        try:
            # Получаем все борды пользователя для исключения
            user_boards = set()
            if user_id and user_id in self.users_data:
                user_boards = set(self.users_data[user_id].board_addresses)
            
            # Получаем случайные токены, исключая собственные борды пользователя
            available_tokens = self.data_manager.get_random_tokens(count, user_boards)
            
            if len(available_tokens) < count:
                # Если недостаточно токенов, берем все доступные
                all_tokens = self.data_manager.read_tokens()
                available_tokens = [t for t in all_tokens if t not in user_boards]
            
            # Создаем HTML-ссылки на токены
            links = []
            for board_id in available_tokens[:count]:
                links.append(f'<a href="https://phi.box/board/{board_id}?referrer={exclude_wallet}">{board_id}</a>')
            
            return links
            
        except Exception as e:
            print(f"Ошибка генерации ссылок на токены: {e}")
            return []
    
    async def handle_followers_refresh(self, query, wallet_index: int):
        """Обрабатывает обновление ссылок для фолловеров"""
        user_id = query.from_user.id
        user_data = self.users_data.get(user_id, UserData([], []))
        
        if wallet_index >= len(user_data.wallet_addresses):
            await query.edit_message_text("❌ Ошибка: неверный индекс кошелька")
            return
        
        wallet_address = user_data.wallet_addresses[wallet_index]
        
        # Проверяем ачивку снова
        achievement = self.api_client.get_trendsetter_achievement(wallet_address)
        
        if not achievement or achievement['completed']:
            await self.handle_followers_wallet_selection(query, wallet_index)
            return
        
        remaining = achievement['remaining']
        
        # Генерируем новые ссылки
        profile_links = self.generate_followers_links(remaining, wallet_address, user_id)
        
        if profile_links:
            # Сохраняем новый список адресов для проверки
            target_addresses = self.extract_addresses_from_links(profile_links)
            
            # Сохраняем в контексте пользователя для последующей проверки
            # Сохраняем данные в контексте пользователя
            if user_id not in self.users_data:
                self.users_data[user_id] = UserData([], [])
            
            # Сохраняем цели для фолловеров в данных пользователя
            user_data = self.users_data[user_id]
            if not hasattr(user_data, 'followers_targets'):
                user_data.followers_targets = {}
            if not hasattr(user_data, 'followers_user_wallet'):
                user_data.followers_user_wallet = {}
            
            user_data.followers_targets[wallet_index] = target_addresses
            user_data.followers_user_wallet[wallet_index] = wallet_address
            self.save_users_data()
            
            links_text = "\n".join([f"• {link}" for link in profile_links])
            message = f"""🔄 Обновленные ссылки для подписки

Подпишитесь на эти профили для получения {remaining} фолловеров:

{links_text}

После подписки нажмите "Готово"."""
            
            keyboard = [
                [InlineKeyboardButton("🔄 Обновить", callback_data=f"followers_refresh_{wallet_index}")],
                [InlineKeyboardButton("✅ Готово", callback_data=f"followers_done_{wallet_index}")],
                [InlineKeyboardButton("❌ Отмена", callback_data="followers")]
            ]
        else:
            message = f"""❌ Недостаточно адресов

В системе недостаточно адресов для генерации ссылок."""
            
            keyboard = [
                [InlineKeyboardButton("← Назад", callback_data="followers")]
            ]
        
        await query.edit_message_text(
            text=message,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )
    
    async def handle_followers_done(self, query, wallet_index: int):
        """Обрабатывает завершение подписок"""
        user_id = query.from_user.id
        user_data = self.users_data.get(user_id, UserData([], []))
        
        if wallet_index >= len(user_data.wallet_addresses):
            await query.edit_message_text("❌ Ошибка: неверный индекс кошелька")
            return
        
        wallet_address = user_data.wallet_addresses[wallet_index]
        
        # Получаем список адресов, на которые нужно было подписаться
        # Это нужно сохранять в контексте или в данных пользователя
        # Пока используем упрощенную версию - проверяем ачивку
        
        # Проверяем ачивку снова
        achievement = self.api_client.get_trendsetter_achievement(wallet_address)
        
        if not achievement:
            message = f"""❌ Ошибка проверки ачивки

Не удалось проверить выполнение ачивки.
Попробуйте позже."""
            
            keyboard = [
                [InlineKeyboardButton("← Назад", callback_data="followers")]
            ]
        elif achievement['completed']:
            # Ачивка выполнена - проверяем, есть ли адрес в общем списке
            is_in_global_list = wallet_address in self.data_manager.read_wallets()
            
            if not is_in_global_list:
                self.add_wallet_to_global_list(wallet_address)
                message = f"""🎉 Поздравляем!

Ачивка "Trendsetter" успешно выполнена для адреса:
{wallet_address}

Ваш адрес добавлен в общий список для помощи другим пользователям.
Выполнено заданий: {user_data.completed_followers_tasks}"""
            else:
                message = f"""🎉 Поздравляем!

Ачивка "Trendsetter" успешно выполнена для адреса:
{wallet_address}

Выполнено заданий: {user_data.completed_followers_tasks}"""
            
            user_data.completed_followers_tasks += 1
            self.save_users_data()
            
            keyboard = [
                [InlineKeyboardButton("← Главное меню", callback_data="back_to_main")]
            ]
        else:
            # Ачивка еще не выполнена - проверяем конкретные подписки
            await self.check_specific_followers(query, wallet_index, wallet_address)
    
    async def handle_followers_continue(self, query, wallet_index: int):
        """Обрабатывает продолжение помощи другим пользователям"""
        # Генерируем случайные ссылки для помощи другим
        available_wallets = self.data_manager.get_random_wallets(5)
        
        if available_wallets:
            links_text = "\n".join([f"• <a href=\"https://phi.box/profile/{wallet}\">{wallet}</a>" for wallet in available_wallets])
            message = f"""🤝 Помощь другим пользователям

Подпишитесь на эти профили, чтобы помочь другим получить ачивку:

{links_text}

Спасибо за помощь! 🙏"""
            
            keyboard = [
                [InlineKeyboardButton("← Главное меню", callback_data="back_to_main")]
            ]
        else:
            message = f"""❌ Нет доступных адресов

В системе пока нет других адресов для помощи."""
            
            keyboard = [
                [InlineKeyboardButton("← Главное меню", callback_data="back_to_main")]
            ]
        
        await query.edit_message_text(
            text=message,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )
    
    async def handle_token_refresh(self, query, wallet_index: int):
        """Обрабатывает обновление ссылок для токенов"""
        user_id = query.from_user.id
        user_data = self.users_data.get(user_id, UserData([], []))
        
        if wallet_index >= len(user_data.wallet_addresses):
            await query.edit_message_text("❌ Ошибка: неверный индекс кошелька")
            return
        
        wallet_address = user_data.wallet_addresses[wallet_index]
        
        # Проверяем ачивку снова
        achievement = self.api_client.get_token_holders_achievement(wallet_address)
        
        if not achievement or achievement['completed']:
            await self.handle_token_wallet_selection(query, wallet_index)
            return
        
        remaining = achievement['remaining']
        
        # Генерируем новые ссылки
        token_links = self.generate_token_links(remaining, wallet_address, user_id)
        
        if token_links:
            # Сохраняем новый список токенов для проверки
            target_board_ids = self.extract_board_ids_from_links(token_links)
            
            # Сохраняем в контексте пользователя для последующей проверки
            # Сохраняем данные в контексте пользователя
            if user_id not in self.users_data:
                self.users_data[user_id] = UserData([], [])
            
            # Сохраняем цели для токенов в данных пользователя
            user_data = self.users_data[user_id]
            if not hasattr(user_data, 'token_targets'):
                user_data.token_targets = {}
            if not hasattr(user_data, 'token_user_wallet'):
                user_data.token_user_wallet = {}
            
            user_data.token_targets[wallet_index] = target_board_ids
            user_data.token_user_wallet[wallet_index] = wallet_address
            self.save_users_data()
            
            links_text = "\n".join([f"• {link}" for link in token_links])
            message = f"""🔄 Обновленные ссылки для покупки токенов

Купите токены по этим ссылкам для получения {remaining} холдеров:

{links_text}

После покупки нажмите "Готово"."""
            
            keyboard = [
                [InlineKeyboardButton("🔄 Обновить", callback_data=f"token_refresh_{wallet_index}")],
                [InlineKeyboardButton("✅ Готово", callback_data=f"token_done_{wallet_index}")],
                [InlineKeyboardButton("❌ Отмена", callback_data="token_holders")]
            ]
        else:
            message = f"""❌ Недостаточно токенов

В системе недостаточно токенов для генерации ссылок."""
            
            keyboard = [
                [InlineKeyboardButton("← Назад", callback_data="token_holders")]
            ]
        
        await query.edit_message_text(
            text=message,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )
    
    async def handle_token_done(self, query, wallet_index: int):
        """Обрабатывает завершение покупки токенов"""
        user_id = query.from_user.id
        user_data = self.users_data.get(user_id, UserData([], []))
        
        if wallet_index >= len(user_data.wallet_addresses):
            await query.edit_message_text("❌ Ошибка: неверный индекс кошелька")
            return
        
        wallet_address = user_data.wallet_addresses[wallet_index]
        
        # Проверяем ачивку снова
        achievement = self.api_client.get_token_holders_achievement(wallet_address)
        
        if not achievement:
            message = f"""❌ Ошибка проверки ачивки

Не удалось проверить выполнение ачивки.
Попробуйте позже."""
            
            keyboard = [
                [InlineKeyboardButton("← Назад", callback_data="token_holders")]
            ]
        elif achievement['completed']:
            # Ачивка выполнена - проверяем, есть ли адрес в общем списке
            is_in_global_list = wallet_address in self.data_manager.read_wallets()
            
            if not is_in_global_list:
                self.add_wallet_to_global_list(wallet_address)
                message = f"""🎉 Поздравляем!

Ачивка "They Lovin' It" успешно выполнена для адреса:
{wallet_address}

Ваш адрес добавлен в общий список для помощи другим пользователям.
Выполнено заданий: {user_data.completed_token_tasks}"""
            else:
                message = f"""🎉 Поздравляем!

Ачивка "They Lovin' It" успешно выполнена для адреса:
{wallet_address}

Выполнено заданий: {user_data.completed_token_tasks}"""
            
            user_data.completed_token_tasks += 1
            self.save_users_data()
            
            keyboard = [
                [InlineKeyboardButton("← Главное меню", callback_data="back_to_main")]
            ]
        else:
            # Ачивка еще не выполнена - проверяем конкретные покупки
            await self.check_specific_token_purchases(query, wallet_index, wallet_address)
    
    async def handle_token_continue(self, query, wallet_index: int):
        """Обрабатывает продолжение помощи другим пользователям с токенами"""
        # Генерируем случайные ссылки на токены для помощи другим
        available_tokens = self.data_manager.get_random_tokens(5)
        
        if available_tokens:
            links_text = "\n".join([f"• <a href=\"https://phi.box/board/{board_id}\">{board_id}</a>" for board_id in available_tokens])
            message = f"""🤝 Помощь другим пользователям

Купите токены по этим ссылкам, чтобы помочь другим получить ачивку:

{links_text}

Спасибо за помощь! 🙏"""
            
            keyboard = [
                [InlineKeyboardButton("← Главное меню", callback_data="back_to_main")]
            ]
        else:
            message = f"""❌ Нет доступных токенов

В системе пока нет других токенов для помощи."""
            
            keyboard = [
                [InlineKeyboardButton("← Главное меню", callback_data="back_to_main")]
            ]
        
        await query.edit_message_text(
            text=message,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )
    
    async def check_specific_token_purchases(self, query, wallet_index: int, user_wallet: str):
        """Проверяет конкретные покупки токенов пользователем"""
        user_id = query.from_user.id
        
        # Получаем сохраненные данные из контекста
        user_data = self.users_data.get(user_id, UserData([], []))
        target_board_ids = getattr(user_data, 'token_targets', {}).get(wallet_index, [])
        
        if not target_board_ids:
            # Если нет сохраненных данных, проверяем ачивку
            achievement = self.api_client.get_token_holders_achievement(user_wallet)
            if not achievement:
                message = f"""❌ Ошибка проверки ачивки

Не удалось проверить выполнение ачивки.
Попробуйте позже."""
                
                keyboard = [
                    [InlineKeyboardButton("← Назад", callback_data="token_holders")]
                ]
            else:
                remaining = achievement['remaining']
                message = f"""⏳ Ачивка еще не выполнена

Осталось получить: {remaining} холдеров

Возможно, нужно подождать некоторое время для обновления данных.
Попробуйте проверить еще раз через 30 секунд."""
                
                keyboard = [
                    [InlineKeyboardButton("🔄 Проверить снова", callback_data=f"token_done_{wallet_index}")],
                    [InlineKeyboardButton("← Назад", callback_data="token_holders")]
                ]
        else:
            # Проверяем конкретные покупки через API
            await query.edit_message_text("🔍 Проверяем покупки токенов...")
            
            # Проверяем каждый токен
            purchase_results = self.api_client.check_multiple_token_purchases(target_board_ids, user_wallet)
            
            # Разделяем на купленные и некупленные
            purchased = [board_id for board_id, is_purchased in purchase_results.items() if is_purchased]
            not_purchased = [board_id for board_id, is_purchased in purchase_results.items() if not is_purchased]
            
            # Если пользователь не купил ни одного токена, добавляем в очередь фоновой проверки
            if not purchased and not_purchased:
                if self.background_checker:
                    self.background_checker.add_pending_check(
                        user_id=user_id,
                        wallet_index=wallet_index,
                        wallet_address=user_wallet,
                        check_type="tokens",
                        target_board_ids=target_board_ids
                    )
                
                message = f"""⏳ Данные еще не обновились

API показывает, что вы пока не купили ни одного из {len(target_board_ids)} токенов.

Если вы уверены, что купили все токены, можете закрыть это меню.
Мы будем проверять каждые 5 минут и уведомим вас, когда данные обновятся.

Максимум проверок: 30 (2.5 часа)"""
                
                keyboard = [
                    [InlineKeyboardButton("🔄 Проверить снова", callback_data=f"token_done_{wallet_index}")],
                    [InlineKeyboardButton("← Назад", callback_data="token_holders")]
                ]
                
                await query.edit_message_text(
                    text=message,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    disable_web_page_preview=True
                )
                return
            
            if not not_purchased:
                # Все покупки выполнены
                user_data = self.users_data.get(user_id, UserData([], []))
                user_data.completed_token_tasks += len(purchased)
                self.save_users_data()
                
                # Проверяем ачивку еще раз
                achievement = self.api_client.get_token_holders_achievement(user_wallet)
                if achievement and achievement['completed']:
                    # Проверяем, есть ли адрес в общем списке
                    is_in_global_list = user_wallet in self.data_manager.read_wallets()
                    if not is_in_global_list:
                        self.add_wallet_to_global_list(user_wallet)
                        message = f"""🎉 Поздравляем!

Ачивка "They Lovin' It" успешно выполнена для адреса:
{user_wallet}

Ваш адрес добавлен в общий список для помощи другим пользователям.
Выполнено заданий: {user_data.completed_token_tasks}"""
                    else:
                        message = f"""🎉 Поздравляем!

Ачивка "They Lovin' It" успешно выполнена для адреса:
{user_wallet}

Выполнено заданий: {user_data.completed_token_tasks}"""
                    
                    keyboard = [
                        [InlineKeyboardButton("← Главное меню", callback_data="back_to_main")]
                    ]
                else:
                    message = f"""✅ Покупки выполнены!

Вы успешно купили все {len(purchased)} токенов.
Выполнено заданий: {user_data.completed_token_tasks}

Ачивка может обновиться через некоторое время."""
                    
                    keyboard = [
                        [InlineKeyboardButton("← Главное меню", callback_data="back_to_main")]
                    ]
            else:
                # Есть некупленные токены
                not_purchased_links = [f'<a href="https://phi.box/board/{board_id}?referrer={user_wallet}">{board_id}</a>' for board_id in not_purchased]
                links_text = "\n".join([f"• {link}" for link in not_purchased_links])
                
                message = f"""⚠️ Не все покупки выполнены

Вы купили {len(purchased)} из {len(target_board_ids)} токенов.

Осталось купить:
{links_text}

После покупки нажмите "Готово" еще раз."""
                
                keyboard = [
                    [InlineKeyboardButton("✅ Готово", callback_data=f"token_done_{wallet_index}")],
                    [InlineKeyboardButton("← Назад", callback_data="token_holders")]
                ]
        
        await query.edit_message_text(
            text=message,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )
    
    async def check_specific_followers(self, query, wallet_index: int, user_wallet: str):
        """Проверяет конкретные подписки пользователя"""
        user_id = query.from_user.id
        
        # Получаем сохраненные данные из контекста
        user_data = self.users_data.get(user_id, UserData([], []))
        target_addresses = getattr(user_data, 'followers_targets', {}).get(wallet_index, [])
        
        if not target_addresses:
            # Если нет сохраненных данных, проверяем ачивку
            achievement = self.api_client.get_trendsetter_achievement(user_wallet)
            if not achievement:
                message = f"""❌ Ошибка проверки ачивки

Не удалось проверить выполнение ачивки.
Попробуйте позже."""
                
                keyboard = [
                    [InlineKeyboardButton("← Назад", callback_data="followers")]
                ]
            else:
                remaining = achievement['remaining']
                message = f"""⏳ Ачивка еще не выполнена

Осталось получить: {remaining} фолловеров

Возможно, нужно подождать некоторое время для обновления данных.
Попробуйте проверить еще раз через 30 секунд."""
                
                keyboard = [
                    [InlineKeyboardButton("🔄 Проверить снова", callback_data=f"followers_done_{wallet_index}")],
                    [InlineKeyboardButton("← Назад", callback_data="followers")]
                ]
        else:
            # Проверяем конкретные подписки через API
            await query.edit_message_text("🔍 Проверяем подписки...")
            
            # Проверяем каждый адрес
            follow_results = self.api_client.check_multiple_followers(target_addresses, user_wallet)
            
            # Разделяем на подписанные и неподписанные
            followed = [addr for addr, is_following in follow_results.items() if is_following]
            not_followed = [addr for addr, is_following in follow_results.items() if not is_following]
            
            # Если пользователь не подписался ни на кого, добавляем в очередь фоновой проверки
            if not followed and not_followed:
                if self.background_checker:
                    self.background_checker.add_pending_check(
                        user_id=user_id,
                        wallet_index=wallet_index,
                        wallet_address=user_wallet,
                        check_type="followers",
                        target_addresses=target_addresses
                    )
                
                message = f"""⏳ Данные еще не обновились

API показывает, что вы пока не подписались ни на кого из {len(target_addresses)} профилей.

Если вы уверены, что подписались на всех, можете закрыть это меню.
Мы будем проверять каждые 5 минут и уведомим вас, когда данные обновятся.

Максимум проверок: 30 (2.5 часа)"""
                
                keyboard = [
                    [InlineKeyboardButton("🔄 Проверить снова", callback_data=f"followers_done_{wallet_index}")],
                    [InlineKeyboardButton("← Назад", callback_data="followers")]
                ]
                
                await query.edit_message_text(
                    text=message,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    disable_web_page_preview=True
                )
                return
            
            if not not_followed:
                # Все подписки выполнены
                user_data = self.users_data.get(user_id, UserData([], []))
                user_data.completed_followers_tasks += len(followed)
                self.save_users_data()
                
                # Проверяем ачивку еще раз
                achievement = self.api_client.get_trendsetter_achievement(user_wallet)
                if achievement and achievement['completed']:
                    # Проверяем, есть ли адрес в общем списке
                    is_in_global_list = user_wallet in self.data_manager.read_wallets()
                    if not is_in_global_list:
                        self.add_wallet_to_global_list(user_wallet)
                        message = f"""🎉 Поздравляем!

Ачивка "Trendsetter" успешно выполнена для адреса:
{user_wallet}

Ваш адрес добавлен в общий список для помощи другим пользователям.
Выполнено заданий: {user_data.completed_followers_tasks}"""
                    else:
                        message = f"""🎉 Поздравляем!

Ачивка "Trendsetter" успешно выполнена для адреса:
{user_wallet}

Выполнено заданий: {user_data.completed_followers_tasks}"""
                    
                    keyboard = [
                        [InlineKeyboardButton("← Главное меню", callback_data="back_to_main")]
                    ]
                else:
                    message = f"""✅ Подписки выполнены!

Вы успешно подписались на все {len(followed)} профилей.
Выполнено заданий: {user_data.completed_followers_tasks}

Ачивка может обновиться через некоторое время."""
                    
                    keyboard = [
                        [InlineKeyboardButton("← Главное меню", callback_data="back_to_main")]
                    ]
            else:
                # Есть неподписанные адреса - предлагаем фоновую проверку
                not_followed_links = [f'<a href="https://phi.box/profile/{addr}">{addr}</a>' for addr in not_followed]
                links_text = "\n".join([f"• {link}" for link in not_followed_links])
                
                message = f"""⚠️ Не все подписки выполнены

Вы подписались на {len(followed)} из {len(target_addresses)} профилей.

Осталось подписаться на:
{links_text}

Если вы уверены, что подписались на всех, можете закрыть это меню. 
Мы будем проверять каждые 5 минут и уведомим вас, когда данные обновятся."""
                
                keyboard = [
                    [InlineKeyboardButton("✅ Готово", callback_data=f"followers_done_{wallet_index}")],
                    [InlineKeyboardButton("🔄 Проверить снова", callback_data=f"followers_done_{wallet_index}")],
                    [InlineKeyboardButton("← Назад", callback_data="followers")]
                ]
        
        await query.edit_message_text(
            text=message,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )
    
    def add_wallet_to_global_list(self, wallet_address: str):
        """Добавляет адрес в общий список кошельков"""
        try:
            # Читаем текущий список
            current_wallets = self.data_manager.read_wallets()
            
            # Добавляем адрес если его нет
            if wallet_address not in current_wallets:
                current_wallets.append(wallet_address)
                self.data_manager.write_wallets(current_wallets)
                print(f"Адрес {wallet_address} добавлен в общий список кошельков")
            
        except Exception as e:
            print(f"Ошибка добавления адреса в общий список: {e}")
    
    def extract_addresses_from_links(self, links: List[str]) -> List[str]:
        """Извлекает адреса из HTML-ссылок на профили"""
        addresses = []
        for link in links:
            if "phi.box/profile/" in link:
                # Извлекаем адрес из HTML-ссылки вида <a href="https://phi.box/profile/{address}">{address}</a>
                address = link.split("phi.box/profile/")[-1].split('"')[0]
                if self.is_valid_ethereum_address(address):
                    addresses.append(address)
        return addresses
    
    def extract_board_ids_from_links(self, links: List[str]) -> List[str]:
        """Извлекает ID бордов из HTML-ссылок на токены"""
        board_ids = []
        for link in links:
            if "phi.box/board/" in link:
                # Извлекаем ID борда из HTML-ссылки вида <a href="https://phi.box/board/{board_id}?referrer={wallet}">{board_id}</a>
                board_part = link.split("phi.box/board/")[-1].split('"')[0]
                board_id = board_part.split("?")[0]  # Убираем параметры после ?
                if self.extract_board_id(board_id):
                    board_ids.append(board_id)
        return board_ids
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик текстовых сообщений"""
        user_id = update.effective_user.id
        text = update.message.text.strip()
        
        # Определяем, в каком режиме находится пользователь
        # Это упрощенная версия - в реальном боте нужно использовать состояния
        if "добавление адресов" in context.user_data.get('mode', ''):
            await self.process_wallet_addresses(update, context, text)
        elif "добавление бордов" in context.user_data.get('mode', ''):
            await self.process_board_addresses(update, context, text)
    
    async def process_wallet_addresses(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
        """Обрабатывает добавление адресов кошельков"""
        user_id = update.effective_user.id
        addresses = [addr.strip() for addr in text.split('\n') if addr.strip()]
        
        valid_addresses = []
        invalid_addresses = []
        
        for address in addresses:
            if self.is_valid_ethereum_address(address):
                valid_addresses.append(address)
            else:
                invalid_addresses.append(address)
        
        if valid_addresses:
            if user_id not in self.users_data:
                self.users_data[user_id] = UserData([], [])
            
            # Добавляем только новые адреса
            for address in valid_addresses:
                if address not in self.users_data[user_id].wallet_addresses:
                    self.users_data[user_id].wallet_addresses.append(address)
            
            self.save_users_data()
            
            # Обновляем общий файл кошельков
            self.update_wallets_file()
        
        message = f"""✅ Обработка завершена

Валидных адресов: {len(valid_addresses)}
Невалидных адресов: {len(invalid_addresses)}"""
        
        if invalid_addresses:
            message += f"\n\n❌ Невалидные адреса:\n" + "\n".join(invalid_addresses)
        
        keyboard = [
            [InlineKeyboardButton("← Назад к данным", callback_data="my_data")]
        ]
        
        await update.message.reply_text(message, reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data['mode'] = ''
    
    async def process_board_addresses(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
        """Обрабатывает добавление бордов"""
        user_id = update.effective_user.id
        boards = [board.strip() for board in text.split('\n') if board.strip()]
        
        valid_boards = []
        invalid_boards = []
        
        for board in boards:
            board_id = self.extract_board_id(board)
            if board_id:
                valid_boards.append(board_id)
            else:
                invalid_boards.append(board)
        
        if valid_boards:
            if user_id not in self.users_data:
                self.users_data[user_id] = UserData([], [])
            
            # Добавляем только новые борды
            for board_id in valid_boards:
                if board_id not in self.users_data[user_id].board_addresses:
                    self.users_data[user_id].board_addresses.append(board_id)
            
            self.save_users_data()
            
            # Обновляем общие файлы
            self.update_boards_file()
            self.update_tokens_file()
        
        message = f"""✅ Обработка завершена

Валидных бордов: {len(valid_boards)}
Невалидных бордов: {len(invalid_boards)}"""
        
        if invalid_boards:
            message += f"\n\n❌ Невалидные борды:\n" + "\n".join(invalid_boards)
        
        keyboard = [
            [InlineKeyboardButton("← Назад к данным", callback_data="my_data")]
        ]
        
        await update.message.reply_text(message, reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data['mode'] = ''
    
    def update_wallets_file(self):
        """Обновляет общий файл кошельков"""
        all_wallets = set()
        for user_data in self.users_data.values():
            all_wallets.update(user_data.wallet_addresses)
        
        self.data_manager.write_wallets(list(all_wallets))
    
    def update_boards_file(self):
        """Обновляет общий файл бордов"""
        all_boards = set()
        for user_data in self.users_data.values():
            all_boards.update(user_data.board_addresses)
        
        self.data_manager.write_boards(list(all_boards))
    
    def update_tokens_file(self):
        """Обновляет общий файл токенов"""
        all_tokens = set()
        for user_data in self.users_data.values():
            for board in user_data.board_addresses:
                all_tokens.add(board)
        
        self.data_manager.write_tokens(list(all_tokens))
    
    def run(self):
        """Запускает бота"""
        if not self.bot_token:
            print("Ошибка: BOT_TOKEN не найден в переменных окружения")
            return
        
        # Создаем приложение
        self.application = Application.builder().token(self.bot_token).build()
        
        # Инициализируем систему фоновой проверки
        self.background_checker = BackgroundChecker(self)
        
        # Добавляем обработчики
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CallbackQueryHandler(self.button_callback))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        print("Бот запущен...")
        
        # Запускаем фоновую проверку
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Запускаем фоновую проверку в отдельной задаче
        background_task = loop.create_task(self.background_checker.start_background_checking())
        
        try:
            # Запускаем бота
            self.application.run_polling()
        except KeyboardInterrupt:
            print("\nОстановка бота...")
            self.background_checker.stop_background_checking()
            background_task.cancel()
            loop.close()

if __name__ == "__main__":
    bot = PHIBot()
    bot.run()
