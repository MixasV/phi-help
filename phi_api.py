import requests
import os
import json
from typing import Dict, List, Optional
from dotenv import load_dotenv

load_dotenv()

class PHIAPI:
    """Класс для работы с PHI API"""
    
    def __init__(self):
        self.base_url = 'https://phi.box'
        self.headers = {
            'accept': 'text/x-component',
            'accept-language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'cache-control': 'no-cache',
            'content-type': 'text/plain;charset=UTF-8',
            'next-action': 'afb871d57ba75e5e0846ceeb0ab25c51f24d2af4',
            'origin': 'https://phi.box',
            'pragma': 'no-cache',
            'priority': 'u=1, i',
            'sec-ch-ua': '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
            'x-kl-saas-ajax-request': 'Ajax_Request',
        }
        
        # Cookies для аутентификации (можно настроить через переменные окружения)
        self.cookies = {
            'wagmi.recentConnectorId': '"io.metamask"',
            'ph_phc_G5OSGfrYncMPntOPKnuzpfkeyNBO03AZ9v1iJDaDJFY_posthog': '%7B%22distinct_id%22%3A%2201988b8d-d372-7940-9a30-7eeda370de9b%22%2C%22%24sesid%22%3A%5B1758541083146%2C%2201997130-848d-74d0-bfb4-202f4a2a726d%22%2C1758540629133%5D%2C%22%24initial_person_info%22%3A%7B%22r%22%3A%22%24direct%22%2C%22u%22%3A%22https%3A%2F%2Fland.phi.box%2F%22%7D%7D',
            'refresh-token': 'eyJhbGciOiJkaXIiLCJlbmMiOiJBMjU2R0NNIn0..5aTFruha1mGpj7jr.ZVFSxNVB3Q4uAPdMN7EKQkm1r-W8cx9ag-tAcRMwyR-ufUkUKpGKuLWJSS53-Ua6HDnIJltr6-fdGIiuoQY24hHdqzccVf7nQyMd7glP17-oyLbpX78bTwvO5IZGDCDk8fBNbZD8edL6O89PIdN0iRki8t1JIXPgHqQnia-apo9XKoz7iZlaG02jCpbNMq52x04MbZlfoPFEtiZknIomrvfAZqPxO9kZNk_9R3eV7kg.1OuPZhhKFanL9gfHuH8iyg',
            'referrer': '0x7fef04d6625D0Ed61C663c82F27b81A5602B1BB1',
            'app-sidebar:state': 'false',
            'wagmi.store': '{"state":{"connections":{"__type":"Map","value":[["ff64c6cf6a5",{"accounts":["0xC7f9154a72524097B1323961F584f7047b875271"],"chainId":8453,"connector":{"id":"io.metamask","name":"MetaMask","type":"injected","uid":"ff64c6cf6a5"}}]]},"chainId":8453,"current":"ff64c6cf6a5"},"version":2}',
            'ph_phc_bsVwlbnvSSp4IfQWxqGW20kW5Iyg5eDqW7iaMIHjTPQ_posthog': '%7B%22distinct_id%22%3A%2201996855-ea7f-7b55-8639-21d74ed2ee12%22%2C%22%24sesid%22%3A%5B1758936758469%2C%220199889f-c564-7233-8feb-dee781677875%22%2C1758933796196%5D%2C%22%24initial_person_info%22%3A%7B%22r%22%3A%22%24direct%22%2C%22u%22%3A%22https%3A%2F%2Fphi.box%2Fmint%2F8453-137%2F8453-1840%3Freferrer%3D0x2A39FD94E139952C3958E69172bA918D8f533571%22%7D%7D',
        }
    
    def _parse_streaming_response(self, response_text: str) -> Optional[any]:
        """Парсит потоковый JSON ответ, который может начинаться с "0:..." или "1:..."."""
        try:
            # Разделяем строки по номерам
            import re
            lines = response_text.strip().split('\n')
            parsed_data = []
            
            for line in lines:
                if ':' in line:
                    # Извлекаем номер и данные
                    parts = line.split(':', 1)
                    if len(parts) == 2:
                        try:
                            # Парсим JSON часть
                            json_data = json.loads(parts[1])
                            parsed_data.append(json_data)
                        except json.JSONDecodeError:
                            # Если не JSON, добавляем как есть
                            parsed_data.append(parts[1])
            
            return parsed_data if parsed_data else None
            
        except Exception as e:
            print(f"Ошибка парсинга потокового JSON: {e}")
            return None
    
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
    
    def get_achievements(self, wallet_address: str) -> Optional[List[Dict]]:
        """
        Получает список ачивок для адреса кошелька
        
        Args:
            wallet_address: Адрес кошелька
            
        Returns:
            Список ачивок или None при ошибке
        """
        try:
            url = f"{self.base_url}/profile/{wallet_address}/achievement"
            
            # Обновляем headers для конкретного запроса
            headers = self.headers.copy()
            headers['next-router-state-tree'] = f'%5B%22%22%2C%7B%22children%22%3A%5B%22profile%22%2C%7B%22children%22%3A%5B%5B%22address%22%2C%22{wallet_address}%22%2C%22d%22%5D%2C%7B%22children%22%3A%5B%22achievement%22%2C%7B%22children%22%3A%5B%22__PAGE__%22%2C%7B%7D%2C%22%2Fprofile%2F{wallet_address}%2Fachievement%22%2C%22refresh%22%5D%7D%5D%7D%5D%7D%5D%7D%2Cnull%2Cnull%2Ctrue%5D'
            headers['referer'] = f'https://phi.box/profile/{wallet_address}/achievement'
            
            data = f'["{wallet_address}"]'
            
            # Увеличиваем таймаут до 30 секунд для медленных запросов
            response = requests.post(url, cookies=self.cookies, headers=headers, data=data, timeout=30)
            
            if response.status_code == 200:
                # Парсим streaming ответ
                response_data = self._parse_streaming_response(response.text)
                if response_data and len(response_data) > 1 and isinstance(response_data[1], list):
                    return response_data[1]
                print(f"Не удалось распарсить JSON для адреса {wallet_address}")
                return []
            else:
                print(f"Ошибка API для адреса {wallet_address}: {response.status_code}")
                return []
                
        except Exception as e:
            print(f"Ошибка получения ачивок: {e}")
            return None
    
    def get_trendsetter_achievement(self, wallet_address: str) -> Optional[Dict]:
        """
        Получает информацию об ачивке Trendsetter (achievement_id: 7)
        
        Args:
            wallet_address: Адрес кошелька
            
        Returns:
            Информация об ачивке или None при ошибке
        """
        try:
            achievements = self.get_achievements(wallet_address)
            if not achievements:
                return None
            
            for achievement in achievements:
                if achievement.get('achievement_id') == 7:  # Trendsetter
                    return {
                        'completed': achievement.get('completed', False),
                        'progress_count': achievement.get('progress_count', 0),
                        'required_count': achievement.get('required_count', 10),
                        'remaining': max(0, achievement.get('required_count', 10) - achievement.get('progress_count', 0)),
                        'name': achievement.get('name', 'Trendsetter'),
                        'description': achievement.get('description', 'Gain 10 followers on EFP to become a Web3 social icon')
                    }
            
            # Если ачивка не найдена, возвращаем нулевой прогресс
            return {
                'completed': False,
                'progress_count': 0,
                'required_count': 10,
                'remaining': 10,
                'name': 'Trendsetter',
                'description': 'Gain 10 followers on EFP to become a Web3 social icon'
            }
                
        except Exception as e:
            print(f"Ошибка получения ачивки Trendsetter: {e}")
            return None
    
    def get_token_holders_achievement(self, wallet_address: str) -> Optional[Dict]:
        """
        Получает информацию об ачивке They Lovin' It (achievement_id: 16)
        
        Args:
            wallet_address: Адрес кошелька
            
        Returns:
            Информация об ачивке или None при ошибке
        """
        try:
            achievements = self.get_achievements(wallet_address)
            if not achievements:
                return None
            
            for achievement in achievements:
                if achievement.get('achievement_id') == 16:  # They Lovin' It
                    return {
                        'completed': achievement.get('completed', False),
                        'progress_count': achievement.get('progress_count', 0),
                        'required_count': achievement.get('required_count', 10),
                        'remaining': max(0, achievement.get('required_count', 10) - achievement.get('progress_count', 0)),
                        'name': achievement.get('name', "They Lovin' It"),
                        'description': achievement.get('description', 'Your creator ETH reaches 10 holders')
                    }
            
            # Если ачивка не найдена, возвращаем нулевой прогресс
            return {
                'completed': False,
                'progress_count': 0,
                'required_count': 10,
                'remaining': 10,
                'name': "They Lovin' It",
                'description': 'Your creator ETH reaches 10 holders'
            }
                
        except Exception as e:
            print(f"Ошибка получения ачивки They Lovin' It: {e}")
            return None
    
    def get_followers_count(self, wallet_address: str) -> Optional[int]:
        """
        Получает количество фолловеров для адреса кошелька
        
        Args:
            wallet_address: Адрес кошелька
            
        Returns:
            Количество фолловеров или None при ошибке
        """
        try:
            achievement = self.get_trendsetter_achievement(wallet_address)
            if achievement:
                return achievement.get('progress_count', 0)
            return None
                
        except Exception as e:
            print(f"Ошибка получения фолловеров: {e}")
            return None
    
    def get_token_holders_count(self, board_id: str) -> Optional[int]:
        """
        Получает количество холдеров токена для борда
        
        Args:
            board_id: ID борда
            
        Returns:
            Количество холдеров или None при ошибке
        """
        try:
            # Используем API для получения информации о борде
            url = f"https://api.phi.box/board/{board_id}"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                # Предполагаем, что количество холдеров хранится в поле holders_count
                return data.get('holders_count', 0)
            else:
                print(f"Ошибка API для борда {board_id}: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"Ошибка получения холдеров токена для борда {board_id}: {e}")
            return None
    
    def check_followers_for_address(self, target_address: str, user_address: str) -> bool:
        """
        Проверяет, подписан ли пользователь на целевой адрес
        
        Args:
            target_address: Адрес, на который нужно было подписаться
            user_address: Адрес пользователя, который выполняет задание
            
        Returns:
            True если подписан, False если нет
        """
        try:
            url = f"http://api.ethfollow.xyz/api/v1/users/{target_address}/followers"
            
            # Увеличиваем таймаут до 30 секунд для медленных запросов
            response = requests.get(url, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                followers = data.get('followers', [])
                
                # Если followers пустой массив, значит у адреса 0 фолловеров
                if len(followers) == 0:
                    print(f"У адреса {target_address} 0 фолловеров")
                    return False
                
                # Ищем адрес пользователя в списке фолловеров
                for follower in followers:
                    if follower.get('address', '').lower() == user_address.lower():
                        return True
                
                return False
            else:
                print(f"Ошибка API ethfollow: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"Ошибка проверки фолловеров: {e}")
            return False
    
    def check_multiple_followers(self, target_addresses: List[str], user_address: str) -> Dict[str, bool]:
        """
        Проверяет подписки на несколько адресов
        
        Args:
            target_addresses: Список адресов для проверки
            user_address: Адрес пользователя
            
        Returns:
            Словарь {адрес: подписан_ли}
        """
        results = {}
        
        for target_address in target_addresses:
            results[target_address] = self.check_followers_for_address(target_address, user_address)
        
        return results
    
    def get_token_holders_count(self, board_id: str) -> Optional[int]:
        """
        Получает количество холдеров токена по ID борда
        
        Args:
            board_id: ID борда/токена
            
        Returns:
            Количество холдеров или None при ошибке
        """
        try:
            # Очищаем board_id от URL если он содержит полную ссылку
            if 'phi.box/board/' in board_id:
                board_id = board_id.split('phi.box/board/')[-1].split('?')[0]
            
            url = f"https://phi.box/board/{board_id}"
            
            # Обновляем headers для конкретного запроса
            headers = self.headers.copy()
            headers['next-router-state-tree'] = f'%5B%22%22%2C%7B%22children%22%3A%5B%22board%22%2C%7B%22children%22%3A%5B%5B%22id%22%2C%22{board_id}%22%2C%22d%22%5D%2C%7B%22children%22%3A%5B%22__PAGE__%22%2C%7B%7D%2C%22%2Fboard%2F{board_id}%22%2C%22refresh%22%5D%7D%5D%7D%5D%7D%2Cnull%2Cnull%2Ctrue%5D'
            headers['referer'] = f'https://phi.box/board/{board_id}'
            headers['next-action'] = 'fdf6e2bbf5f272e25209a9583d7434afe0ab1283'
            
            data = f'[{{"filter":{{"boardId":"{board_id}"}},"sort":"balance"}}]'
            
            # Увеличиваем таймаут до 30 секунд для медленных запросов
            response = requests.post(url, cookies=self.cookies, headers=headers, data=data, timeout=30)
            
            if response.status_code == 200:
                # Парсим streaming ответ
                parsed_data = self._parse_streaming_response(response.text)
                
                if parsed_data and len(parsed_data) > 1:
                    # Ищем данные с total
                    for item in parsed_data:
                        if isinstance(item, dict) and 'total' in item:
                            return item.get('total', 0)
                
                print(f"Не удалось найти total в ответе для токена {board_id}")
                return 0
            else:
                print(f"Ошибка API получения холдеров токена {board_id}: {response.status_code}")
                return 0
                
        except Exception as e:
            print(f"Ошибка получения количества холдеров токена: {e}")
            return None
    
    def check_token_purchase(self, board_id: str, user_address: str) -> bool:
        """
        Проверяет, купил ли пользователь токен
        
        Args:
            board_id: ID борда/токена
            user_address: Адрес пользователя
            
        Returns:
            True если купил, False если нет
        """
        try:
            # Очищаем board_id от URL если он содержит полную ссылку
            if 'phi.box/board/' in board_id:
                board_id = board_id.split('phi.box/board/')[-1].split('?')[0]
            
            url = f"https://phi.box/board/{board_id}"
            
            # Обновляем headers для конкретного запроса
            headers = self.headers.copy()
            headers['next-router-state-tree'] = f'%5B%22%22%2C%7B%22children%22%3A%5B%22board%22%2C%7B%22children%22%3A%5B%5B%22id%22%2C%22{board_id}%22%2C%22d%22%5D%2C%7B%22children%22%3A%5B%22__PAGE__%22%2C%7B%7D%2C%22%2Fboard%2F{board_id}%22%2C%22refresh%22%5D%7D%5D%7D%5D%7D%2Cnull%2Cnull%2Ctrue%5D'
            headers['referer'] = f'https://phi.box/board/{board_id}'
            headers['next-action'] = '39d6cf268cd0763be6917d586cfe9dc92ca6c5cd'
            
            data = f'["{board_id}","$undefined"]'
            
            # Увеличиваем таймаут до 30 секунд для медленных запросов
            response = requests.post(url, cookies=self.cookies, headers=headers, data=data, timeout=30)
            
            if response.status_code == 200:
                # Парсим streaming ответ
                parsed_data = self._parse_streaming_response(response.text)
                
                if parsed_data and len(parsed_data) > 1:
                    # Ищем данные с records
                    for item in parsed_data:
                        if isinstance(item, dict) and 'records' in item:
                            records = item.get('records', [])
                            
                            # Ищем запись о покупке токена пользователем
                            for record in records:
                                if (record.get('activity_type') == 'trade' and 
                                    record.get('address', '').lower() == user_address.lower()):
                                    return True
                            
                            return False
                
                print(f"Не удалось найти records в ответе для проверки покупки токена {board_id}")
                return False
            else:
                print(f"Ошибка API проверки покупки токена: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"Ошибка проверки покупки токена: {e}")
            return False
    
    def check_multiple_token_purchases(self, board_ids: List[str], user_address: str) -> Dict[str, bool]:
        """
        Проверяет покупки нескольких токенов
        
        Args:
            board_ids: Список ID бордов/токенов
            user_address: Адрес пользователя
            
        Returns:
            Словарь {board_id: купил_ли}
        """
        results = {}
        
        for board_id in board_ids:
            results[board_id] = self.check_token_purchase(board_id, user_address)
        
        return results

# Пример использования
if __name__ == "__main__":
    api = PHIAPI()
    
    # Пример проверки фолловеров
    wallet = "0xC7f9154a72524097B1323961F584f7047b875271"
    followers = api.get_followers_count(wallet)
    print(f"Фолловеры для {wallet}: {followers}")
    
    # Пример проверки ачивки
    achievement_status = api.check_achievement_status(wallet, 'followers')
    print(f"Статус ачивки фолловеров: {achievement_status}")
