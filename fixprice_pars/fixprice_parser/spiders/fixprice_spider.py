from datetime import datetime

import scrapy
import time
import random
from urllib.parse import urljoin
from fixprice_parser.items import ProductItem
from scrapy_playwright.page import PageMethod


class ProductsSpider(scrapy.Spider):
    name = 'products'
    allowed_domains = ['fix-price.com']
    custom_settings = {
        'PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT': 180000,
        'DOWNLOAD_DELAY': random.uniform(3, 7),
        'CONCURRENT_REQUESTS': 1,
        'PLAYWRIGHT_LAUNCH_OPTIONS': {
            'headless': True,
            'timeout': 180000,
            'args': [
                '--disable-blink-features=AutomationControlled',
                '--disable-web-security',
                '--disable-extensions',
                '--disable-popup-blocking',
                '--disable-notifications',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                f'--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{random.randint(100, 115)}.0.0.0 Safari/537.36'
            ],
        },
        'PLAYWRIGHT_CONTEXTS': {
            'default': {
                'viewport': {'width': 1920, 'height': 1080},
                'ignore_https_errors': True,
                'java_script_enabled': True,
                'locale': 'ru-RU',
                'timezone_id': 'Europe/Moscow',
            }
        }
    }

    def start_requests(self):
        urls = [
            'https://fix-price.com/catalog/kosmetika-i-gigiena/ukhod-za-polostyu-rta',
        ]
        for url in urls:
            yield scrapy.Request(
                url,
                cookies={'selectedCity': 'Екатеринбург'},
                callback=self.parse_category,
                meta={
                    'playwright': True,
                    'playwright_include_page': True,
                    'playwright_page_methods': [
                        PageMethod('wait_for_load_state', 'networkidle', timeout=180000),
                        PageMethod('evaluate', '''() => {
                            window.scrollBy(0, 500);
                            return true;
                        }'''),
                        PageMethod('wait_for_timeout', random.randint(2000, 5000)),
                    ],
                    'playwright_context': 'default',
                }
            )

    async def parse_category(self, response):
        page = response.meta['playwright_page']

        try:
            product_data = await page.evaluate('''() => {
                const items = [];
                document.querySelectorAll('div.product').forEach(product => {
                    const link = product.querySelector('a.title');
                    const currentPriceEl = product.querySelector('.special-price');
                    const originalPriceEl = product.querySelector('.regular-price.old-price');
                    const brand = product.querySelector('a.title')?.innerText.split(',')[1]?.trim();
                    const images = Array.from(product.querySelectorAll('.swiper-slide img')).map(img => 
                        img.src || img.getAttribute('data-src')
                    ).filter(Boolean);
                    const sticker = product.querySelector('.sticker')?.innerText.trim();

                    if (link) {
                        items.push({
                            url: link.href,
                            full_title: link.innerText.trim(),
                            current_price: currentPriceEl?.innerText.trim(),
                            original_price: originalPriceEl?.innerText.trim(),
                            brand: brand,
                            images: images,
                            marketing_tags: sticker ? [sticker] : [],
                            in_stock: true, // По умолчанию, можно уточнить по наличию кнопки "В корзину"
                            // Другие данные можно добавить здесь
                        });
                    }
                });
                return items;
            }''')

            if not product_data:
                self.logger.warning(f"No products found at {response.url}")
                await page.screenshot(path='debug_no_products.png', full_page=True)
                return

            for product in product_data:
                item = ProductItem()
                print(item)
                # Основные данные
                item['timestamp'] = datetime.now().timestamp()
                # item['RPC'] = product['id']  # Генерация уникального кода
                item['url'] = urljoin(response.url, product['url'])
                # Обработка названия и бренда
                title_parts = product['full_title'].split(',')
                item['title'] = title_parts[0].strip()
                if len(title_parts) > 1:
                    item['title'] += f", {title_parts[1].strip()}"  # Добавляем объем/количество

                item['brand'] = product.get('brand', '')
                item['marketing_tags'] = product.get('marketing_tags', [])

                # Данные о цене
                current_price = float(product['current_price'].replace(' ₽', '').replace(',', '.')) if product[
                    'current_price'] else 0.0
                original_price = float(product['original_price'].replace(' ₽', '').replace(',', '.')) if product.get(
                    'original_price') else current_price

                sale_tag = ''
                if original_price > current_price:
                    discount = round((original_price - current_price) / original_price * 100)
                    sale_tag = f'Скидка {discount}%'

                item['price_data'] = {
                    'current': current_price,
                    'original': original_price,
                    'sale_tag': sale_tag
                }

                # Данные о наличии
                item['stock'] = {
                    'in_stock': product.get('in_stock', False),
                    'count': 0  # Можно попробовать получить количество из интерфейса
                }

                # Изображения
                item['assets'] = {
                    'main_image': product['images'][0] if product.get('images') else '',
                    'set_images': product.get('images', []),
                    'view360': [],
                    'video': []
                }

                # Метаданные и характеристики
                item['metadata'] = {
                    '__description': '',  # Нужно получить со страницы товара
                    'Вес/Объем': title_parts[-1].strip() if len(title_parts) > 1 else '',
                    # Другие характеристики можно добавить
                }

                item['variants'] = 0  # Можно определить по наличию вариантов

                yield item
                await page.wait_for_timeout(random.randint(1000, 3000))

            # Код для обработки пагинации
            has_next_page = await page.evaluate('''() => {
                const nextBtn = document.querySelector('a.pagination__item--arrow_right');
                return nextBtn !== null;
            }''')

            if has_next_page:
                next_page_url = await page.evaluate('''() => {
                    const nextBtn = document.querySelector('a.pagination__item--arrow_right');
                    return nextBtn ? nextBtn.href : null;
                }''')

                if next_page_url:
                    yield scrapy.Request(
                        urljoin(response.url, next_page_url),
                        callback=self.parse_category,
                        meta={
                            'playwright': True,
                            'playwright_include_page': True,
                            'playwright_page_methods': [
                                PageMethod('wait_for_load_state', 'networkidle', timeout=180000),
                            ],
                        }
                    )
        except Exception as e:
            self.logger.error(f"Error parsing category: {str(e)}")
            await page.screenshot(path='error_screenshot.png', full_page=True)
        finally:
            await page.close()

    async def parse_product(self, response):
        pass
