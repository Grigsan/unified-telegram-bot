#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSS новостной парсер - простой и надёжный
Берёт свежие новости из РИА, ТАСС и других RSS-лент
"""

import logging
from datetime import datetime
from typing import List, Dict
import requests
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

RSS_FEEDS = {
    'ria': 'https://ria.ru/export/rss2/archive/index.xml',
    'tass': 'https://tass.ru/rss/v2.xml',
    'interfax': 'https://www.interfax.ru/rss.asp',
}

def fetch_rss_news(max_items: int = 5) -> List[Dict[str, str]]:
    """Получает новости из RSS-лент"""
    all_news = []
    
    for source_name, feed_url in RSS_FEEDS.items():
        try:
            logger.info(f"Запрос RSS от {source_name}: {feed_url}")
            response = requests.get(feed_url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            
            if response.status_code != 200:
                logger.warning(f"{source_name} вернул {response.status_code}")
                continue
            
            # Парсим XML
            root = ET.fromstring(response.content)
            
            # RSS 2.0 формат
            items = root.findall('.//item')[:max_items]
            
            for item in items:
                title_el = item.find('title')
                link_el = item.find('link')
                desc_el = item.find('description')
                date_el = item.find('pubDate')
                
                title = title_el.text if title_el is not None and title_el.text else "Без заголовка"
                link = link_el.text if link_el is not None and link_el.text else ""
                desc = desc_el.text if desc_el is not None and desc_el.text else ""
                pub_date = date_el.text if date_el is not None and date_el.text else ""
                
                # Убираем HTML теги из описания
                if desc:
                    import re
                    desc = re.sub(r'<[^>]+>', '', desc).strip()
                
                all_news.append({
                    'title': title,
                    'description': desc[:300],  # Ограничиваем длину
                    'link': link,
                    'source': source_name.upper(),
                    'date': pub_date
                })
                
            logger.info(f"Получено {len(items)} новостей от {source_name}")
                
        except Exception as e:
            logger.error(f"Ошибка при получении RSS от {source_name}: {e}")
            continue
    
    return all_news[:max_items * 2]  # Возвращаем топ новостей


def get_news_context(query: str = "", max_items: int = 5) -> str:
    """Формирует текстовый контекст из новостей"""
    news = fetch_rss_news(max_items)
    
    if not news:
        logger.warning("RSS ленты не вернули новостей")
        return ""
    
    context_lines = [f"\n📰 СВЕЖИЕ НОВОСТИ ({datetime.now().strftime('%d.%m.%Y %H:%M')}):\n"]
    
    for idx, item in enumerate(news, 1):
        context_lines.append(f"\n{idx}. **{item['title']}**")
        context_lines.append(f"   Источник: {item['source']}")
        if item['date']:
            context_lines.append(f"   Дата: {item['date']}")
        if item['description']:
            context_lines.append(f"   {item['description']}")
        if item['link']:
            context_lines.append(f"   🔗 {item['link']}")
    
    context_lines.append(f"\n⚠️ Актуальные новости на {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    
    result = "\n".join(context_lines)
    logger.info(f"Сформирован контекст из {len(news)} новостей, {len(result)} символов")
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    context = get_news_context(max_items=3)
    print(context or "Новости не найдены")

