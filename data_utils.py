import os
import random
from typing import List, Set, Tuple

class DataManager:
    """Класс для управления файлами данных"""
    
    def __init__(self, wallets_file: str = 'wallets.txt', 
                 boards_file: str = 'boards.txt', 
                 tokens_file: str = 'tokens.txt'):
        self.wallets_file = wallets_file
        self.boards_file = boards_file
        self.tokens_file = tokens_file
    
    def _safe_comparison(self, value: any, threshold: int, operation: str = ">=") -> bool:
        """Безопасное сравнение с проверкой на None"""
        if value is None:
            print(f"Предупреждение: попытка сравнения None с {threshold}")
            return False
        
        try:
            if operation == ">=":
                return value >= threshold
            elif operation == ">":
                return value > threshold
            elif operation == "<=":
                return value <= threshold
            elif operation == "<":
                return value < threshold
            elif operation == "==":
                return value == threshold
            else:
                print(f"Неизвестная операция сравнения: {operation}")
                return False
        except TypeError as e:
            print(f"Ошибка сравнения {value} {operation} {threshold}: {e}")
            return False
    
    def read_wallets(self) -> List[str]:
        """Читает список кошельков из файла"""
        try:
            if not os.path.exists(self.wallets_file):
                return []
            
            with open(self.wallets_file, 'r', encoding='utf-8') as f:
                wallets = []
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        wallets.append(line)
                return wallets
        except Exception as e:
            print(f"Ошибка чтения файла кошельков: {e}")
            return []
    
    def read_boards(self) -> List[str]:
        """Читает список бордов из файла"""
        try:
            if not os.path.exists(self.boards_file):
                return []
            
            with open(self.boards_file, 'r', encoding='utf-8') as f:
                boards = []
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        boards.append(line)
                return boards
        except Exception as e:
            print(f"Ошибка чтения файла бордов: {e}")
            return []
    
    def read_tokens(self) -> List[str]:
        """Читает список токенов из файла (только ID бордов)"""
        try:
            print(f"📁 Читаем файл токенов: {self.tokens_file}")
            
            if not os.path.exists(self.tokens_file):
                print(f"❌ Файл токенов не существует: {self.tokens_file}")
                return []
            
            tokens = []
            with open(self.tokens_file, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    original_line = line
                    line = line.strip()
                    print(f"📄 Строка {line_num}: '{original_line.strip()}' -> '{line}'")
                    
                    if line and not line.startswith('#'):
                        # Очищаем токен от URL, если это полная ссылка
                        if 'phi.box/board/' in line:
                            board_id = line.split('phi.box/board/')[-1].split('?')[0]
                            tokens.append(board_id)
                            print(f"🧹 Очищен токен: '{line}' -> '{board_id}'")
                        else:
                            tokens.append(line)
                            print(f"✅ Добавлен токен: '{line}'")
                    else:
                        print(f"⏭️ Пропущена строка: '{line}'")
            
            print(f"📋 Итого токенов: {len(tokens)}")
            print(f"📋 Токены: {tokens}")
            return tokens
            
        except Exception as e:
            print(f"❌ Ошибка чтения файла токенов: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def write_wallets(self, wallets: List[str]):
        """Записывает список кошельков в файл"""
        try:
            with open(self.wallets_file, 'w', encoding='utf-8') as f:
                f.write("# Список адресов кошельков пользователей\n")
                f.write("# Каждый адрес на новой строке\n")
                f.write("# Формат: 0x...\n\n")
                for wallet in sorted(set(wallets)):
                    f.write(f"{wallet}\n")
        except Exception as e:
            print(f"Ошибка записи файла кошельков: {e}")
    
    def write_boards(self, boards: List[str]):
        """Записывает список бордов в файл"""
        try:
            with open(self.boards_file, 'w', encoding='utf-8') as f:
                f.write("# Список бордов пользователей\n")
                f.write("# Каждый борд на новой строке\n")
                f.write("# Формат: UUID или ссылка на phi.box/board/\n\n")
                for board in sorted(set(boards)):
                    f.write(f"{board}\n")
        except Exception as e:
            print(f"Ошибка записи файла бордов: {e}")
    
    def write_tokens(self, tokens: List[str]):
        """Записывает список токенов в файл"""
        try:
            with open(self.tokens_file, 'w', encoding='utf-8') as f:
                f.write("# Список токенов пользователей\n")
                f.write("# Формат: board_id\n")
                f.write("# Каждая запись на новой строке\n\n")
                for board_id in sorted(set(tokens)):
                    # Очищаем board_id от URL если он содержит полную ссылку
                    clean_board_id = board_id
                    if 'phi.box/board/' in board_id:
                        clean_board_id = board_id.split('phi.box/board/')[-1].split('?')[0]
                    f.write(f"{clean_board_id}\n")
        except Exception as e:
            print(f"Ошибка записи файла токенов: {e}")
    
    def remove_wallet(self, wallet: str):
        """Удаляет кошелек из файла"""
        try:
            wallets = self.read_wallets()
            if wallet in wallets:
                wallets.remove(wallet)
                self.write_wallets(wallets)
                print(f"🗑️ Удален кошелек: {wallet}")
        except Exception as e:
            print(f"Ошибка удаления кошелька: {e}")
    
    def remove_token(self, token: str):
        """Удаляет токен из файла"""
        try:
            tokens = self.read_tokens()
            if token in tokens:
                tokens.remove(token)
                self.write_tokens(tokens)
                print(f"🗑️ Удален токен: {token}")
        except Exception as e:
            print(f"Ошибка удаления токена: {e}")
    
    def get_random_wallets(self, count: int, exclude: Set[str] = None) -> List[str]:
        """Получает случайные кошельки из списка"""
        wallets = self.read_wallets()
        if exclude:
            wallets = [w for w in wallets if w not in exclude]
        
        if len(wallets) <= count:
            return wallets
        
        return random.sample(wallets, count)
    
    def get_random_tokens(self, count: int, exclude_boards: Set[str] = None) -> List[str]:
        """Получает случайные токены из списка"""
        print(f"🎲 get_random_tokens: нужно {count}, исключить {exclude_boards}")
        
        tokens = self.read_tokens()
        print(f"📁 Прочитано токенов из файла: {len(tokens)}")
        print(f"📋 Токены из файла: {tokens}")
        
        if exclude_boards:
            print(f"🚫 Исключаем борды: {exclude_boards}")
            # Очищаем exclude_boards от URL если они содержат полные ссылки
            clean_exclude_boards = set()
            for board in exclude_boards:
                if 'phi.box/board/' in board:
                    clean_board = board.split('phi.box/board/')[-1].split('?')[0]
                    clean_exclude_boards.add(clean_board)
                    print(f"🧹 Очищен исключаемый борд: {board} -> {clean_board}")
                else:
                    clean_exclude_boards.add(board)
            
            print(f"🚫 Очищенные исключаемые борды: {clean_exclude_boards}")
            tokens = [t for t in tokens if t not in clean_exclude_boards]
            print(f"📋 Токены после исключения: {len(tokens)}")
            print(f"📋 Токены после исключения: {tokens}")
        
        if len(tokens) <= count:
            print(f"✅ Возвращаем все токены: {len(tokens)}")
            return tokens
        
        result = random.sample(tokens, count)
        print(f"🎲 Возвращаем случайные токены: {len(result)}")
        print(f"📋 Случайные токены: {result}")
        return result
    
    def remove_wallet_if_completed(self, wallet: str, achievement_type: str, threshold: int, api_client):
        """
        Удаляет кошелек из списка если ачивка выполнена
        
        Args:
            wallet: Адрес кошелька
            achievement_type: Тип ачивки ('followers' или 'token_holders')
            threshold: Пороговое значение для ачивки
            api_client: Клиент для работы с API
        """
        try:
            if achievement_type == 'followers':
                current_count = api_client.get_followers_count(wallet)
            elif achievement_type == 'token_holders':
                # Для токенов нужно проверить все борды пользователя
                # Это упрощенная версия - в реальности нужно проверить каждый токен
                return
            else:
                return
            
            if current_count is not None and current_count >= threshold:
                # Удаляем кошелек из списка
                wallets = self.read_wallets()
                if wallet in wallets:
                    wallets.remove(wallet)
                    self.write_wallets(wallets)
                    print(f"Кошелек {wallet} удален из списка (ачивка выполнена)")
        
        except Exception as e:
            print(f"Ошибка проверки и удаления кошелька: {e}")
    
    def remove_token_if_completed(self, wallet: str, board: str, threshold: int, api_client):
        """
        Удаляет токен из списка если ачивка выполнена
        
        Args:
            wallet: Адрес кошелька
            board: ID борда
            threshold: Пороговое значение для ачивки
            api_client: Клиент для работы с API
        """
        try:
            current_count = api_client.get_token_holders_count(wallet, board)
            
            if current_count is not None and current_count >= threshold:
                # Удаляем токен из списка
                tokens = self.read_tokens()
                token_to_remove = (wallet, board)
                if token_to_remove in tokens:
                    tokens.remove(token_to_remove)
                    self.write_tokens(tokens)
                    print(f"Токен {wallet}:{board} удален из списка (ачивка выполнена)")
        
        except Exception as e:
            print(f"Ошибка проверки и удаления токена: {e}")
    
    def remove_tokens_with_many_holders(self, api_client, threshold: int = 10):
        """
        Удаляет токены с количеством холдеров >= threshold
        
        Args:
            api_client: Клиент для работы с API
            threshold: Пороговое значение холдеров (по умолчанию 10)
        """
        try:
            tokens = self.read_tokens()
            tokens_to_keep = []
            
            for board_id in tokens:
                # Очищаем board_id от URL если он содержит полную ссылку
                clean_board_id = board_id
                if 'phi.box/board/' in board_id:
                    clean_board_id = board_id.split('phi.box/board/')[-1].split('?')[0]
                
                holders_count = api_client.get_token_holders_count(clean_board_id)
                if holders_count == 0:
                    print(f"🚫 Токен {clean_board_id} удален из списка (0 холдеров - нельзя купить)")
                elif self._safe_comparison(holders_count, threshold, "<"):
                    tokens_to_keep.append(clean_board_id)
                elif self._safe_comparison(holders_count, threshold, ">="):
                    print(f"✅ Токен {clean_board_id} удален из списка ({holders_count} холдеров - ≥{threshold})")
                else:
                    # Если не удалось получить данные, оставляем токен в списке
                    print(f"⚠️ Не удалось проверить холдеров для токена {clean_board_id} - оставляем в списке")
                    tokens_to_keep.append(clean_board_id)
            
            if len(tokens_to_keep) != len(tokens):
                self.write_tokens(tokens_to_keep)
                print(f"Обновлен список токенов: {len(tokens_to_keep)} из {len(tokens)}")
            
        except Exception as e:
            print(f"Ошибка удаления токенов с большим количеством холдеров: {e}")

# Пример использования
if __name__ == "__main__":
    dm = DataManager()
    
    # Читаем данные
    wallets = dm.read_wallets()
    boards = dm.read_boards()
    tokens = dm.read_tokens()
    
    print(f"Кошельков: {len(wallets)}")
    print(f"Бордов: {len(boards)}")
    print(f"Токенов: {len(tokens)}")
    
    # Получаем случайные кошельки
    random_wallets = dm.get_random_wallets(3)
    print(f"Случайные кошельки: {random_wallets}")
