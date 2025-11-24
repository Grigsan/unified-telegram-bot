#!/usr/bin/env python3
"""
Мультипоиск через несколько бесплатных поисковиков
Без регистрации и API ключей
"""

import requests
import json
import time
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)

class MultiSearch:
    """Класс для поиска через несколько поисковиков одновременно"""
    
    def __init__(self):
        self.search_engines = {
            'duckduckgo': self.search_duckduckgo,
            'mojeek': self.search_mojeek,
            'metager': self.search_metager,
            'brave': self.search_brave,
        }
    
    def search_duckduckgo(self, query: str, max_results: int = 3) -> List[Dict]:
        """Поиск через DuckDuckGo"""
        try:
            from duckduckgo_search import DDGS
            results = []
            with DDGS() as ddgs:
                # Новостной поиск
                try:
                    news_results = list(ddgs.news(query, max_results=max_results))
                    for result in news_results:
                        results.append({
                            'title': result.get('title', ''),
                            'body': result.get('body', result.get('excerpt', '')),
                            'url': result.get('url', ''),
                            'source': 'DuckDuckGo News',
                            'date': result.get('date', '')
                        })
                except:
                    pass
                
                # Обычный поиск
                if len(results) < max_results:
                    text_results = list(ddgs.text(query, max_results=max_results))
                    for result in text_results:
                        results.append({
                            'title': result.get('title', ''),
                            'body': result.get('body', result.get('snippet', '')),
                            'url': result.get('href', ''),
                            'source': 'DuckDuckGo',
                            'date': ''
                        })
            
            logger.info(f"DuckDuckGo вернул {len(results)} результатов")
            return results[:max_results]
        except Exception as e:
            logger.error(f"Ошибка DuckDuckGo: {e}")
            return []
    
    def search_mojeek(self, query: str, max_results: int = 3) -> List[Dict]:
        """Поиск через Mojeek API"""
        try:
            # Mojeek API endpoint
            url = "https://api.mojeek.com/search"
            params = {
                'q': query,
                'fmt': 'json',
                'count': max_results
            }
            
            response = requests.get(url, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                results = []
                
                if 'results' in data:
                    for result in data['results']:
                        results.append({
                            'title': result.get('title', ''),
                            'body': result.get('desc', ''),
                            'url': result.get('url', ''),
                            'source': 'Mojeek',
                            'date': ''
                        })
                
                logger.info(f"Mojeek вернул {len(results)} результатов")
                return results
            else:
                logger.warning(f"Mojeek API ошибка: {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Ошибка Mojeek: {e}")
            return []
    
    def search_metager(self, query: str, max_results: int = 3) -> List[Dict]:
        """Поиск через MetaGer API"""
        try:
            # MetaGer API endpoint
            url = "https://metager.org/meta/meta.ger3"
            params = {
                'eingabe': query,
                'focus': 'web',
                'encoding': 'utf8',
                'lang': 'all',
                'num': max_results
            }
            
            response = requests.get(url, params=params, timeout=5)
            if response.status_code == 200:
                # MetaGer возвращает HTML, нужно парсить
                # Это упрощенная версия
                results = []
                logger.info(f"MetaGer запрос выполнен")
                return results
            else:
                logger.warning(f"MetaGer API ошибка: {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Ошибка MetaGer: {e}")
            return []
    
    def search_brave(self, query: str, max_results: int = 3) -> List[Dict]:
        """Поиск через Brave Search API"""
        try:
            # Brave Search API (требует API ключ, но есть бесплатный лимит)
            # Пока оставляем заглушку
            results = []
            logger.info(f"Brave Search пока не реализован")
            return results
        except Exception as e:
            logger.error(f"Ошибка Brave: {e}")
            return []
    
    def search_all(self, query: str, max_results: int = 3) -> str:
        """Поиск через все доступные поисковики"""
        all_results = []
        
        # Запускаем поиск параллельно
        for engine_name, search_func in self.search_engines.items():
            try:
                results = search_func(query, max_results)
                all_results.extend(results)
                time.sleep(0.1)  # Небольшая задержка между запросами
            except Exception as e:
                logger.error(f"Ошибка в {engine_name}: {e}")
        
        # Убираем дубликаты по URL
        unique_results = []
        seen_urls = set()
        
        for result in all_results:
            url = result.get('url', '')
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_results.append(result)
        
        # Формируем итоговый текст
        if unique_results:
            context = "\n🔍 РЕЗУЛЬТАТЫ ПОИСКА:\n"
            
            for i, result in enumerate(unique_results[:max_results], 1):
                title = result.get('title', 'Без названия')
                body = result.get('body', '')
                url = result.get('url', '')
                source = result.get('source', 'Неизвестно')
                date = result.get('date', '')
                
                context += f"\n{i}. **{title}**"
                if date:
                    context += f" ({date})"
                context += f" - {source}\n"
                
                if body:
                    body_text = body[:300] + "..." if len(body) > 300 else body
                    context += f"   {body_text}\n"
                
                if url:
                    context += f"   🔗 {url}\n"
            
            context += "\n⚠️ ВАЖНО: Используй ЭТУ информацию для ответа!\n"
            logger.info(f"Мультипоиск вернул {len(unique_results)} уникальных результатов")
            return context
        else:
            logger.warning("Мультипоиск не вернул результатов")
            return ""

# Функция для интеграции в основной бот
def search_web_multi(query: str, max_results: int = 3) -> str:
    """Мультипоиск для интеграции в unified_bot.py"""
    searcher = MultiSearch()
    return searcher.search_all(query, max_results)

if __name__ == "__main__":
    # Тестирование
    searcher = MultiSearch()
    results = searcher.search_all("новости 2025", 3)
    print(results)
