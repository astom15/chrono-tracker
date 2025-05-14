import asyncio
import re
import aiohttp
import json
from bs4 import BeautifulSoup, Tag
from typing import Dict, Any, Optional, List
import logging
import random

from tools.base_tool import BaseTool
from core.protocol_definitions import ToolRequest, ToolResponse, ScrapeListingsParams, ScrapedListingsData, ScrapedListingData


DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36"

class ChronoScraperTool(BaseTool):
    "Tool for scraping listings from Chrono24"
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__("ChronoScraperTool", config)
        self.base_url = self.config.get("base_url", "https://www.chrono24.com")
        self.search_path = self.config.get("default_search_path", "/search/index.htm")
        self.request_delay_seconds = float(self.config.get("request_delay_seconds", 3.0))
        self.max_retries_per_request = int(self.config.get("max_retries_per_request", 3))
        self.user_agents = self.config.get("user_agents", [DEFAULT_USER_AGENT])
        if not isinstance(self.user_agents,list) or not self.user_agents:
            self.user_agents = [DEFAULT_USER_AGENT]

        self.known_brands = self.config.get('known_brands').split(',')
        self.known_brands = set(b.strip() for b in self.known_brands if b.strip())

        self.logger.info(f"ChronoScraperTool initialized. Base URL: {self.base_url}, "
                         f"Delay: {self.request_delay_seconds}s, "
                         f"Max retries: {self.max_retries_per_request}")

    def _get_random_user_agent(self) -> str:
        "selects a random user agent from the list of user agents"
        return random.choice(self.user_agents)
    
    async def _fetch_html(self, session: aiohttp.ClientSession, url: str, attempt: int) -> Optional[str]:
        "Fetches the HTML content of a given URL with retries and delay."
        headers = {"User-Agent": self._get_random_user_agent()}
        self.logger.debug(f"Attempt {attempt}. Fetching URL: {url} with user agent: {headers['User-Agent']}")
        await asyncio.sleep(self.request_delay_seconds)

        try: 
            async with session.get(url, headers=headers, timeout=self.config.get('default_request_timeout_seconds', 30)) as response:
                response.raise_for_status()
                html_content = await response.text()
                self.logger.debug(f"Successfully fetched {url}, response: {response.status}")
                return html_content
        except aiohttp.ClientResponseError as e:
            self.logger.warning(f"HTTP error fetching {url}. Attempt {attempt/{self.max_retries_per_request}}: {e.status} {e.message}")
            if e.status in [403,404,429]:
                if attempt >= self.max_retries_per_request:
                    self.logger.error(f"Final attempt failed for {url} with error: {e.status}")
                return None
        except asyncio.TimeoutError:
            self.logger.warning(f"Timeout fetching {url} on attempt {attempt}/{self.max_retries_per_request}")
        except aiohttp.ClientError as e:
            self.logger.warning(f"Client error fetching {url}. Attempt {attempt}/{self.max_retries_per_request}: {e}")
        
        return None

    def _extract_text_from_element(self, element: Optional[Tag], selector: str, default: Optional[str] = None) -> Optional[str]:
        "Extracts text from BS4 element using a selector"
        if not element: 
            return default
        target = element.select_one(selector)
        return target.get_text(strip=True) if target else default

    def _extract_price_currency(self, price_text_raw: Optional[str]) -> tuple[Optional[float], Optional[str]]:
        "Extracts numerical price and currency symbol from a price string // fallback from JSON-LD"
        if not price_text_raw:
            return None, None
        price_value = None
        currency_symbol_extracted = None
        currency_match = re.search(r'[$€£¥₹]|[A-Z]{3})', price_text_raw)
        if currency_match:
            currency_symbol_extracted = currency_match.group(0)
        
        price_match = re.search(r'[\d, \.]+', price_text_raw)
        if price_match:
            cleaned_price_str = price_match.group(0).replace(',', '')
            try:
                price_value = float(cleaned_price_str)
            except ValueError:
                self.logger.warning(f"Could not parse price from {price_text_raw}")
        return price_value, currency_symbol_extracted

    def _parse_brand_model_from_title(self, line1: Optional[str], line2: Optional[str]) -> tuple[Optional[str], Optional[str]]:
        "Parses brand and model from line1 and line2"
        brand = None
        model = None
        line1_stripped = line1.strip() if line1 else None
        line2_stripped = line2.strip() if line2 else None
        full_title_parts = []
        if line1_stripped: full_title_parts.append(line1_stripped)  
        if line2_stripped: full_title_parts.append(line2_stripped)
        combined_full_title = " ".join(filter(None, full_title_parts))

        if line1_stripped:
            line1_lower = line1_stripped.lower()
            for known_brand in self.known_brands:
                if (line1_lower.startswith(known_brand)):
                    brand = line1_lower[:len(known_brand)]
                    model_candidate = line1_lower[len(known_brand):].strip()
                    if model_candidate:
                        model = model_candidate
                    break

            # this is not an exact science but ill revisit later
            if not brand: 
                if ' ' in line1_stripped:
                    parts = line1_stripped.split(' ', 1)
                    brand = parts[0]
                    if len(parts) > 1 and parts[1]: 
                        model = parts[1].strip()
                else: 
                    if line1_lower in self.known_brands:
                        brand = line1_stripped
                    else:
                        model = line1_stripped 
        
        if line2_stripped:
            if not model or (brand and model and brand.lower() == model.lower()):
                model = line2_stripped 
            elif model and brand and not line1_lower.startswith(brand.lower() + " " + model.lower()):
                pass 

        return brand, model, combined_full_title

    def _get_details_from_pairs(self, details_container: Optional[Tag], label_text: str) -> Optional[str]:
        """
        Extracts a detail value based on its preceding label within a container
        assuming a structure like:
        <div class="w-50 row row-direct">
           <div class="col-xs-12">LABEL_TEXT:</div>
           <div class="col-xs-12 text-ellipsis"><strong>VALUE</strong></div>
        </div>
        """
        if not details_container:
            return None

        detail_pairs = details_container.select('div.w-50.row.row-direct')
        for pair in detail_pairs:
            label_div = pair.select_one('div.col-xs-12:not(.text-ellipsis)')
            if label_div and label_text.lower() in label_div.get_text(strip=True).lower():
                value_div = pair.select_one('div.col-xs-12.text-ellipsis strong')
                if value_div:
                    return value_div.get_text(strip=True)
                value_div_no_strong = pair.select_one('div.col-xs-12.text-ellipsis')
                if value_div_no_strong:
                    return value_div_no_strong.get_text(strip=True)
        return None


    # it seems the json+ld of chrono isnt super useful cause they concatenate the whole title in the name so we'll just use direct html tag scraping
    # def _parse_json_ld_listings(self, html_content: str, search_query_attributes: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    #     "Parses scraped listings from HTML content first searching JSON-LD"
    #     self.logger.debug(f"Parsing listings from HTML content (length: {len(html_content)}) chars.")
    #     soup = BeautifulSoup(html_content, 'lxml')
        
    #     json_ld_offer_map: Dict[str, List[Dict[str, Any]]] = {}
    #     currency: Optional[str] = None

    #     json_ld_scripts = soup.find_all('script', type='application/ld+json')
    #     for script_tag in json_ld_scripts:
    #         try:
    #             data = json.loads(script_tag.string)
    #             if isinstance(data, dict) and data.get('@context') == 'http://schema.org':
    #                 graph_items = data.get('@graph', [])
    #                 if not isinstance(graph_items, list):
    #                     graph_items = [graph_items] if graph_items else []

    #                 for graph_item in graph_items:
    #                     if isinstance(graph_item, dict) and graph_item.get('@type') == ' AggregateOffer':
    #                         currency = graph_item.get('priceCurrency')
    #                         offers_in_aggregate = graph_item.get('offers',[])
    #                         if isinstance(offers_in_aggregate, list):
    #                             for offer_item in offers_in_aggregate:
    #                                 if isinstance(offer_item, dict) and offer_item.get('@type') == 'Offer':
    #                                     offer_url = offer_item.get('url')
    #                                     if offer_url:
    #                                         offer_item_copy = offer_item.copy()
    #                                         offer_item_copy['currency'] = currency
    #                                         json_ld_offer_map[offer_url] = offer_item_copy
    #                             if offers_in_aggregate:
    #                                 break
    #         except json.JSONDecodeError:
    #             self.logger.debug("Could not decode JSON-LD content.")
    #         except Exception as e:
    #             self.logger.warning(f"Error processing JSON-LD script: {e}")

    #         if json_ld_offer_map:
    #             self.logger.info(f"Pre-parsed {len(json_ld_offer_map)} offers in JSON-LD")
        
    #     return json_ld_offer_map
        
        

    def _parse_direct_HTML_tag_listings(self, html_content: str, search_query_attributes: Dict[str, Any]) -> List[ScrapedListingData]:
        "Parses scraped listings from HTML content directly using HTML tags"
        self.logger.debug(f"Parsing listings from HTML content (length: {len(html_content)}) chars.")
        soup = BeautifulSoup(html_content, 'lxml')
        scraped_items: List[ScrapedListingData] = []

        listing_item_selector = 'div.js-article-item-container'
        listing_elements = soup.select(listing_item_selector)
        self.logger.info(f"Found {len(listing_elements)} listing items in HTML")
        for elem_idx, elem in enumerate(listing_elements):
            try:
                # probably put these hardcoded tags in a config file later
                link_element = elem.select_one('a.js-article-item.article-item')
                html_listing_url_relative = link_element['href'] if link_element and link_element.has_attr('href') else None
                html_listing_url = f"{self.base_url}{html_listing_url_relative}" if html_listing_url_relative and html_listing_url_relative.startswith('/') else html_listing_url_relative
                main_title_div = elem.select_one('div.text-sm.text-sm-xlg.text-bold.text-ellipsis')
                main_title_html = main_title_div.get_text(strip=True) if main_title_div else None
                sub_title_div = elem.select_one('div.text-sm.text-sm-lg.text-ellipsis.p-r-5')
                sub_title_html = sub_title_div.get_text(strip=True) if sub_title_div else None
                html_brand, html_model, html_full_title = self._parse_brand_model_from_title(main_title_html, sub_title_html)

                price_container = elem.select_one('div.text-lg.text-sm-xlg.text-bold')
                price_text_raw_html = price_container.get_text(strip=True) if price_container else None
                html_price, html_currency = self._extract_price_currency(price_text_raw_html)

                details_container = elem.select_one('div.d-none.d-sm-flex.m-b-sm-3.flex-wrap')

                movement_str = self._get_details_from_pairs(details_container, 'Movement')
                case_material_str = self._get_detail_from_pairs(details_container, 'Case material')
                year_str = self._get_detail_from_pairs(details_container, 'Year of production')
                condition_str = self._get_detail_from_pairs(details_container, 'Condition')
                location_str = self._get_detail_from_pairs(details_container, 'Location')
                reference_str = self._get_detail_from_pairs(details_container, 'Reference number')
                condition = self._get_detail_from_pairs(details_container, 'Condition')
                
                if html_listing_url and html_full_title and html_price is not None:
                    listing = ScrapedListingData(
                        listing_url=html_listing_url,
                        listing_title=html_full_title,
                        brand=html_brand,
                        model=html_model,
                        price=html_price,
                        currency=html_currency,
                        movement=movement_str,
                        case_material=case_material_str,
                        year_of_production=year_str,
                        condition=condition_str,
                        location=location_str,
                        reference_number=reference_str
                    )
                    scraped_items.append(listing)
                else:
                    self.logger.warning(f"Skipped element {elem_idx + 1} due to missing required fields. URL={html_listing_url}, title={html_full_title}, price={html_price}")
            except Exception as e:
                self.logger.exception(f"Error parsing listing {elem_idx + 1}: {e}.Element HTML (first 300 chars): {str(elem)[:300]}")
        if scraped_items:
            self.logger.info(f"Successfully parsed {len(scraped_items)} listings from HTML")
        else:
            self.logger.warning("No listings parsed from HTML")
        return scraped_items
    
    def _parse_listings_from_html(self,html_content: str, search_query_attributes: Dict[str,Any]) -> List[ScrapedListingData]:
        scraped_listings: List[ScrapedListingData] = self._parse_direct_HTML_tag_listings(html_content, search_query_attributes)

