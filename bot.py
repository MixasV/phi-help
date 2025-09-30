import os
import json
import random
import re
import asyncio
from datetime import datetime, timedelta
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
    sent_achievement_notifications: Dict[str, List[str]] = None  # Отправленные уведомления {achievement_name: [wallet_addresses]}
    language: str = 'ru'  # Язык пользователя (ru/en)
    last_wallet_count: int = 0  # Количество кошельков при последнем обновлении кэша
    followers_progress: Dict[str, Dict] = None  # Прогресс по фолловерам по кошельку {wallet: {count, counted_addresses}}
    token_progress: Dict[str, Dict] = None      # Прогресс по токенам по кошельку {wallet: {count, counted_board_ids}}
    
    def __post_init__(self):
        if self.sent_achievement_notifications is None:
            self.sent_achievement_notifications = {}
        if self.followers_progress is None:
            self.followers_progress = {}
        if self.token_progress is None:
            self.token_progress = {}

@dataclass
class CachedStats:
    """Кэшированная статистика пользователя"""
    wallet_address: str
    user_stats: Dict
    total_achievements: int
    total_achievements_possible: int
    social_butterfly: Dict
    trendsetter: Dict
    they_lovin_it: Dict
    cached_at: datetime
    formatted_message: str
    
    def is_expired(self, max_age_minutes: int = 5) -> bool:
        """Проверяет, истек ли кэш"""
        return datetime.now() - self.cached_at > timedelta(minutes=max_age_minutes)

class StatsCache:
    """Менеджер кэша статистики"""
    
    def __init__(self):
        self.cache: Dict[str, CachedStats] = {}
        self.loading_queue: Dict[str, asyncio.Task] = {}  # Очередь загрузки
        self.last_auto_refresh = datetime.now()
        self.auto_refresh_interval = 20  # минут
    
    def get_cached_stats(self, wallet_address: str, compact: bool = False, max_age_minutes: int = 5) -> Optional[CachedStats]:
        """Получает кэшированную статистику"""
        cache_key = f"{wallet_address}_{compact}"
        if cache_key in self.cache:
            cached_stats = self.cache[cache_key]
            if not cached_stats.is_expired(max_age_minutes):
                return cached_stats
            else:
                # Удаляем устаревший кэш
                del self.cache[cache_key]
        return None
    
    def set_cached_stats(self, wallet_address: str, compact: bool, stats_data: Dict, formatted_message: str):
        """Сохраняет статистику в кэш"""
        cache_key = f"{wallet_address}_{compact}"
        self.cache[cache_key] = CachedStats(
            wallet_address=wallet_address,
            user_stats=stats_data.get('user_stats'),
            total_achievements=stats_data.get('total_achievements', 0),
            total_achievements_possible=stats_data.get('total_achievements_possible', 0),
            social_butterfly=stats_data.get('social_butterfly'),
            trendsetter=stats_data.get('trendsetter'),
            they_lovin_it=stats_data.get('they_lovin_it'),
            cached_at=datetime.now(),
            formatted_message=formatted_message
        )
    
    def is_loading(self, wallet_address: str, compact: bool = False) -> bool:
        """Проверяет, загружается ли статистика для адреса"""
        cache_key = f"{wallet_address}_{compact}"
        return cache_key in self.loading_queue
    
    def add_loading_task(self, wallet_address: str, compact: bool, task: asyncio.Task):
        """Добавляет задачу загрузки в очередь"""
        cache_key = f"{wallet_address}_{compact}"
        self.loading_queue[cache_key] = task
    
    def remove_loading_task(self, wallet_address: str, compact: bool = False):
        """Удаляет задачу загрузки из очереди"""
        cache_key = f"{wallet_address}_{compact}"
        if cache_key in self.loading_queue:
            del self.loading_queue[cache_key]
    
    def should_auto_refresh(self) -> bool:
        """Проверяет, нужно ли выполнить автоматическое обновление"""
        return datetime.now() - self.last_auto_refresh > timedelta(minutes=self.auto_refresh_interval)
    
    def mark_auto_refresh_done(self):
        """Отмечает, что автоматическое обновление выполнено"""
        self.last_auto_refresh = datetime.now()
    
    def clear_expired_cache(self):
        """Очищает устаревший кэш"""
        expired_keys = []
        for cache_key, cached_stats in self.cache.items():
            if cached_stats.is_expired(20):  # 20 минут для автоочистки
                expired_keys.append(cache_key)
        
        for key in expired_keys:
            del self.cache[key]
    
    def clear_user_cache(self, wallet_addresses: List[str]):
        """Очищает кэш для конкретных адресов кошельков"""
        keys_to_remove = []
        for cache_key in self.cache.keys():
            for wallet_address in wallet_addresses:
                if cache_key.startswith(f"{wallet_address}_"):
                    keys_to_remove.append(cache_key)
                    break
        
        for key in keys_to_remove:
            del self.cache[key]
        
        print(f"🧹 Очищен кэш для {len(keys_to_remove)} записей")

def group_buttons_in_rows(buttons, buttons_per_row=3):
    """Группирует кнопки по указанному количеству в ряд"""
    grouped = []
    for i in range(0, len(buttons), buttons_per_row):
        row = buttons[i:i + buttons_per_row]
        grouped.append(row)
    return grouped

class PHIBot:
    def __init__(self):
        self.bot_token = os.getenv('BOT_TOKEN')
        self.wallets_file = os.getenv('WALLETS_FILE', 'wallets.txt')
        self.boards_file = os.getenv('BOARDS_FILE', 'boards.txt')
        self.tokens_file = os.getenv('TOKENS_FILE', 'tokens.txt')
        self.users_data_file = os.getenv('USERS_DATA_FILE', 'users_data.json')
        self.user_stats_file = os.getenv('USER_STATS_FILE', 'user_stats.json')
        self.followers_threshold = int(os.getenv('FOLLOWERS_THRESHOLD', '10'))
        self.token_holders_threshold = int(os.getenv('TOKEN_HOLDERS_THRESHOLD', '10'))
        
        # Инициализируем API клиент и менеджер данных
        self.api_client = PHIAPI()
        self.data_manager = DataManager(self.wallets_file, self.boards_file, self.tokens_file)
        
        # Инициализируем систему фоновой проверки
        self.background_checker = None
        
        # Инициализируем кэш статистики
        self.stats_cache = StatsCache()
        # Файловое хранилище статистики для главного меню
        self.user_stats_store: Dict[str, Dict] = self.load_user_stats_store()
        # Последнее сообщение главного меню для каждого пользователя
        self.user_main_menu_message_id: Dict[int, int] = {}
        # Таски фонового обновления кэша по пользователям (для дедупликации)
        self.user_cache_update_tasks: Dict[int, asyncio.Task] = {}
        
        # Загружаем данные пользователей
        self.users_data = self.load_users_data()
        
        # Создаем файлы данных если их нет
        self.ensure_data_files()
        
        # Инициализируем переводы
        self.translations = self.init_translations()
    
    def init_translations(self) -> Dict[str, Dict[str, str]]:
        """Инициализирует словари переводов"""
        return {
            'ru': {
                'welcome': '🤖 Добро пожаловать в PHI Helper Bot!\n\nВы можете добавить свои адреса кошельков для выполнения ачивок, а также свои борды.\n\n📊 Ваша статистика:\n• Адресов кошельков: {wallet_count}\n• Бордов: {board_count}\n\nВыберите действие:',
                'my_data': 'Мои данные',
                'followers': 'Фолловеры',
                'token_holders': 'Token holders',
                'back': '← Назад',
                'main_menu': '← Главное меню',
                'add_wallets': 'Добавить адреса',
                'add_boards': 'Добавить борды',
                'cancel': 'Отмена',
                'done': '✅ Готово',
                'refresh': '🔄 Обновить',
                'continue': 'Продолжить',
                'language_selection': '🌐 Выберите язык / Choose language:',
                'russian': '🇷🇺 Русский',
                'english': '🇺🇸 English',
                'language_changed': '✅ Язык изменен на: {language}',
                'my_data_title': '📋 Мои данные\n\nАдресов кошельков: {wallet_count}\nБордов: {board_count}\n\nВыберите действие:',
                'add_wallets_title': '💳 Добавление адресов кошельков\n\nОтправьте адреса кошельков в формате EVM (начинающиеся с 0x).\nМожно отправить несколько адресов, каждый с новой строки.\n\nПример:\n0xC7f9154a72524097B1323961F584f7047b875271\n0x1234567890123456789012345678901234567890\n\nОтправьте адреса или нажмите "Отмена":',
                'add_boards_title': '🎯 Добавление бордов\n\nОтправьте ссылки на борды или их ID.\nМожно отправить несколько бордов, каждый с новой строки.\n\nПримеры:\nhttps://phi.box/board/5ced1c01-dca1-4021-8a9d-870955020444\n5ced1c01-dca1-4021-8a9d-870955020444\n\nОтправьте борды или нажмите "Отмена":',
                'followers_title': '👥 Фолловеры\n\nУ вас пока нет добавленных адресов кошельков.\nСначала добавьте адреса, чтобы получить фолловеров.',
                'followers_select': '👥 Фолловеры\n\nВыберите адрес кошелька для получения фолловеров:',
                'token_holders_title': '🪙 Token holders\n\nУ вас пока нет добавленных адресов кошельков или бордов.\nСначала добавьте их, чтобы получить холдеров токенов.',
                'token_holders_select': '🪙 Token holders\n\nВыберите адрес кошелька для получения холдеров токенов:',
                'processing_complete': '✅ Обработка завершена\n\nВалидных адресов: {valid_count}\nНевалидных адресов: {invalid_count}',
                'processing_complete_boards': '✅ Обработка завершена\n\nВалидных бордов: {valid_count}\nНевалидных бордов: {invalid_count}',
                'invalid_addresses': '❌ Невалидные адреса:\n{addresses}',
                'invalid_boards': '❌ Невалидные борды:\n{boards}',
                'back_to_data': '← Назад к данным',
                'add_wallets_btn': 'Добавить адреса',
                'add_boards_btn': 'Добавить борды',
                'back_to_main_btn': '← Назад',
                'error_wallet_index': '❌ Ошибка: неверный индекс кошелька',
                'error_achievement_check': '❌ Ошибка проверки ачивки\n\nНе удалось получить информацию об ачивке для адреса:\n{wallet_address}\n\nПопробуйте позже.',
                'error_achievement_check_general': '❌ Ошибка проверки ачивки\n\nНе удалось проверить выполнение ачивки.\nПопробуйте позже.',
                'achievement_completed': '✅ Ачивка уже выполнена!\n\n🎉 Поздравляем! Ачивка "{achievement_name}" уже выполнена для адреса:\n{wallet_address}\n\nХотите продолжить и помочь другим пользователям?',
                'achievement_completed_added': '✅ Ачивка уже выполнена!\n\n🎉 Поздравляем! Ачивка "{achievement_name}" уже выполнена для адреса:\n{wallet_address}\n\nВаш адрес добавлен в общий список для помощи другим пользователям.\nХотите продолжить помогать?',
                'trendsetter_status': '📊 Статус ачивки "Trendsetter"\n\nАдрес: {wallet_address}\nПрогресс: {progress}/{required}\nОсталось получить: {remaining} фолловеров\nВыполнено заданий: {completed_tasks}\n\nГенерируем ссылки для подписки...',
                'token_holders_status': '📊 Статус ачивки "They Lovin\' It"\n\nАдрес: {wallet_address}\nПрогресс: {progress}/{required}\nОсталось получить: {remaining} холдеров\nВыполнено заданий: {completed_tasks}\n\nГенерируем ссылки для покупки токенов...',
                'followers_available': '👥 Фолловеры для адреса {wallet_address_short}...\n\n📋 Доступно адресов: {available_count} из {needed_count} необходимых\n\nПодпишитесь на следующие профили:\n{links}\n\nПосле подписки нажмите "Готово".',
                'tokens_available': '🪙 Token holders для адреса {wallet_address_short}...\n\n📋 Доступно токенов: {available_count} из {needed_count} необходимых\n\nКупите следующие токены:\n{links}\n\nПосле покупки нажмите "Готово".',
                'insufficient_addresses': '\n\n⏳ Недостаточно адресов для полного выполнения задания.\nМы уведомим вас, когда появятся новые адреса.',
                'insufficient_tokens': '\n\n⏳ Недостаточно токенов для полного выполнения задания.\nМы уведомим вас, когда появятся новые токены.',
                'achievement_success': '🎉 Поздравляем!\n\nАчивка "{achievement_name}" успешно выполнена для адреса:\n{wallet_address}\n\nВаш адрес добавлен в общий список для помощи другим пользователям.\nВыполнено заданий: {completed_tasks}',
                'achievement_success_simple': '🎉 Поздравляем!\n\nАчивка "{achievement_name}" успешно выполнена для адреса:\n{wallet_address}\n\nВыполнено заданий: {completed_tasks}',
                'help_others_followers': '🤝 Помощь другим пользователям\n\nПодпишитесь на эти профили, чтобы помочь другим получить ачивку:\n\n{links}\n\nСпасибо за помощь! 🙏',
                'help_others_tokens': '🤝 Помощь другим пользователям\n\nКупите токены по этим ссылкам, чтобы помочь другим получить ачивку:\n\n{links}\n\nСпасибо за помощь! 🙏',
                'no_available_addresses': '❌ Нет доступных адресов\n\nВ системе пока нет других адресов для помощи.',
                'no_available_tokens': '❌ Нет доступных токенов\n\nВ системе пока нет других токенов для помощи.',
                'achievement_not_completed': '⏳ Ачивка еще не выполнена\n\nОсталось получить: {remaining} {type}\n\nВозможно, нужно подождать некоторое время для обновления данных.\nПопробуйте проверить еще раз через 30 секунд.',
                'checking_purchases': '🔍 Проверяем покупки токенов...',
                'checking_followers': '🔍 Проверяем подписки...',
                'data_not_updated': '⏳ Данные еще не обновились\n\nAPI показывает, что вы пока не купили ни одного из {count} токенов.\n\nЕсли вы уверены, что купили все токены, можете закрыть это меню.\nМы будем проверять каждые 5 минут и уведомим вас, когда данные обновятся.\n\nМаксимум проверок: 30 (2.5 часа)',
                'data_not_updated_followers': '⏳ Данные еще не обновились\n\nAPI показывает, что вы пока не подписались ни на кого из {count} профилей.\n\nЕсли вы уверены, что подписались на всех, можете закрыть это меню.\nМы будем проверять каждые 5 минут и уведомим вас, когда данные обновятся.\n\nМаксимум проверок: 30 (2.5 часа)',
                'all_purchases_complete': '✅ Покупки выполнены!\n\nВы успешно купили все {count} токенов.\nВыполнено заданий: {completed_tasks}\n\nАчивка может обновиться через некоторое время.',
                'all_followers_complete': '✅ Подписки выполнены!\n\nВы успешно подписались на все {count} профилей.\nВыполнено заданий: {completed_tasks}\n\nАчивка может обновиться через некоторое время.',
                'not_all_purchases': '⚠️ Не все покупки выполнены\n\nВы купили {purchased} из {total} токенов.\n\nОсталось купить:\n{links}\n\nПосле покупки нажмите "Готово" еще раз.',
                'not_all_followers': '⚠️ Не все подписки выполнены\n\nВы подписались на {followed} из {total} профилей.\n\nОсталось подписаться на:\n{links}\n\nЕсли вы уверены, что подписались на всех, можете закрыть это меню.\nМы будем проверять каждые 5 минут и уведомим вас, когда данные обновятся.',
                'insufficient_tokens_system': '❌ Недостаточно токенов\n\nВ системе недостаточно токенов для генерации ссылок.',
                'insufficient_addresses_system': '❌ Недостаточно адресов\n\nВ системе недостаточно адресов для генерации ссылок.',
                'refresh_links_tokens': '🔄 Обновленные ссылки для покупки токенов\n\nКупите токены по этим ссылкам для получения {remaining} холдеров:\n\n{links}\n\nПосле покупки нажмите "Готово".',
                'refresh_links_followers': '🔄 Обновленные ссылки для подписки\n\nПодпишитесь на эти профили для получения {remaining} фолловеров:\n\n{links}\n\nПосле подписки нажмите "Готово".',
                'followers_type': 'фолловеров',
                'holders_type': 'холдеров',
                'user_stats_title': '📊 Статистика пользователя\n\n👤 Адрес: {wallet_address}\n👥 Подписчики: {followers_count}\n📝 Подписки: {following_count}\n🏆 Выполнено ачивок: {total_achievements}\n\n🎯 Прогресс по ачивкам:\n{achievements_progress}',
                'achievement_completed_icon': '✅',
                'achievement_in_progress_icon': '⏳',
                'achievement_progress_line': '{icon} {name}: {progress}/{required} ({remaining} осталось)',
                'achievement_completed_line': '{icon} {name}: Выполнено!',
                'social_butterfly': 'Social Butterfly',
                'trendsetter': 'Trendsetter',
                'they_lovin_it': 'They Lovin\' It',
                'user_stats_compact': '📊 Статистика пользователя\n\n👤 Адрес: {wallet_address}\n👥 {followers_count}📝 {following_count} 🏆 {total_achievements}/{total_achievements_possible}\n\n{achievements_progress}',
                'updating_data': '🔄 Обновляем данные...',
                'wallet_label': '📊 Кошелек {index}',
                'wallet_stats_label': '📊 Статистика кошелька {index}',
                'more_wallets': '📊 ... и еще {count} кошельков'
            },
            'en': {
                'welcome': '🤖 Welcome to PHI Helper Bot!\n\nYou can add your wallet addresses to complete achievements, as well as your boards.\n\n📊 Your statistics:\n• Wallet addresses: {wallet_count}\n• Boards: {board_count}\n\nChoose an action:',
                'my_data': 'My Data',
                'followers': 'Followers',
                'token_holders': 'Token holders',
                'back': '← Back',
                'main_menu': '← Main Menu',
                'add_wallets': 'Add Addresses',
                'add_boards': 'Add Boards',
                'cancel': 'Cancel',
                'done': '✅ Done',
                'refresh': '🔄 Refresh',
                'continue': 'Continue',
                'language_selection': '🌐 Choose language / Выберите язык:',
                'russian': '🇷🇺 Русский',
                'english': '🇺🇸 English',
                'language_changed': '✅ Language changed to: {language}',
                'my_data_title': '📋 My Data\n\nWallet addresses: {wallet_count}\nBoards: {board_count}\n\nChoose an action:',
                'add_wallets_title': '💳 Adding Wallet Addresses\n\nSend wallet addresses in EVM format (starting with 0x).\nYou can send multiple addresses, each on a new line.\n\nExample:\n0xC7f9154a72524097B1323961F584f7047b875271\n0x1234567890123456789012345678901234567890\n\nSend addresses or press "Cancel":',
                'add_boards_title': '🎯 Adding Boards\n\nSend board links or their IDs.\nYou can send multiple boards, each on a new line.\n\nExamples:\nhttps://phi.box/board/5ced1c01-dca1-4021-8a9d-870955020444\n5ced1c01-dca1-4021-8a9d-870955020444\n\nSend boards or press "Cancel":',
                'followers_title': '👥 Followers\n\nYou don\'t have any wallet addresses added yet.\nFirst add addresses to get followers.',
                'followers_select': '👥 Followers\n\nChoose a wallet address to get followers:',
                'token_holders_title': '🪙 Token holders\n\nYou don\'t have any wallet addresses or boards added yet.\nFirst add them to get token holders.',
                'token_holders_select': '🪙 Token holders\n\nChoose a wallet address to get token holders:',
                'processing_complete': '✅ Processing complete\n\nValid addresses: {valid_count}\nInvalid addresses: {invalid_count}',
                'processing_complete_boards': '✅ Processing complete\n\nValid boards: {valid_count}\nInvalid boards: {invalid_count}',
                'invalid_addresses': '❌ Invalid addresses:\n{addresses}',
                'invalid_boards': '❌ Invalid boards:\n{boards}',
                'back_to_data': '← Back to data',
                'add_wallets_btn': 'Add Addresses',
                'add_boards_btn': 'Add Boards',
                'back_to_main_btn': '← Back',
                'error_wallet_index': '❌ Error: invalid wallet index',
                'error_achievement_check': '❌ Achievement check error\n\nFailed to get achievement information for address:\n{wallet_address}\n\nPlease try again later.',
                'error_achievement_check_general': '❌ Achievement check error\n\nFailed to verify achievement completion.\nPlease try again later.',
                'achievement_completed': '✅ Achievement already completed!\n\n🎉 Congratulations! Achievement "{achievement_name}" is already completed for address:\n{wallet_address}\n\nWould you like to continue and help other users?',
                'achievement_completed_added': '✅ Achievement already completed!\n\n🎉 Congratulations! Achievement "{achievement_name}" is already completed for address:\n{wallet_address}\n\nYour address has been added to the general list to help other users.\nWould you like to continue helping?',
                'trendsetter_status': '📊 "Trendsetter" Achievement Status\n\nAddress: {wallet_address}\nProgress: {progress}/{required}\nRemaining to get: {remaining} followers\nCompleted tasks: {completed_tasks}\n\nGenerating subscription links...',
                'token_holders_status': '📊 "They Lovin\' It" Achievement Status\n\nAddress: {wallet_address}\nProgress: {progress}/{required}\nRemaining to get: {remaining} holders\nCompleted tasks: {completed_tasks}\n\nGenerating token purchase links...',
                'followers_available': '👥 Followers for address {wallet_address_short}...\n\n📋 Available addresses: {available_count} out of {needed_count} needed\n\nSubscribe to the following profiles:\n{links}\n\nAfter subscribing, press "Done".',
                'tokens_available': '🪙 Token holders for address {wallet_address_short}...\n\n📋 Available tokens: {available_count} out of {needed_count} needed\n\nBuy the following tokens:\n{links}\n\nAfter purchasing, press "Done".',
                'insufficient_addresses': '\n\n⏳ Not enough addresses to complete the task.\nWe will notify you when new addresses appear.',
                'insufficient_tokens': '\n\n⏳ Not enough tokens to complete the task.\nWe will notify you when new tokens appear.',
                'achievement_success': '🎉 Congratulations!\n\nAchievement "{achievement_name}" successfully completed for address:\n{wallet_address}\n\nYour address has been added to the general list to help other users.\nCompleted tasks: {completed_tasks}',
                'achievement_success_simple': '🎉 Congratulations!\n\nAchievement "{achievement_name}" successfully completed for address:\n{wallet_address}\n\nCompleted tasks: {completed_tasks}',
                'help_others_followers': '🤝 Helping other users\n\nSubscribe to these profiles to help others get the achievement:\n\n{links}\n\nThank you for your help! 🙏',
                'help_others_tokens': '🤝 Helping other users\n\nBuy tokens using these links to help others get the achievement:\n\n{links}\n\nThank you for your help! 🙏',
                'no_available_addresses': '❌ No available addresses\n\nThere are no other addresses in the system for help.',
                'no_available_tokens': '❌ No available tokens\n\nThere are no other tokens in the system for help.',
                'achievement_not_completed': '⏳ Achievement not completed yet\n\nRemaining to get: {remaining} {type}\n\nYou may need to wait some time for data to update.\nTry checking again in 30 seconds.',
                'checking_purchases': '🔍 Checking token purchases...',
                'checking_followers': '🔍 Checking subscriptions...',
                'data_not_updated': '⏳ Data not updated yet\n\nAPI shows you haven\'t bought any of the {count} tokens yet.\n\nIf you\'re sure you bought all tokens, you can close this menu.\nWe will check every 5 minutes and notify you when data updates.\n\nMaximum checks: 30 (2.5 hours)',
                'data_not_updated_followers': '⏳ Data not updated yet\n\nAPI shows you haven\'t subscribed to any of the {count} profiles yet.\n\nIf you\'re sure you subscribed to everyone, you can close this menu.\nWe will check every 5 minutes and notify you when data updates.\n\nMaximum checks: 30 (2.5 hours)',
                'all_purchases_complete': '✅ Purchases completed!\n\nYou successfully bought all {count} tokens.\nCompleted tasks: {completed_tasks}\n\nAchievement may update after some time.',
                'all_followers_complete': '✅ Subscriptions completed!\n\nYou successfully subscribed to all {count} profiles.\nCompleted tasks: {completed_tasks}\n\nAchievement may update after some time.',
                'not_all_purchases': '⚠️ Not all purchases completed\n\nYou bought {purchased} out of {total} tokens.\n\nStill need to buy:\n{links}\n\nAfter purchasing, press "Done" again.',
                'not_all_followers': '⚠️ Not all subscriptions completed\n\nYou subscribed to {followed} out of {total} profiles.\n\nStill need to subscribe to:\n{links}\n\nIf you\'re sure you subscribed to everyone, you can close this menu.\nWe will check every 5 minutes and notify you when data updates.',
                'insufficient_tokens_system': '❌ Not enough tokens\n\nThere are not enough tokens in the system to generate links.',
                'insufficient_addresses_system': '❌ Not enough addresses\n\nThere are not enough addresses in the system to generate links.',
                'refresh_links_tokens': '🔄 Updated token purchase links\n\nBuy tokens using these links to get {remaining} holders:\n\n{links}\n\nAfter purchasing, press "Done".',
                'refresh_links_followers': '🔄 Updated subscription links\n\nSubscribe to these profiles to get {remaining} followers:\n\n{links}\n\nAfter subscribing, press "Done".',
                'followers_type': 'followers',
                'holders_type': 'holders',
                'user_stats_title': '📊 User Statistics\n\n👤 Address: {wallet_address}\n👥 Followers: {followers_count}\n📝 Following: {following_count}\n🏆 Completed achievements: {total_achievements}\n\n🎯 Achievement progress:\n{achievements_progress}',
                'achievement_completed_icon': '✅',
                'achievement_in_progress_icon': '⏳',
                'achievement_progress_line': '{icon} {name}: {progress}/{required} ({remaining} remaining)',
                'achievement_completed_line': '{icon} {name}: Completed!',
                'social_butterfly': 'Social Butterfly',
                'trendsetter': 'Trendsetter',
                'they_lovin_it': 'They Lovin\' It',
                'user_stats_compact': '📊 User Statistics\n\n👤 Address: {wallet_address}\n👥 {followers_count}📝 {following_count} 🏆 {total_achievements}/{total_achievements_possible}\n\n{achievements_progress}',
                'updating_data': '🔄 Updating data...',
                'wallet_label': '📊 Wallet {index}',
                'wallet_stats_label': '📊 Wallet statistics {index}',
                'more_wallets': '📊 ... and {count} more wallets'
            }
        }
    
    def get_text(self, user_id: int, key: str, **kwargs) -> str:
        """Получает переведенный текст для пользователя"""
        user_data = self.users_data.get(user_id, UserData([], []))
        language = user_data.language
        text = self.translations.get(language, self.translations['ru']).get(key, key)
        return text.format(**kwargs) if kwargs else text
    
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
                            completed_token_tasks=user_data.get('completed_token_tasks', 0),
                            language=user_data.get('language', 'ru'),
                            followers_progress=user_data.get('followers_progress', {}),
                            token_progress=user_data.get('token_progress', {})
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
                    'completed_token_tasks': user_data.completed_token_tasks,
                    'language': user_data.language,
                    'followers_progress': user_data.followers_progress,
                    'token_progress': user_data.token_progress
                }
                for user_id, user_data in self.users_data.items()
            }
            with open(self.users_data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка сохранения данных пользователей: {e}")

    def load_user_stats_store(self) -> Dict[str, Dict]:
        """Загружает файл статистики для главного меню"""
        try:
            if os.path.exists(self.user_stats_file):
                with open(self.user_stats_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Ошибка загрузки файла статистики: {e}")
        return {}

    def save_user_stats_store(self):
        """Сохраняет файл статистики для главного меню"""
        try:
            with open(self.user_stats_file, 'w', encoding='utf-8') as f:
                json.dump(self.user_stats_store, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка сохранения файла статистики: {e}")
    
    def ensure_data_files(self):
        """Создает файлы данных если их нет"""
        for file_path in [self.wallets_file, self.boards_file, self.tokens_file, self.user_stats_file]:
            if not os.path.exists(file_path):
                with open(file_path, 'w', encoding='utf-8') as f:
                    if file_path == self.user_stats_file:
                        json.dump({}, f, ensure_ascii=False, indent=2)
                    else:
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
            [InlineKeyboardButton(self.get_text(user_id, 'my_data'), callback_data="my_data")],
            [InlineKeyboardButton(self.get_text(user_id, 'followers'), callback_data="followers")],
            [InlineKeyboardButton(self.get_text(user_id, 'token_holders'), callback_data="token_holders")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def get_main_menu_message(self, user_id: int) -> str:
        """Создает сообщение главного меню"""
        user_data = self.users_data.get(user_id, UserData([], []))
        wallet_count = len(user_data.wallet_addresses)
        board_count = len(user_data.board_addresses)
        
        # Базовое сообщение (уберем строку призыва к действию в конец)
        welcome_text = self.get_text(user_id, 'welcome', wallet_count=wallet_count, board_count=board_count)
        language = self.users_data.get(user_id, UserData([], [])).language
        select_action = 'Выберите действие:' if language == 'ru' else 'Choose an action:'
        base_message = welcome_text.replace(select_action, '').rstrip()
        
        # Если у пользователя есть адреса, добавляем статистику
        if user_data.wallet_addresses:
            # Всегда показываем не более 8 кошельков, чтобы влезало в сообщение
            max_to_show = 8
            # Проверяем, есть ли кэш для всех кошельков (не только первых 3)
            has_cache = True
            wallets_to_check = user_data.wallet_addresses
            
            for wallet in wallets_to_check:
                cached_stats = self.stats_cache.get_cached_stats(wallet, True) or self.stats_cache.get_cached_stats(wallet, False)
                if not cached_stats or cached_stats.is_expired(5):
                    has_cache = False
                    break
            
            if has_cache:
                # Если есть кэш, показываем статистику
                wallets_to_show = user_data.wallet_addresses[:max_to_show]
                stats_messages = []
                for wallet in wallets_to_show:
                    cached_stats = self.stats_cache.get_cached_stats(wallet, True) or self.stats_cache.get_cached_stats(wallet, False)
                    if cached_stats:
                        wallet_stats = self._format_wallet_block(user_id, cached_stats.formatted_message)
                        stats_messages.append(wallet_stats)
                if len(user_data.wallet_addresses) > max_to_show:
                    stats_messages.append(self.get_text(user_id, 'more_wallets', count=len(user_data.wallet_addresses) - max_to_show))
                stats_message = '\n\n'.join(stats_messages)
                return f"{base_message}\n\n{stats_message}\n\n{select_action}"
            else:
                # Если нет кэша, пробуем взять данные из файлового хранилища
                user_key = str(user_id)
                stats_messages = []
                if user_key in self.user_stats_store and self.user_stats_store[user_key].get('wallets'):
                    wallets_to_show = user_data.wallet_addresses[:max_to_show]
                    for wallet in wallets_to_show:
                        stored = self.user_stats_store[user_key]['wallets'].get(wallet)
                        if stored and stored.get('formatted'):
                            wallet_stats = self._format_wallet_block(user_id, stored['formatted'])
                            stats_messages.append(wallet_stats)
                    if len(user_data.wallet_addresses) > max_to_show:
                        stats_messages.append(self.get_text(user_id, 'more_wallets', count=len(user_data.wallet_addresses) - max_to_show))
                    if stats_messages:
                        return f"{base_message}\n\n{'\n\n'.join(stats_messages)}\n\n{select_action}"
                # Если и в файле нет — показываем заглушку
                loading_message = self.get_text(user_id, 'updating_data')
                return f"{base_message}\n\n{loading_message}\n\n{select_action}"
        
        return f"{base_message}\n\n{select_action}"

    def _format_wallet_block(self, user_id: int, formatted_message: str) -> str:
        """Форматирует блок кошелька: ставит адрес заголовком, убирает лишние пустые строки внутри блока, сохраняет отступы между кошельками"""
        try:
            language = self.users_data.get(user_id, UserData([], [])).language
            # Определяем исходный заголовок
            header_src = "📊 Статистика пользователя" if language == 'ru' else "📊 User Statistics"
            # Удаляем исходный заголовок полностью, не дублируем адрес
            body = formatted_message.replace(header_src, "")
            # Убираем все пустые строки внутри блока
            compact_lines = []
            for line in body.splitlines():
                if len(line.strip()) == 0:
                    continue
                compact_lines.append(line)
            # Убираем возможную пустую строку в начале
            while compact_lines and len(compact_lines[0].strip()) == 0:
                compact_lines.pop(0)
            # Убираем пустую строку в конце блока
            while compact_lines and len(compact_lines[-1].strip()) == 0:
                compact_lines.pop()
            return "\n".join(compact_lines)
        except Exception:
            return formatted_message
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        user_id = update.effective_user.id
        
        # Инициализируем пользователя если его нет
        if user_id not in self.users_data:
            self.users_data[user_id] = UserData([], [])
            self.save_users_data()
        
        # Проверяем, есть ли у пользователя выбранный язык
        user_data = self.users_data[user_id]
        if not hasattr(user_data, 'language') or user_data.language is None:
            # Показываем меню выбора языка
            await self.show_language_selection(update)
        else:
            # Показываем главное меню
            user_data = self.users_data[user_id]
            
            # Показываем меню сразу с доступными данными
            message = self.get_main_menu_message(user_id)
            keyboard = self.get_main_menu_keyboard(user_id)
            sent = await update.message.reply_text(message, reply_markup=keyboard, parse_mode='HTML')
            # Сохраняем id сообщения главного меню
            if sent and getattr(sent, 'message_id', None):
                self.user_main_menu_message_id[user_id] = sent.message_id
            
        # Если есть кошельки, при необходимости запускаем фоновое обновление кэша без ожидания
            if user_data.wallet_addresses:
                use_compact = len(user_data.wallet_addresses) >= 5
                
                # Проверяем, нужно ли обновить кэш
                needs_update = False
                if use_compact:
                    wallets_to_check = user_data.wallet_addresses[:3]
                else:
                    wallets_to_check = user_data.wallet_addresses
                
                for wallet in wallets_to_check:
                    cached_stats = self.stats_cache.get_cached_stats(wallet, use_compact)
                    if not cached_stats or cached_stats.is_expired(5):
                        needs_update = True
                        break
                
                if needs_update:
                    # Запускаем фоновое обновление кэша (дедупликация по пользователю)
                    existing = self.user_cache_update_tasks.get(user_id)
                    if existing and not existing.done():
                        pass
                    else:
                        task = self.application.create_task(self.background_cache_update(user_id, use_compact))
                        self.user_cache_update_tasks[user_id] = task
    
    async def show_language_selection(self, update: Update):
        """Показывает меню выбора языка"""
        message = "🌐 Выберите язык / Choose language:"
        keyboard = [
            [InlineKeyboardButton("🇷🇺 Русский", callback_data="set_language_ru")],
            [InlineKeyboardButton("🇺🇸 English", callback_data="set_language_en")]
        ]
        
        if hasattr(update, 'message'):
            await update.message.reply_text(message, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.callback_query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def language_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /language"""
        user_id = update.effective_user.id
        
        # Инициализируем пользователя если его нет
        if user_id not in self.users_data:
            self.users_data[user_id] = UserData([], [])
            self.save_users_data()
        
        await self.show_language_selection(update)
    
    async def set_language(self, query, language: str):
        """Устанавливает язык пользователя"""
        user_id = query.from_user.id
        
        if user_id not in self.users_data:
            self.users_data[user_id] = UserData([], [])
        
        self.users_data[user_id].language = language
        self.save_users_data()
        
        language_name = "Русский" if language == 'ru' else "English"
        message = f"✅ Язык изменен на: {language_name}"
        
        keyboard = [
            [InlineKeyboardButton(self.get_text(user_id, 'main_menu'), callback_data="back_to_main")]
        ]
        
        await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def my_data_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /my"""
        user_id = update.effective_user.id
        
        # Инициализируем пользователя если его нет
        if user_id not in self.users_data:
            self.users_data[user_id] = UserData([], [])
            self.save_users_data()
        
        # Создаем фейковый query для использования существующего метода
        class FakeQuery:
            def __init__(self, user_id):
                self.from_user = type('obj', (object,), {'id': user_id})()
            
            async def edit_message_text(self, text, reply_markup=None):
                await update.message.reply_text(text, reply_markup=reply_markup)
        
        fake_query = FakeQuery(user_id)
        await self.show_my_data_menu(fake_query)
    
    async def trendsetter_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /trendsetter"""
        user_id = update.effective_user.id
        
        # Инициализируем пользователя если его нет
        if user_id not in self.users_data:
            self.users_data[user_id] = UserData([], [])
            self.save_users_data()
        
        # Создаем фейковый query для использования существующего метода
        class FakeQuery:
            def __init__(self, user_id):
                self.from_user = type('obj', (object,), {'id': user_id})()
            
            async def edit_message_text(self, text, reply_markup=None):
                await update.message.reply_text(text, reply_markup=reply_markup)
        
        fake_query = FakeQuery(user_id)
        await self.show_followers_menu(fake_query)
    
    async def tokens_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /tokens"""
        user_id = update.effective_user.id
        
        # Инициализируем пользователя если его нет
        if user_id not in self.users_data:
            self.users_data[user_id] = UserData([], [])
            self.save_users_data()
        
        # Создаем фейковый query для использования существующего метода
        class FakeQuery:
            def __init__(self, user_id):
                self.from_user = type('obj', (object,), {'id': user_id})()
            
            async def edit_message_text(self, text, reply_markup=None):
                await update.message.reply_text(text, reply_markup=reply_markup)
        
        fake_query = FakeQuery(user_id)
        await self.show_token_holders_menu(fake_query)
    
    async def set_bot_commands(self):
        """Устанавливает меню команд бота"""
        from telegram import BotCommand
        
        commands = [
            BotCommand("start", "Main menu / Главное меню"),
            BotCommand("my", "My data / Мои данные"),
            BotCommand("trendsetter", "Execute subscriptions / Выполнить подписки"),
            BotCommand("tokens", "Buy user tokens / Купить токены пользователей"),
            BotCommand("language", "Language selection / Выбор языка")
        ]
        
        await self.application.bot.set_my_commands(commands)
    
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
        elif data == "set_language_ru":
            await self.set_language(query, 'ru')
        elif data == "set_language_en":
            await self.set_language(query, 'en')
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
        user_data = self.users_data.get(user_id, UserData([], []))
        
        # Показываем меню сразу с доступными данными
        message = self.get_main_menu_message(user_id)
        keyboard = self.get_main_menu_keyboard(user_id)
        edited = await query.edit_message_text(message, reply_markup=keyboard, parse_mode='HTML')
        # Сохраняем id сообщения главного меню
        if edited and getattr(edited, 'message_id', None):
            self.user_main_menu_message_id[user_id] = edited.message_id
        
        # Если есть кошельки, при необходимости запускаем фоновое обновление кэша без ожидания
        if user_data.wallet_addresses:
            use_compact = len(user_data.wallet_addresses) >= 5
            
            # Проверяем, нужно ли обновить кэш (по устареванию 5 минут)
            needs_update = False
            if use_compact:
                wallets_to_check = user_data.wallet_addresses[:3]
            else:
                wallets_to_check = user_data.wallet_addresses
            
            for wallet in wallets_to_check:
                cached_stats = self.stats_cache.get_cached_stats(wallet, use_compact)
                if not cached_stats or cached_stats.is_expired(5):
                    needs_update = True
                    break
            
            if needs_update:
                # Запускаем фоновое обновление кэша (дедупликация по пользователю)
                existing = self.user_cache_update_tasks.get(user_id)
                if not existing or existing.done():
                    task = self.application.create_task(self.background_cache_update(user_id, use_compact))
                    self.user_cache_update_tasks[user_id] = task
    
    async def show_my_data_menu(self, query):
        """Показывает меню 'Мои данные'"""
        user_id = query.from_user.id
        user_data = self.users_data.get(user_id, UserData([], []))
        
        message = self.get_text(user_id, 'my_data_title', 
                               wallet_count=len(user_data.wallet_addresses),
                               board_count=len(user_data.board_addresses))
        
        keyboard = [
            [InlineKeyboardButton(self.get_text(user_id, 'add_wallets'), callback_data="add_wallets")],
            [InlineKeyboardButton(self.get_text(user_id, 'add_boards'), callback_data="add_boards")],
            [InlineKeyboardButton(self.get_text(user_id, 'back'), callback_data="back_to_main")]
        ]
        
        await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def show_add_wallets_menu(self, query):
        """Показывает меню добавления адресов"""
        user_id = query.from_user.id
        message = self.get_text(user_id, 'add_wallets_title')
        
        keyboard = [
            [InlineKeyboardButton(self.get_text(user_id, 'cancel'), callback_data="my_data")]
        ]
        
        await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def show_add_boards_menu(self, query):
        """Показывает меню добавления бордов"""
        user_id = query.from_user.id
        message = self.get_text(user_id, 'add_boards_title')
        
        keyboard = [
            [InlineKeyboardButton(self.get_text(user_id, 'cancel'), callback_data="my_data")]
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
            message = self.get_text(user_id, 'followers_title')
            
            keyboard = [
                [InlineKeyboardButton(self.get_text(user_id, 'add_wallets'), callback_data="add_wallets")],
                [InlineKeyboardButton(self.get_text(user_id, 'back'), callback_data="back_to_main")]
            ]
        else:
            message = self.get_text(user_id, 'followers_select')
            
            # Создаем кнопки для кошельков
            wallet_buttons = []
            for i, address in enumerate(user_data.wallet_addresses):
                short_address = f"{address[:6]}...{address[-4:]}"
                wallet_buttons.append(InlineKeyboardButton(
                    f"📱 {short_address}", 
                    callback_data=f"followers_wallet_{i}"
                ))
            
            # Группируем кнопки по 3 в ряд, если кошельков больше 3
            if len(user_data.wallet_addresses) > 3:
                keyboard = group_buttons_in_rows(wallet_buttons, 3)
            else:
                keyboard = [[button] for button in wallet_buttons]
            
            keyboard.append([InlineKeyboardButton(self.get_text(user_id, 'back'), callback_data="back_to_main")])
        
        await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def show_token_holders_menu(self, query):
        """Показывает меню token holders"""
        user_id = query.from_user.id
        user_data = self.users_data.get(user_id, UserData([], []))
        
        if not user_data.wallet_addresses or not user_data.board_addresses:
            message = self.get_text(user_id, 'token_holders_title')
            
            keyboard = [
                [InlineKeyboardButton(self.get_text(user_id, 'add_wallets'), callback_data="add_wallets")],
                [InlineKeyboardButton(self.get_text(user_id, 'add_boards'), callback_data="add_boards")],
                [InlineKeyboardButton(self.get_text(user_id, 'back'), callback_data="back_to_main")]
            ]
        else:
            message = self.get_text(user_id, 'token_holders_select')
            
            # Создаем кнопки для кошельков
            wallet_buttons = []
            for i, address in enumerate(user_data.wallet_addresses):
                short_address = f"{address[:6]}...{address[-4:]}"
                wallet_buttons.append(InlineKeyboardButton(
                    f"📱 {short_address}", 
                    callback_data=f"token_wallet_{i}"
                ))
            
            # Группируем кнопки по 3 в ряд, если кошельков больше 3
            if len(user_data.wallet_addresses) > 3:
                keyboard = group_buttons_in_rows(wallet_buttons, 3)
            else:
                keyboard = [[button] for button in wallet_buttons]
            
            keyboard.append([InlineKeyboardButton(self.get_text(user_id, 'back'), callback_data="back_to_main")])
        
        await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def handle_followers_wallet_selection(self, query, wallet_index: int):
        """Обрабатывает выбор кошелька для фолловеров"""
        user_id = query.from_user.id
        user_data = self.users_data.get(user_id, UserData([], []))
        
        if wallet_index >= len(user_data.wallet_addresses):
            await query.edit_message_text(self.get_text(user_id, 'error_wallet_index'))
            return
        
        wallet_address = user_data.wallet_addresses[wallet_index]
        
        # Проверяем ачивку Trendsetter (в отдельном потоке)
        achievement = await asyncio.to_thread(self.api_client.get_trendsetter_achievement, wallet_address)
        
        if not achievement:
            message = self.get_text(user_id, 'error_achievement_check', wallet_address=wallet_address)
            
            keyboard = [
                [InlineKeyboardButton(self.get_text(user_id, 'back'), callback_data="followers")]
            ]
        elif achievement['completed']:
            # Ачивка уже выполнена – ничего не добавляем в общий список
            message = self.get_text(user_id, 'achievement_completed', 
                                  achievement_name='Trendsetter', wallet_address=wallet_address)
            
            keyboard = [
                [InlineKeyboardButton(self.get_text(user_id, 'continue'), callback_data=f"followers_continue_{wallet_index}")],
                [InlineKeyboardButton(self.get_text(user_id, 'back'), callback_data="followers")]
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
            
            message = self.get_text(user_id, 'trendsetter_status',
                                  wallet_address=wallet_address, progress=progress, 
                                  required=required, remaining=remaining, completed_tasks=completed_tasks)
            
            await query.edit_message_text(message)
            
            # Генерируем ссылки на профили (в отдельном потоке)
            profile_links = await asyncio.to_thread(self.generate_followers_links, remaining, wallet_address, user_id)
            
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
            links_text = chr(10).join([f"{i+1}. {link}" for i, link in enumerate(profile_links)])
            message = self.get_text(user_id, 'followers_available',
                                  wallet_address_short=wallet_address[:10],
                                  available_count=len(profile_links),
                                  needed_count=remaining,
                                  links=links_text)
            
            keyboard = [
                [InlineKeyboardButton(self.get_text(user_id, 'refresh'), callback_data=f"followers_refresh_{wallet_index}")],
                [InlineKeyboardButton(self.get_text(user_id, 'done'), callback_data=f"followers_done_{wallet_index}")],
                [InlineKeyboardButton(self.get_text(user_id, 'cancel'), callback_data="followers")]
            ]
            
            # Если недостаточно адресов, добавляем в очередь ожидания
            if len(profile_links) < remaining:
                # Не добавляем кошелек в общий список автоматически
                
                if self.background_checker:
                    self.background_checker.add_waiting_user(
                        user_id=user_id,
                        wallet_index=wallet_index,
                        wallet_address=wallet_address,
                        check_type="followers",
                        needed_count=remaining
                    )
                
                # Добавляем информацию о том, что недостаточно адресов
                message += self.get_text(user_id, 'insufficient_addresses')
        
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
            await query.edit_message_text(self.get_text(user_id, 'error_wallet_index'))
            return
        
        wallet_address = user_data.wallet_addresses[wallet_index]
        
        # Проверяем ачивку They Lovin' It (в отдельном потоке)
        achievement = await asyncio.to_thread(self.api_client.get_token_holders_achievement, wallet_address)
        
        if not achievement:
            message = self.get_text(user_id, 'error_achievement_check', wallet_address=wallet_address)
            
            keyboard = [
                [InlineKeyboardButton(self.get_text(user_id, 'back'), callback_data="token_holders")]
            ]
        elif achievement['completed']:
            # Для токенов не добавляем кошелёк в список адресов для фолловеров
            message = self.get_text(user_id, 'achievement_completed', 
                                  achievement_name="They Lovin' It", wallet_address=wallet_address)
            
            keyboard = [
                [InlineKeyboardButton(self.get_text(user_id, 'continue'), callback_data=f"token_continue_{wallet_index}")],
                [InlineKeyboardButton(self.get_text(user_id, 'back'), callback_data="token_holders")]
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
            
            message = self.get_text(user_id, 'token_holders_status',
                                  wallet_address=wallet_address, progress=progress, 
                                  required=required, remaining=remaining, completed_tasks=completed_tasks)
            
            await query.edit_message_text(message)
            
            # Генерируем ссылки на токены (в отдельном потоке)
            token_links = await asyncio.to_thread(self.generate_token_links, remaining, wallet_address, user_id)
            
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
            links_text = chr(10).join([f"{i+1}. {link}" for i, link in enumerate(token_links)])
            message = self.get_text(user_id, 'tokens_available',
                                  wallet_address_short=wallet_address[:10],
                                  available_count=len(token_links),
                                  needed_count=remaining,
                                  links=links_text)
            
            keyboard = [
                [InlineKeyboardButton(self.get_text(user_id, 'refresh'), callback_data=f"token_refresh_{wallet_index}")],
                [InlineKeyboardButton(self.get_text(user_id, 'done'), callback_data=f"token_done_{wallet_index}")],
                [InlineKeyboardButton(self.get_text(user_id, 'cancel'), callback_data="token_holders")]
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
                message += self.get_text(user_id, 'insufficient_tokens')
        
        await query.edit_message_text(
            text=message,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )
    
    def generate_followers_links(self, count: int, exclude_wallet: str, user_id: int = None) -> List[str]:
        """Генерирует ссылки на профили для подписки (только для адресов без ачивки Trendsetter)"""
        try:
            # Получаем все адреса пользователя для исключения
            user_addresses = set()
            if user_id and user_id in self.users_data:
                user_addresses = set(self.users_data[user_id].wallet_addresses)
            
            # Добавляем выбранный кошелек в исключения
            user_addresses.add(exclude_wallet)
            
            # Получаем все кошельки и фильтруем их
            all_wallets = self.data_manager.read_wallets()
            filtered_wallets = []
            
            print(f"🔍 Фильтруем {len(all_wallets)} кошельков для подписок...")
            
            for wallet in all_wallets:
                # Исключаем адреса пользователя
                if wallet in user_addresses:
                    continue
                
                # Проверяем ачивку Trendsetter (получается при 10+ фолловерах)
                achievement = self.api_client.get_trendsetter_achievement(wallet)
                if achievement and achievement['completed']:
                    print(f"   ❌ Адрес {wallet[:10]}... уже имеет ачивку Trendsetter (10+ фолловеров) - пропускаем")
                    # Удаляем адрес из файла, так как ачивка уже получена
                    self.data_manager.remove_wallet(wallet)
                    continue
                elif achievement is None:
                    print(f"   ⚠️ Не удалось проверить ачивку для {wallet[:10]}... - пропускаем")
                    continue
                else:
                    print(f"   ✅ Адрес {wallet[:10]}... подходит для подписок (фолловеров: {achievement.get('progress_count', 0)})")
                    filtered_wallets.append(wallet)
            
            # Берем нужное количество адресов
            if len(filtered_wallets) <= count:
                available_wallets = filtered_wallets
            else:
                available_wallets = random.sample(filtered_wallets, count)
            
            print(f"📋 Выбрано {len(available_wallets)} адресов для подписок")
            
            # Создаем HTML-ссылки на профили
            links = []
            for wallet in available_wallets:
                links.append(f'<a href="https://phi.box/profile/{wallet}">{wallet}</a>')
            
            return links
            
        except Exception as e:
            print(f"Ошибка генерации ссылок на профили: {e}")
            return []
    
    def generate_token_links(self, count: int, exclude_wallet: str, user_id: int = None) -> List[str]:
        """Генерирует ссылки на токены для покупки (только для токенов с недостаточным количеством холдеров)"""
        try:
            # Получаем все борды пользователя для исключения
            user_boards = set()
            if user_id and user_id in self.users_data:
                user_boards = set(self.users_data[user_id].board_addresses)
            
            # Получаем все токены и фильтруем их
            all_tokens = self.data_manager.read_tokens()
            filtered_tokens = []
            
            print(f"🔍 Фильтруем {len(all_tokens)} токенов для покупок...")
            
            for board_id in all_tokens:
                # Исключаем собственные борды пользователя
                if board_id in user_boards:
                    continue
                
                # Проверяем количество холдеров токена
                holders_count = self.api_client.get_token_holders_count(board_id)
                if holders_count is None:
                    print(f"   ⚠️ Не удалось проверить холдеров для токена {board_id[:10]}... - пропускаем")
                    continue
                elif holders_count >= 10:  # Порог для ачивки "They Lovin' It"
                    print(f"   ❌ Токен {board_id[:10]}... уже имеет {holders_count} холдеров - пропускаем")
                    # Удаляем токен из файла, так как ачивка уже может быть получена
                    self.data_manager.remove_token(board_id)
                    continue
                else:
                    print(f"   ✅ Токен {board_id[:10]}... подходит для покупок (холдеров: {holders_count})")
                    filtered_tokens.append(board_id)
            
            # Берем нужное количество токенов
            if len(filtered_tokens) <= count:
                available_tokens = filtered_tokens
            else:
                available_tokens = random.sample(filtered_tokens, count)
            
            print(f"📋 Выбрано {len(available_tokens)} токенов для покупок")
            
            # Создаем HTML-ссылки на токены
            links = []
            for board_id in available_tokens:
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
            await query.edit_message_text(self.get_text(user_id, 'error_wallet_index'))
            return
        
        wallet_address = user_data.wallet_addresses[wallet_index]
        
        # Проверяем ачивку снова (в отдельном потоке)
        achievement = await asyncio.to_thread(self.api_client.get_trendsetter_achievement, wallet_address)
        
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
            message = self.get_text(user_id, 'refresh_links_followers', remaining=remaining, links=links_text)
            
            keyboard = [
                [InlineKeyboardButton(self.get_text(user_id, 'refresh'), callback_data=f"followers_refresh_{wallet_index}")],
                [InlineKeyboardButton(self.get_text(user_id, 'done'), callback_data=f"followers_done_{wallet_index}")],
                [InlineKeyboardButton(self.get_text(user_id, 'cancel'), callback_data="followers")]
            ]
        else:
            message = self.get_text(user_id, 'insufficient_addresses_system')
            
            keyboard = [
                [InlineKeyboardButton(self.get_text(user_id, 'back'), callback_data="followers")]
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
            await query.edit_message_text(self.get_text(user_id, 'error_wallet_index'))
            return
        
        wallet_address = user_data.wallet_addresses[wallet_index]
        
        # Получаем список адресов, на которые нужно было подписаться
        # Это нужно сохранять в контексте или в данных пользователя
        # Пока используем упрощенную версию - проверяем ачивку
        
        # Проверяем ачивку снова (в отдельном потоке)
        achievement = await asyncio.to_thread(self.api_client.get_trendsetter_achievement, wallet_address)
        
        if not achievement:
            message = self.get_text(user_id, 'error_achievement_check_general')
            
            keyboard = [
                [InlineKeyboardButton(self.get_text(user_id, 'back'), callback_data="followers")]
            ]
        elif achievement['completed']:
            # Ачивка выполнена - проверяем, есть ли адрес в общем списке
            is_in_global_list = wallet_address in self.data_manager.read_wallets()
            
            if not is_in_global_list:
                self.add_wallet_to_global_list(wallet_address)
                message = self.get_text(user_id, 'achievement_success',
                                      achievement_name='Trendsetter', wallet_address=wallet_address,
                                      completed_tasks=user_data.completed_followers_tasks)
            else:
                message = self.get_text(user_id, 'achievement_success_simple',
                                      achievement_name='Trendsetter', wallet_address=wallet_address,
                                      completed_tasks=user_data.completed_followers_tasks)
            
            user_data.completed_followers_tasks += 1
            self.save_users_data()
            
            keyboard = [
                [InlineKeyboardButton(self.get_text(user_id, 'main_menu'), callback_data="back_to_main")]
            ]
        else:
            # Ачивка еще не выполнена - проверяем конкретные подписки
            await self.check_specific_followers(query, wallet_index, wallet_address)
    
    async def handle_followers_continue(self, query, wallet_index: int):
        """Обрабатывает продолжение помощи другим пользователям"""
        user_id = query.from_user.id
        # Генерируем случайные ссылки для помощи другим
        available_wallets = self.data_manager.get_random_wallets(5)
        
        if available_wallets:
            links_text = "\n".join([f"• <a href=\"https://phi.box/profile/{wallet}\">{wallet}</a>" for wallet in available_wallets])
            message = self.get_text(user_id, 'help_others_followers', links=links_text)
            
            keyboard = [
                [InlineKeyboardButton(self.get_text(user_id, 'main_menu'), callback_data="back_to_main")]
            ]
        else:
            message = self.get_text(user_id, 'no_available_addresses')
            
            keyboard = [
                [InlineKeyboardButton(self.get_text(user_id, 'main_menu'), callback_data="back_to_main")]
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
            await query.edit_message_text(self.get_text(user_id, 'error_wallet_index'))
            return
        
        wallet_address = user_data.wallet_addresses[wallet_index]
        
        # Проверяем ачивку снова (в отдельном потоке)
        achievement = await asyncio.to_thread(self.api_client.get_token_holders_achievement, wallet_address)
        
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
            message = self.get_text(user_id, 'refresh_links_tokens', remaining=remaining, links=links_text)
            
            keyboard = [
                [InlineKeyboardButton(self.get_text(user_id, 'refresh'), callback_data=f"token_refresh_{wallet_index}")],
                [InlineKeyboardButton(self.get_text(user_id, 'done'), callback_data=f"token_done_{wallet_index}")],
                [InlineKeyboardButton(self.get_text(user_id, 'cancel'), callback_data="token_holders")]
            ]
        else:
            message = self.get_text(user_id, 'insufficient_tokens_system')
            
            keyboard = [
                [InlineKeyboardButton(self.get_text(user_id, 'back'), callback_data="token_holders")]
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
            await query.edit_message_text(self.get_text(user_id, 'error_wallet_index'))
            return
        
        wallet_address = user_data.wallet_addresses[wallet_index]
        
        # Проверяем ачивку снова (в отдельном потоке)
        achievement = await asyncio.to_thread(self.api_client.get_token_holders_achievement, wallet_address)
        
        if not achievement:
            message = self.get_text(user_id, 'error_achievement_check_general')
            
            keyboard = [
                [InlineKeyboardButton(self.get_text(user_id, 'back'), callback_data="token_holders")]
            ]
        elif achievement['completed']:
            # Ачивка выполнена - проверяем, есть ли адрес в общем списке
            is_in_global_list = wallet_address in self.data_manager.read_wallets()
            
            if not is_in_global_list:
                self.add_wallet_to_global_list(wallet_address)
                message = self.get_text(user_id, 'achievement_success',
                                      achievement_name="They Lovin' It", wallet_address=wallet_address,
                                      completed_tasks=user_data.completed_token_tasks)
            else:
                message = self.get_text(user_id, 'achievement_success_simple',
                                      achievement_name="They Lovin' It", wallet_address=wallet_address,
                                      completed_tasks=user_data.completed_token_tasks)
            
            user_data.completed_token_tasks += 1
            self.save_users_data()
            
            keyboard = [
                [InlineKeyboardButton(self.get_text(user_id, 'main_menu'), callback_data="back_to_main")]
            ]
        else:
            # Ачивка еще не выполнена - проверяем конкретные покупки
            await self.check_specific_token_purchases(query, wallet_index, wallet_address)
    
    async def handle_token_continue(self, query, wallet_index: int):
        """Обрабатывает продолжение помощи другим пользователям с токенами"""
        user_id = query.from_user.id
        # Генерируем случайные ссылки на токены для помощи другим
        available_tokens = self.data_manager.get_random_tokens(5)
        
        if available_tokens:
            links_text = "\n".join([f"• <a href=\"https://phi.box/board/{board_id}\">{board_id}</a>" for board_id in available_tokens])
            message = self.get_text(user_id, 'help_others_tokens', links=links_text)
            
            keyboard = [
                [InlineKeyboardButton(self.get_text(user_id, 'main_menu'), callback_data="back_to_main")]
            ]
        else:
            message = self.get_text(user_id, 'no_available_tokens')
            
            keyboard = [
                [InlineKeyboardButton(self.get_text(user_id, 'main_menu'), callback_data="back_to_main")]
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
            achievement = await asyncio.to_thread(self.api_client.get_token_holders_achievement, user_wallet)
            if not achievement:
                message = self.get_text(user_id, 'error_achievement_check_general')
                
                keyboard = [
                    [InlineKeyboardButton(self.get_text(user_id, 'back'), callback_data="token_holders")]
                ]
            else:
                remaining = achievement['remaining']
                message = self.get_text(user_id, 'achievement_not_completed', 
                                      remaining=remaining, type=self.get_text(user_id, 'holders_type'))
                
                keyboard = [
                    [InlineKeyboardButton(self.get_text(user_id, 'refresh'), callback_data=f"token_done_{wallet_index}")],
                    [InlineKeyboardButton(self.get_text(user_id, 'back'), callback_data="token_holders")]
                ]
        else:
            # Проверяем конкретные покупки через API
            await query.edit_message_text(self.get_text(user_id, 'checking_purchases'))
            
            # Проверяем каждый токен (в отдельном потоке)
            purchase_results = await asyncio.to_thread(self.api_client.check_multiple_token_purchases, target_board_ids, user_wallet)
            
            # Разделяем на купленные и некупленные
            purchased = [board_id for board_id, is_purchased in purchase_results.items() if is_purchased]
            not_purchased = [board_id for board_id, is_purchased in purchase_results.items() if not is_purchased]
            
            # Учитываем только новые покупки (чтобы не двойной учёт)
            progress = user_data.token_progress.get(user_wallet, {'count': 0, 'counted_board_ids': []})
            already = set(progress.get('counted_board_ids', []))
            new_purchased = [bid for bid in purchased if bid not in already]
            # Если пользователь не купил ни одного токена (новых тоже нет), добавляем в очередь фоновой проверки
            if not new_purchased and not_purchased:
                if self.background_checker:
                    self.background_checker.add_pending_check(
                        user_id=user_id,
                        wallet_index=wallet_index,
                        wallet_address=user_wallet,
                        check_type="tokens",
                        target_board_ids=target_board_ids
                    )
                
                message = self.get_text(user_id, 'data_not_updated', count=len(target_board_ids))
                
                keyboard = [
                    [InlineKeyboardButton(self.get_text(user_id, 'refresh'), callback_data=f"token_done_{wallet_index}")],
                    [InlineKeyboardButton(self.get_text(user_id, 'back'), callback_data="token_holders")]
                ]
                
                await query.edit_message_text(
                    text=message,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    disable_web_page_preview=True
                )
                return
            
            if not not_purchased:
                # Все покупки выполнены
                progress['count'] = int(progress.get('count', 0)) + len(new_purchased)
                progress['counted_board_ids'] = list(already.union(set(new_purchased)))
                user_data.token_progress[user_wallet] = progress
                # Обновляем глобальный суммарный счётчик (если нужен)
                user_data.completed_token_tasks = sum(p.get('count', 0) for p in user_data.token_progress.values())
                self.save_users_data()
                
                # Проверяем ачивку еще раз (в отдельном потоке)
                achievement = await asyncio.to_thread(self.api_client.get_token_holders_achievement, user_wallet)
                if achievement and achievement['completed']:
                    # Проверяем, есть ли адрес в общем списке
                    is_in_global_list = user_wallet in self.data_manager.read_wallets()
                    if not is_in_global_list:
                        self.add_wallet_to_global_list(user_wallet)
                        message = self.get_text(user_id, 'achievement_success',
                                              achievement_name="They Lovin' It", wallet_address=user_wallet,
                                              completed_tasks=user_data.completed_token_tasks)
                    else:
                        message = self.get_text(user_id, 'achievement_success_simple',
                                              achievement_name="They Lovin' It", wallet_address=user_wallet,
                                              completed_tasks=user_data.completed_token_tasks)
                    
                    keyboard = [
                        [InlineKeyboardButton(self.get_text(user_id, 'main_menu'), callback_data="back_to_main")]
                    ]
                else:
                    message = self.get_text(user_id, 'all_purchases_complete', 
                                          count=len(new_purchased), completed_tasks=progress['count'])
                    
                    keyboard = [
                        [InlineKeyboardButton(self.get_text(user_id, 'main_menu'), callback_data="back_to_main")]
                    ]
            else:
                # Есть некупленные токены
                not_purchased_links = [f'<a href="https://phi.box/board/{board_id}?referrer={user_wallet}">{board_id}</a>' for board_id in not_purchased]
                links_text = "\n".join([f"• {link}" for link in not_purchased_links])
                
                message = self.get_text(user_id, 'not_all_purchases', 
                                      purchased=len(new_purchased), total=len(target_board_ids), links=links_text)
                
                keyboard = [
                    [InlineKeyboardButton(self.get_text(user_id, 'done'), callback_data=f"token_done_{wallet_index}")],
                    [InlineKeyboardButton(self.get_text(user_id, 'back'), callback_data="token_holders")]
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
            achievement = await asyncio.to_thread(self.api_client.get_trendsetter_achievement, user_wallet)
            if not achievement:
                message = self.get_text(user_id, 'error_achievement_check_general')
                
                keyboard = [
                    [InlineKeyboardButton(self.get_text(user_id, 'back'), callback_data="followers")]
                ]
            else:
                remaining = achievement['remaining']
                message = self.get_text(user_id, 'achievement_not_completed', 
                                      remaining=remaining, type=self.get_text(user_id, 'followers_type'))
                
                keyboard = [
                    [InlineKeyboardButton(self.get_text(user_id, 'refresh'), callback_data=f"followers_done_{wallet_index}")],
                    [InlineKeyboardButton(self.get_text(user_id, 'back'), callback_data="followers")]
                ]
        else:
            # Проверяем конкретные подписки через API
            await query.edit_message_text(self.get_text(user_id, 'checking_followers'))
            
            # Проверяем каждый адрес (в отдельном потоке)
            follow_results = await asyncio.to_thread(self.api_client.check_multiple_followers, target_addresses, user_wallet)
            
            # Разделяем на подписанные и неподписанные
            followed = [addr for addr, is_following in follow_results.items() if is_following]
            not_followed = [addr for addr, is_following in follow_results.items() if not is_following]
            
            # Учитываем только новые подписки (без двойного учёта)
            progress = user_data.followers_progress.get(user_wallet, {'count': 0, 'counted_addresses': []})
            already = set(progress.get('counted_addresses', []))
            new_followed = [addr for addr in followed if addr not in already]
            # Если нет новых подписок и есть неподписанные — добавляем в проверку
            if not new_followed and not_followed:
                if self.background_checker:
                    self.background_checker.add_pending_check(
                        user_id=user_id,
                        wallet_index=wallet_index,
                        wallet_address=user_wallet,
                        check_type="followers",
                        target_addresses=target_addresses
                    )
                
                message = self.get_text(user_id, 'data_not_updated_followers', count=len(target_addresses))
                
                keyboard = [
                    [InlineKeyboardButton(self.get_text(user_id, 'refresh'), callback_data=f"followers_done_{wallet_index}")],
                    [InlineKeyboardButton(self.get_text(user_id, 'back'), callback_data="followers")]
                ]
                
                await query.edit_message_text(
                    text=message,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    disable_web_page_preview=True
                )
                return
            
            if not not_followed:
                # Все подписки выполнены
                progress['count'] = int(progress.get('count', 0)) + len(new_followed)
                progress['counted_addresses'] = list(already.union(set(new_followed)))
                user_data.followers_progress[user_wallet] = progress
                # Обновляем глобальный суммарный счётчик (если нужен)
                user_data.completed_followers_tasks = sum(p.get('count', 0) for p in user_data.followers_progress.values())
                self.save_users_data()
                
                # Проверяем ачивку еще раз
                achievement = await asyncio.to_thread(self.api_client.get_trendsetter_achievement, user_wallet)
                if achievement and achievement['completed']:
                    # Проверяем, есть ли адрес в общем списке
                    is_in_global_list = user_wallet in self.data_manager.read_wallets()
                    if not is_in_global_list:
                        self.add_wallet_to_global_list(user_wallet)
                        message = self.get_text(user_id, 'achievement_success',
                                              achievement_name='Trendsetter', wallet_address=user_wallet,
                                              completed_tasks=user_data.completed_followers_tasks)
                    else:
                        message = self.get_text(user_id, 'achievement_success_simple',
                                              achievement_name='Trendsetter', wallet_address=user_wallet,
                                              completed_tasks=user_data.completed_followers_tasks)
                    
                    keyboard = [
                        [InlineKeyboardButton(self.get_text(user_id, 'main_menu'), callback_data="back_to_main")]
                    ]
                else:
                    message = self.get_text(user_id, 'all_followers_complete', 
                                          count=len(new_followed), completed_tasks=progress['count'])
                    
                    keyboard = [
                        [InlineKeyboardButton(self.get_text(user_id, 'main_menu'), callback_data="back_to_main")]
                    ]
            else:
                # Есть неподписанные адреса - предлагаем фоновую проверку
                not_followed_links = [f'<a href="https://phi.box/profile/{addr}">{addr}</a>' for addr in not_followed]
                links_text = "\n".join([f"• {link}" for link in not_followed_links])
                
                message = self.get_text(user_id, 'not_all_followers', 
                                      followed=len(new_followed), total=len(target_addresses), links=links_text)
                
                keyboard = [
                    [InlineKeyboardButton(self.get_text(user_id, 'done'), callback_data=f"followers_done_{wallet_index}")],
                    [InlineKeyboardButton(self.get_text(user_id, 'refresh'), callback_data=f"followers_done_{wallet_index}")],
                    [InlineKeyboardButton(self.get_text(user_id, 'back'), callback_data="followers")]
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
    
    def is_achievement_notification_sent(self, user_id: int, wallet_address: str, achievement_name: str) -> bool:
        """Проверяет, было ли уже отправлено уведомление о получении ачивки"""
        user_data = self.users_data.get(user_id)
        if not user_data or not user_data.sent_achievement_notifications:
            return False
        
        achievement_notifications = user_data.sent_achievement_notifications.get(achievement_name, [])
        return wallet_address in achievement_notifications
    
    def mark_achievement_notification_sent(self, user_id: int, wallet_address: str, achievement_name: str):
        """Отмечает, что уведомление о получении ачивки было отправлено"""
        user_data = self.users_data.get(user_id)
        if not user_data:
            return
        
        if not user_data.sent_achievement_notifications:
            user_data.sent_achievement_notifications = {}
        
        if achievement_name not in user_data.sent_achievement_notifications:
            user_data.sent_achievement_notifications[achievement_name] = []
        
        if wallet_address not in user_data.sent_achievement_notifications[achievement_name]:
            user_data.sent_achievement_notifications[achievement_name].append(wallet_address)
            self.save_users_data()
    
    def clear_achievement_notifications(self, user_id: int, achievement_name: str = None):
        """Очищает историю отправленных уведомлений о получении ачивок"""
        user_data = self.users_data.get(user_id)
        if not user_data:
            return
        
        if not user_data.sent_achievement_notifications:
            return
        
        if achievement_name:
            # Очищаем уведомления для конкретной ачивки
            if achievement_name in user_data.sent_achievement_notifications:
                del user_data.sent_achievement_notifications[achievement_name]
        else:
            # Очищаем все уведомления
            user_data.sent_achievement_notifications = {}
        
        self.save_users_data()
        print(f"Очищены уведомления о получении ачивок для пользователя {user_id}")
    
    def check_wallet_changes(self, user_id: int) -> bool:
        """Проверяет, изменились ли кошельки пользователя"""
        user_data = self.users_data.get(user_id)
        if not user_data:
            return False
        
        current_wallet_count = len(user_data.wallet_addresses)
        last_wallet_count = getattr(user_data, 'last_wallet_count', 0)
        
        # Если количество кошельков изменилось
        if current_wallet_count != last_wallet_count:
            print(f"🔄 Обнаружено изменение кошельков для пользователя {user_id}: {last_wallet_count} → {current_wallet_count}")
            
            # Очищаем кэш для всех кошельков пользователя
            self.stats_cache.clear_user_cache(user_data.wallet_addresses)
            
            # Обновляем счетчик
            user_data.last_wallet_count = current_wallet_count
            self.save_users_data()
            
            return True
        
        return False
    
    def get_user_statistics(self, wallet_address: str, user_id: int, compact: bool = False, use_cache: bool = True) -> str:
        """Получает статистику пользователя с прогрессом по ачивкам"""
        try:
            # Проверяем кэш если включено кэширование
            if use_cache:
                cached_stats = self.stats_cache.get_cached_stats(wallet_address, compact)
                if cached_stats:
                    return cached_stats.formatted_message
            
            # Получаем статистику пользователя
            user_stats = self.api_client.get_user_stats(wallet_address)
            if not user_stats:
                return "❌ Не удалось получить статистику пользователя"
            
            followers_count = user_stats.get('followers_count', 0)
            following_count = user_stats.get('following_count', 0)
            
            # Получаем общее количество выполненных ачивок
            total_achievements = self.api_client.get_total_achievements_count(wallet_address)
            total_achievements_possible = self.api_client.get_total_achievements_possible(wallet_address)
            
            # Получаем прогресс по конкретным ачивкам
            social_butterfly = self.api_client.get_social_butterfly_achievement(wallet_address)
            trendsetter = self.api_client.get_trendsetter_achievement(wallet_address)
            they_lovin_it = self.api_client.get_token_holders_achievement(wallet_address)
            
            # Формируем строку прогресса по ачивкам
            achievements_progress = []
            
            # Social Butterfly
            if social_butterfly:
                if social_butterfly['completed']:
                    if not compact:  # В компактном режиме не показываем выполненные ачивки
                        achievements_progress.append(
                            self.get_text(user_id, 'achievement_completed_line',
                                        icon=self.get_text(user_id, 'achievement_completed_icon'),
                                        name=self.get_text(user_id, 'social_butterfly'))
                        )
                else:
                    achievements_progress.append(
                        self.get_text(user_id, 'achievement_progress_line',
                                    icon=self.get_text(user_id, 'achievement_in_progress_icon'),
                                    name=self.get_text(user_id, 'social_butterfly'),
                                    progress=social_butterfly['progress_count'],
                                    required=social_butterfly['required_count'],
                                    remaining=social_butterfly['remaining'])
                    )
            
            # Trendsetter
            if trendsetter:
                if trendsetter['completed']:
                    if not compact:  # В компактном режиме не показываем выполненные ачивки
                        achievements_progress.append(
                            self.get_text(user_id, 'achievement_completed_line',
                                        icon=self.get_text(user_id, 'achievement_completed_icon'),
                                        name=self.get_text(user_id, 'trendsetter'))
                        )
                else:
                    achievements_progress.append(
                        self.get_text(user_id, 'achievement_progress_line',
                                    icon=self.get_text(user_id, 'achievement_in_progress_icon'),
                                    name=self.get_text(user_id, 'trendsetter'),
                                    progress=trendsetter['progress_count'],
                                    required=trendsetter['required_count'],
                                    remaining=trendsetter['remaining'])
                    )
            
            # They Lovin' It
            if they_lovin_it:
                if they_lovin_it['completed']:
                    if not compact:  # В компактном режиме не показываем выполненные ачивки
                        achievements_progress.append(
                            self.get_text(user_id, 'achievement_completed_line',
                                        icon=self.get_text(user_id, 'achievement_completed_icon'),
                                        name=self.get_text(user_id, 'they_lovin_it'))
                        )
                else:
                    achievements_progress.append(
                        self.get_text(user_id, 'achievement_progress_line',
                                    icon=self.get_text(user_id, 'achievement_in_progress_icon'),
                                    name=self.get_text(user_id, 'they_lovin_it'),
                                    progress=they_lovin_it['progress_count'],
                                    required=they_lovin_it['required_count'],
                                    remaining=they_lovin_it['remaining'])
                    )
            
            achievements_progress_text = '\n'.join(achievements_progress)
            
            # Выбираем формат в зависимости от режима
            if compact:
                formatted_message = self.get_text(user_id, 'user_stats_compact',
                                   wallet_address=wallet_address,
                                   followers_count=followers_count,
                                   following_count=following_count,
                                   total_achievements=total_achievements,
                                   total_achievements_possible=total_achievements_possible,
                                   achievements_progress=achievements_progress_text)
            else:
                formatted_message = self.get_text(user_id, 'user_stats_title',
                                   wallet_address=wallet_address,
                                   followers_count=followers_count,
                                   following_count=following_count,
                                   total_achievements=total_achievements,
                                   achievements_progress=achievements_progress_text)
            
            # Всегда сохраняем в кэш свежие данные (use_cache влияет только на чтение)
            stats_data = {
                'user_stats': user_stats,
                'total_achievements': total_achievements,
                'total_achievements_possible': total_achievements_possible,
                'social_butterfly': social_butterfly,
                'trendsetter': trendsetter,
                'they_lovin_it': they_lovin_it
            }
            self.stats_cache.set_cached_stats(wallet_address, compact, stats_data, formatted_message)

            # Обновляем файловое хранилище статистики для главного меню
            user_key = str(user_id)
            if user_key not in self.user_stats_store:
                self.user_stats_store[user_key] = {
                    'wallets': {},
                    'updated_at': datetime.now().isoformat()
                }
            # Для каждого кошелька храним скомпонованный текст и время
            self.user_stats_store[user_key]['wallets'][wallet_address] = {
                'compact': compact,
                'formatted': formatted_message,
                'updated_at': datetime.now().isoformat()
            }
            self.user_stats_store[user_key]['updated_at'] = datetime.now().isoformat()
            self.save_user_stats_store()
            
            return formatted_message
            
        except Exception as e:
            print(f"Ошибка получения статистики пользователя: {e}")
            return "❌ Ошибка получения статистики пользователя"
    
    async def load_stats_async(self, wallet_address: str, user_id: int, compact: bool = False):
        """Асинхронно загружает статистику пользователя в фоне"""
        try:
            print(f"🔄 Начинаем асинхронную загрузку статистики для {wallet_address}")
            
            # Получаем статистику без кэша
            stats_message = await asyncio.to_thread(self.get_user_statistics, wallet_address, user_id, compact, False)
            
            print(f"✅ Асинхронная загрузка статистики завершена для {wallet_address}")
            return stats_message
            
        except Exception as e:
            print(f"❌ Ошибка асинхронной загрузки статистики для {wallet_address}: {e}")
            return None
        finally:
            # Удаляем задачу из очереди загрузки
            self.stats_cache.remove_loading_task(wallet_address, compact)
    
    async def background_cache_update(self, user_id: int, use_compact: bool):
        """Фоновое обновление кэша статистики"""
        try:
            user_data = self.users_data.get(user_id)
            if not user_data or not user_data.wallet_addresses:
                return
            
            # Определяем, какие кошельки нужно обновить (все кошельки пользователя)
            wallets_to_update = []
            wallets_to_check = user_data.wallet_addresses
            
            for wallet in wallets_to_check:
                cached_stats = self.stats_cache.get_cached_stats(wallet, use_compact)
                if not cached_stats or cached_stats.is_expired(5):
                    wallets_to_update.append(wallet)
            
            # Обновляем кэш для нужных кошельков
            for wallet in wallets_to_update:
                try:
                    await asyncio.to_thread(self.get_user_statistics, wallet, user_id, use_compact, False)
                    # Данные уже сохранены в кэш в get_user_statistics
                except Exception as e:
                    print(f"Ошибка обновления кэша для {wallet}: {e}")
            
            print(f"Фоновое обновление кэша завершено для пользователя {user_id}")
            
            # Обновляем меню пользователя, если он все еще в главном меню
            await self.update_user_menu_if_needed(user_id)
            # Снимаем ссылку на таск, он завершился
            task = self.user_cache_update_tasks.get(user_id)
            if task and task.done():
                del self.user_cache_update_tasks[user_id]
            
        except Exception as e:
            print(f"Ошибка в фоновом обновлении кэша: {e}")
    
    async def update_user_menu_if_needed(self, user_id: int):
        """Если кэш обновился, перерисовывает главное меню пользователя."""
        try:
            # Проверяем, есть ли у пользователя сообщение главного меню
            message_id = self.user_main_menu_message_id.get(user_id)
            if not message_id:
                return
            # Пересобираем текст и клавиатуру
            message = self.get_main_menu_message(user_id)
            keyboard = self.get_main_menu_keyboard(user_id)
            # Пытаемся отредактировать сохраненное сообщение главного меню
            try:
                await self.application.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=message_id,
                    text=message,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            except Exception as e:
                # Игнорируем ошибку «Message is not modified» как некритичную
                if 'Message is not modified' in str(e):
                    return
                raise
        except Exception as e:
            print(f"Ошибка при обновлении меню пользователя {user_id}: {e}")
    
    async def auto_refresh_stats_cache(self):
        """Автоматически обновляет кэш статистики каждые 20 минут"""
        while True:
            try:
                await asyncio.sleep(60)  # Проверяем каждую минуту
                
                if self.stats_cache.should_auto_refresh():
                    print("🔄 Выполняем автоматическое обновление кэша статистики...")
                    
                    # Получаем все уникальные адреса из кэша
                    addresses_to_refresh = list(self.stats_cache.cache.keys())
                    
                    for wallet_address in addresses_to_refresh:
                        try:
                            # Обновляем статистику для каждого адреса
                            # Находим пользователя с этим адресом
                            user_id = None
                            for uid, user_data in self.users_data.items():
                                if wallet_address in user_data.wallet_addresses:
                                    user_id = uid
                                    break
                            
                            if user_id:
                                # Обновляем статистику без кэша
                                await asyncio.to_thread(self.get_user_statistics, wallet_address, user_id, False, False)
                                print(f"✅ Обновлена статистика для {wallet_address}")
                        except Exception as e:
                            print(f"❌ Ошибка обновления статистики для {wallet_address}: {e}")
                    
                    # Очищаем устаревший кэш
                    self.stats_cache.clear_expired_cache()
                    
                    # Отмечаем, что автообновление выполнено
                    self.stats_cache.mark_auto_refresh_done()
                    print("✅ Автоматическое обновление кэша завершено")
                    
            except Exception as e:
                print(f"❌ Ошибка в автоматическом обновлении кэша: {e}")
    
    def cleanup_completed_achievements(self):
        """Очищает файлы от адресов и токенов с уже полученными ачивками"""
        print("🧹 Начинаем очистку файлов от адресов с полученными ачивками...")
        
        # Очищаем кошельки
        wallets = self.data_manager.read_wallets()
        wallets_to_remove = []
        
        print(f"📋 Проверяем {len(wallets)} кошельков...")
        
        for wallet in wallets:
            achievement = self.api_client.get_trendsetter_achievement(wallet)
            if achievement and achievement['completed']:
                print(f"   ❌ Удаляем {wallet[:10]}... (ачивка Trendsetter получена - 10+ фолловеров)")
                wallets_to_remove.append(wallet)
        
        for wallet in wallets_to_remove:
            self.data_manager.remove_wallet(wallet)
        
        if wallets_to_remove:
            print(f"🗑️ Удалено {len(wallets_to_remove)} кошельков из wallets.txt")
        
        # Очищаем токены
        tokens = self.data_manager.read_tokens()
        tokens_to_remove = []
        
        print(f"📋 Проверяем {len(tokens)} токенов...")
        
        for board_id in tokens:
            holders_count = self.api_client.get_token_holders_count(board_id)
            if holders_count is not None and holders_count >= 10:
                print(f"   ❌ Удаляем {board_id[:10]}... ({holders_count} холдеров)")
                tokens_to_remove.append(board_id)
        
        for board_id in tokens_to_remove:
            self.data_manager.remove_token(board_id)
        
        if tokens_to_remove:
            print(f"🗑️ Удалено {len(tokens_to_remove)} токенов из tokens.txt")
        
        print("✅ Очистка завершена!")
    
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
        
        message = self.get_text(user_id, 'processing_complete', 
                               valid_count=len(valid_addresses),
                               invalid_count=len(invalid_addresses))
        
        if invalid_addresses:
            message += "\n\n" + self.get_text(user_id, 'invalid_addresses', addresses="\n".join(invalid_addresses))
        
        keyboard = [
            [InlineKeyboardButton(self.get_text(user_id, 'back_to_data'), callback_data="my_data")]
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
        
        message = self.get_text(user_id, 'processing_complete_boards', 
                               valid_count=len(valid_boards),
                               invalid_count=len(invalid_boards))
        
        if invalid_boards:
            message += "\n\n" + self.get_text(user_id, 'invalid_boards', boards="\n".join(invalid_boards))
        
        keyboard = [
            [InlineKeyboardButton(self.get_text(user_id, 'back_to_data'), callback_data="my_data")]
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
        
        # Добавляем обработчики команд
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("language", self.language_command))
        self.application.add_handler(CommandHandler("my", self.my_data_command))
        self.application.add_handler(CommandHandler("trendsetter", self.trendsetter_command))
        self.application.add_handler(CommandHandler("tokens", self.tokens_command))
        
        # Добавляем обработчики кнопок и сообщений
        self.application.add_handler(CallbackQueryHandler(self.button_callback))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        print("Бот запущен...")
        
        async def _post_init(app):
            # Устанавливаем меню команд
            await self.set_bot_commands()
            # Запускаем фоновые задачи через приложение (его event loop)
            app.create_task(self.background_checker.start_background_checking())
            app.create_task(self.auto_refresh_stats_cache())
        
        # Регистрируем post_init хук, без использования JobQueue
        self.application.post_init = _post_init
        
        # Запускаем бота (внутри будет создан и использован один event loop)
        self.application.run_polling()

if __name__ == "__main__":
    bot = PHIBot()
    bot.run()
