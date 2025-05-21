import asyncio
import logging
import os
import random
import re
from typing import Any

from bs4 import BeautifulSoup, Tag
from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from playwright.async_api import Error as PlaywrightError

from core.protocol_definitions import (
    ScrapedListingData,
    ScrapedListingsData,
    ScrapeListingsParams,
    ToolRequest,
    ToolResponse,
)
from tools.base_tool import BaseTool

DEFAULT_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
COMMON_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
]


class ChronoScraperTool(BaseTool):
    """Tool for scraping listings from Chrono24"""

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__("ChronoScraperTool", config)
        self.base_url = self.config.get("base_url", "https://www.chrono24.com")
        self.search_path = self.config.get("default_search_path", "/search/index.htm")
        self.request_delay_seconds = float(self.config.get("request_delay_seconds", 3.0))
        self.max_retries_per_request = int(self.config.get("max_retries_per_request", 3))
        self.user_agents = self.config.get("user_agents", [COMMON_USER_AGENTS])
        if not isinstance(self.user_agents, list) or not self.user_agents:
            self.user_agents = [COMMON_USER_AGENTS]

        self.known_brands = self.config.get("known_brands").split(",")
        self.known_brands = {b.strip() for b in self.known_brands if b.strip()}

        self.logger.info(
            f"ChronoScraperTool initialized. Base URL: {self.base_url}, "
            f"Delay: {self.request_delay_seconds}s, "
            f"Max retries: {self.max_retries_per_request}"
        )
        self.playwright_headless = self.config.get("playwright_headless", False)
        self.playwright_instance = None
        self.browser = None

    def _get_random_user_agent(self) -> str:
        """Selects a random user agent from the list of user agents"""
        return random.choice(self.user_agents)

    async def _get_browser(self) -> Browser:
        """Initializes a playwright browser instance"""
        if self.browser and self.browser.is_connected():
            return self.browser
        if not self.playwright_instance:
            self.playwright_instance = await async_playwright().start()
        try:
            self.browser = await self.playwright_instance.chromium.launch(headless=self.playwright_headless)
        except PlaywrightError as e:
            self.logger.error(f"Failed to launch playwright browser: {e}")
            if self.playwright_instance:
                await self.playwright_instance.stop()
                self.playwright_instance = None
            raise
        return self.browser

    async def _close_browser(self):
        """Closes the playwright browser instance"""
        if self.browser and self.browser.is_connected():
            await self.browser.close()
            self.browser = None
        if self.playwright_instance:
            await self.playwright_instance.stop()
            self.playwright_instance = None

        self.logger.info("Playwright browser instance and Playwright closed")

    def _get_request_headers(self, is_initial_visit: bool = False) -> dict[str, str]:
        """Constructs a dictionary of minimal HTTP headers that might be useful to explicitly
        set with Playwright's context.set_extra_http_headers(), if needed.
        Playwright's browser engine handles most headers automatically.
        """
        headers = {}
        accept_language = self.config.get("accept_language", "en-US,en;q=0.9")
        if accept_language:
            headers["Accept-Language"] = accept_language

        if not is_initial_visit:
            referer = self.config.get("referer_subsequent", self.base_url)
            if referer:
                headers["Referer"] = referer
        return {k: v for k, v in headers.items() if v is not None}

    async def _handle_popup(self, page: Page):
        """Handles a popup on the page"""
        popup_accept_selectors = [
            "dialog.gdpr-layer button.js-cookie-accept-all",
            "dialog.gdpr-layer button.btn-primary:has-text('OK')",
        ]
        popup_handled = False
        for selector in popup_accept_selectors:
            try:
                await page.locator(selector).click(timeout=3000)
                popup_handled = True
                await asyncio.sleep(random.uniform(0.5, 1.0))
                break
            except TimeoutError:
                self.logger.debug(f"Popup not found with selector: {selector}. Timed out")
            except PlaywrightError as e:
                self.logger.debug(f"Popup not found with selector: {selector}. Error: {e}")
        if not popup_handled:
            self.logger.warning("No popup accept button found. Proceeding with scrape.")

    async def _change_view_to_list(self, page: Page):
        """Changes the view to list"""
        view_changed_to_list = False
        try:
            await page.locator("a.result-view-switcher").click(timeout=3000)
            view_changed_to_list = True
            await asyncio.sleep(random.uniform(0.5, 1.0))
        except TimeoutError:
            self.logger.debug("View not changed to list. Timed out")
        except PlaywrightError as e:
            self.logger.debug(f"View not changed to list. Error: {e}")
        if not view_changed_to_list:
            self.logger.warning("View not changed to list. Proceeding with scrape.")

    async def _fetch_html(self, url: str, attempt: int) -> str | None:
        """Fetches the HTML content from a url with playwright."""
        browser = await self._get_browser()
        context: BrowserContext | None = None
        page: Page | None = None
        user_agent_override = random.choice(self.user_agents)
        self.logger.debug(
            f"Playwright Attempt {attempt}: Fetching URL: {url} with User-Agent: {user_agent_override if user_agent_override else 'Playwright Default'}"
        )

        current_delay = self.request_delay_seconds
        if attempt > 1:
            current_delay = self.request_delay_seconds * attempt
            self.logger.info(f"Retrying attempt {attempt}, waiting for {current_delay} seconds...")
        await asyncio.sleep(current_delay)

        try:
            context_options: dict[str, Any] = {}
            if user_agent_override:
                context_options["user_agent"] = user_agent_override
            accept_lang = self.config.get("accept_language", "en-US,en;q=0.9")
            if accept_lang:
                context_options["locale"] = accept_lang.split(",")[0]

            context = await browser.new_context(**context_options)
            page = await context.new_page()
            self.logger.info(f"Playwright navigating to {url}")
            response = await page.goto(
                url,
                timeout=self.config.get("default_request_timeout_seconds", 60) * 1000,
                wait_until="networkidle",
            )
            if response:
                await self._handle_popup(page)
                self.logger.debug(f"Playwright response status for {url}: {response.status}")
                if response.status != 200:
                    self.logger.warning(
                        f"Playwright navigation failed for {url}. Attempt {attempt}/{self.max_retries_per_request}"
                    )
                    if response.status in [403, 429] and attempt >= self.max_retries:
                        self.logger.error(
                            f"Playwright final attempt failed for {url} with critical HTTP error: {response.status}"
                        )
                    return None
                await self._change_view_to_list(page)
                html_content = await page.content()
                self.logger.debug(
                    f"Playwright successfully fetched URL: {url}, status: {response.status}, content length: {len(html_content)}"
                )
                return html_content
            else:
                self.logger.warning(f"Playwright navigation to {url} returned no response object")
                return None
        except PlaywrightError as e:
            self.logger.warning(
                f"Playwright error fetching {url}. Attempt {attempt}/{self.max_retries_per_request}: {e.message}"
            )
        except Exception as e:
            self.logger.exception(
                f"Unexpected error fetching {url}. Attempt {attempt}/{self.max_retries_per_request}: {e}"
            )
        finally:
            if page:
                await page.close()
            if context:
                await context.close()
        return None

    def _extract_text_from_element(self, element: Tag | None, selector: str, default: str | None = None) -> str | None:
        """Extracts text from BS4 element using a selector"""
        if not element:
            return default
        target = element.select_one(selector)
        return target.get_text(strip=True) if target else default

    def _extract_price_currency(self, price_text_raw: str | None) -> tuple[float | str | None, str | None]:
        """Extracts numerical price and currency symbol from a price string // fallback from JSON-LD"""
        if not price_text_raw:
            return None, None
        if price_text_raw.lower().strip() == "price on request":
            return "price on request", None
        price_value = None
        currency_symbol_extracted = None
        currency_match = re.search(r"([$€£¥₹]|[A-Z]{3})", price_text_raw)
        if currency_match:
            currency_symbol_extracted = currency_match.group(0)

        price_match = re.search(r"[\d, \.]+", price_text_raw)
        if price_match:
            cleaned_price_str = price_match.group(0).replace(",", "")
            try:
                price_value = float(cleaned_price_str)
            except ValueError:
                self.logger.warning(f"Could not parse price from {price_text_raw}")
        return price_value, currency_symbol_extracted

    def _parse_brand_model_from_title(self, line1: str | None, line2: str | None) -> tuple[str | None, str | None]:
        """Parses brand and model from line1 and line2"""
        brand = None
        model = None
        line1_stripped = line1.strip() if line1 else None
        line2_stripped = line2.strip() if line2 else None
        full_title_parts = []
        if line1_stripped:
            full_title_parts.append(line1_stripped)
        if line2_stripped:
            full_title_parts.append(line2_stripped)
        combined_full_title = " ".join(filter(None, full_title_parts))

        if line1_stripped:
            line1_lower = line1_stripped.lower()
            for known_brand in self.known_brands:
                if line1_lower.startswith(known_brand):
                    brand = line1_lower[: len(known_brand)]
                    model_candidate = line1_lower[len(known_brand) :].strip()
                    if model_candidate:
                        model = model_candidate
                    break

            # this is not an exact science but ill revisit later
            if not brand:
                if " " in line1_stripped:
                    parts = line1_stripped.split(" ", 1)
                    brand = parts[0]
                    if len(parts) > 1 and parts[1]:
                        model = parts[1].strip()
                elif line1_lower in self.known_brands:
                    brand = line1_stripped
                else:
                    model = line1_stripped

        if line2_stripped:
            if not model or (brand and model and brand.lower() == model.lower()):
                model = line2_stripped
            elif model and brand and not line1_lower.startswith(brand.lower() + " " + model.lower()):
                pass

        return brand, model, combined_full_title

    def _get_details_from_pairs(self, details_container: Tag | None, label_text: str) -> str | None:
        """Extracts a detail value based on its preceding label within a container
        assuming a structure like:
            <div class="w-50 row row-direct">
            <div class="col-xs-12">LABEL_TEXT:</div>
            <div class="col-xs-12 text-ellipsis"><strong>VALUE</strong></div>
            </div>
        """
        if not details_container:
            return None

        detail_pairs = details_container.select("div.w-50.row.row-direct")
        for pair in detail_pairs:
            label_div = pair.select_one("div.col-xs-12:not(.text-ellipsis)")
            if label_div and label_text.lower() in label_div.get_text(strip=True).lower():
                value_text = None
                value_strong = pair.select_one("div.col-xs-12.text-ellipsis strong")
                if value_strong:
                    value_text = value_strong.get_text(strip=True)
                else:
                    value_div = pair.select_one("div.col-xs-12.text-ellipsis")
                    if value_div:
                        value_text = value_div.get_text(strip=True)
                if value_text == "-":
                    self.logger.debug(f"Found placeholder '-' for label {label_text} returning None")
                    return None
                return value_text

        return None

    def _parse_direct_HTML_tag_listings(
        self, html_content: str, search_query_attributes: dict[str, Any]
    ) -> list[ScrapedListingData]:
        """Parses scraped listings from HTML content directly using HTML tags"""
        self.logger.debug(f"Parsing listings from HTML content (length: {len(html_content)}) chars.")
        soup = BeautifulSoup(html_content, "lxml")
        scraped_items: list[ScrapedListingData] = []

        listing_item_selector = "div.js-article-item-container"
        listing_elements = soup.select(listing_item_selector)
        self.logger.info(f"Found {len(listing_elements)} listing items in HTML")
        for elem_idx, elem in enumerate(listing_elements):
            try:
                # probably put these hardcoded tags in a config file later
                # abstract some stuff also
                link_element = elem.select_one("a.js-article-item.article-item")
                html_listing_url_relative = (
                    link_element["href"] if link_element and link_element.has_attr("href") else None
                )
                html_listing_url = (
                    f"{self.base_url}{html_listing_url_relative}"
                    if html_listing_url_relative and html_listing_url_relative.startswith("/")
                    else html_listing_url_relative
                )

                main_title_div = elem.select_one("div.text-sm.text-bold.text-ellipsis")
                main_title_html = main_title_div.get_text(strip=True) if main_title_div else None
                sub_title_div = elem.select_one("div.text-sm.text-ellipsis.m-b-sm-2")
                sub_title_html = sub_title_div.get_text(strip=True) if sub_title_div else None
                html_brand, html_model, html_full_title = self._parse_brand_model_from_title(
                    main_title_html, sub_title_html
                )

                price_container = elem.select_one("div.text-lg.text-sm-xlg.text-bold")
                price_text_raw_html = price_container.get_text(strip=True) if price_container else None
                html_price, html_currency = self._extract_price_currency(price_text_raw_html)

                details_container = elem.select_one("div.d-sm-flex.m-b-sm-3.flex-wrap")
                movement_str = self._get_details_from_pairs(details_container, "Movement")
                case_material_str = self._get_details_from_pairs(details_container, "Case material")
                year_str = self._get_details_from_pairs(details_container, "Year of production")
                condition_str = self._get_details_from_pairs(details_container, "Condition")
                location_str = self._get_details_from_pairs(details_container, "Location")
                reference_str = self._get_details_from_pairs(details_container, "Reference number")
                condition_str = self._get_details_from_pairs(details_container, "Condition")

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
                        reference_number=reference_str,
                    )
                    scraped_items.append(listing)
                else:
                    self.logger.warning(
                        f"Skipped element {elem_idx + 1} due to missing required fields. URL={html_listing_url}, title={html_full_title}, price={html_price}"
                    )
            except Exception as e:
                self.logger.exception(
                    f"Error parsing listing {elem_idx + 1}: {e}.Element HTML (first 300 chars): {str(elem)[:300]}"
                )
        if scraped_items:
            self.logger.info(f"Successfully parsed {len(scraped_items)} listings from HTML")
        else:
            self.logger.warning("No listings parsed from HTML")
        return scraped_items

    def _parse_listings_from_html(
        self, html_content: str, search_query_attributes: dict[str, Any]
    ) -> list[ScrapedListingData]:
        """Parses scraped listings from HTML content"""
        self.logger.debug(f"Parsing listings from HTML content (length: {len(html_content)}) chars.")
        scraped_listings: list[ScrapedListingsData] = self._parse_direct_HTML_tag_listings(
            html_content, search_query_attributes
        )
        return scraped_listings

    # TODO: need to deal with pagination later
    async def _handle_scrape_listings(
        self, params: ScrapeListingsParams, original_input_attributes: dict[str, Any]
    ) -> ScrapedListingsData:
        """Handles the scrape_listings action using playwright"""
        self.logger.info(f"Starting scrape_listings action with params: {params}")
        search_url = (
            f"{self.base_url}{self.search_path}?dosearch=true&query={params.search_query_string.replace(' ', '+')}"
        )
        html_content = None
        try:
            for attempt in range(1, self.max_retries_per_request + 1):
                html_content = await self._fetch_html(search_url, attempt)
                if html_content:
                    break
                elif attempt < self.max_retries_per_request:
                    self.logger.info(
                        f"Retrying fetch for {search_url} (Attempt {attempt + 1}/{self.max_retries_per_request}) after delay."
                    )
                else:
                    self.logger.error(f"All {self.max_retries_per_request} retries failed for search URL: {search_url}")
        except Exception as e:
            self.logger.exception(f"Error fetching HTML content from {search_url}: {e}")

        if not html_content:
            raise RuntimeError(
                f"Failed to fetch HTML content from {search_url} after {self.max_retries_per_request} attempts"
            )
        loop = asyncio.get_event_loop()
        all_parsed_listings = await loop.run_in_executor(
            None, self._parse_listings_from_html, html_content, original_input_attributes
        )
        return ScrapedListingsData(scraped_items=all_parsed_listings)

    async def execute(self, request: ToolRequest) -> ToolResponse:
        """Executes an action requested for the ChronoScraperTool"""
        self.logger.info(f"Received request for action: {request.action} with params: {request.params}")
        action_handler = None
        if request.action == "scrape_listings":
            action_handler = self._handle_scrape_listings
        else:
            return self._create_error_response(
                f"Unsupported action: {request.action} for tool: {self.tool_name}", request_params=request.params
            )
        if action_handler:
            try:
                if request.action == "scrape_listings":
                    input_attributes = request.context.get("original_input_attributes") if request.context else {}
                    if not input_attributes and request.params.get("search_query_string"):
                        self.logger.warning(
                            "original_input_attributes not found in request context for scrape_listings, scraped items might lack full input context."
                        )
                    params_model = ScrapeListingsParams(**request.params)
                    response = await action_handler(params_model, input_attributes)
                    return self._create_success_response(data=response.model_dump(), request_params=request.params)
            except Exception as e:
                self.logger.exception(f"Error executing action {request.action}: {e}")
                return self._create_error_response(
                    f"Error executing action {request.action}: {e}", request_params=request.params
                )
        return self._create_error_response(
            f"Action handler not found for action: {request.action} for tool: {self.tool_name}",
            request_params=request.params,
        )


if __name__ == "__main__":

    async def test_chrono_scraper_tool():
        from core.config_loader import get_setting
        from core.config_loader import load_configurations as load_app_configurations
        from core.logging_config import setup_logging

        load_app_configurations()
        log_level_str = get_setting("General", "log_level", default="DEBUG").upper()
        numeric_log_level = getattr(logging, log_level_str, logging.DEBUG)
        setup_logging(log_level=numeric_log_level)

        logger = logging.getLogger("TestChronoScraperTool")

        scraper_config_data = {
            "base_url": os.getenv("CHRONO24_BASE_URL", "https://www.chrono24.com"),
            "default_search_path": get_setting("ChronoScraperTool", "default_search_path"),
            "request_delay_seconds": get_setting(
                "ChronoScraperTool", "request_delay_seconds", is_float=True, default=1.0
            ),
            "max_retries_per_request": get_setting(
                "ChronoScraperTool", "max_retries_per_request", is_int=True, default=1
            ),
            "user_agents": COMMON_USER_AGENTS,
            "known_brands": get_setting(
                "ChronoScraperTool", "known_brands", default="rolex,cartier,patek philippe,omega"
            ),
            "playwright_headless": get_setting("ChronoScraperTool", "playwright_headless", default=True, is_bool=True),
            "default_request_timeout_seconds": get_setting(
                "General", "default_request_timeout_seconds", default=60, is_int=True
            ),
            # Only include header configs if _get_extra_headers_for_playwright explicitly uses them
            "header_accept_language": get_setting(
                "Headers", "accept_language", default="en-US,en;q=0.9"
            ),  # For context locale
            "header_referer_subsequent": get_setting(
                "Headers", "referer_subsequent", default="https://www.chrono24.com/"
            ),  # If used by _get_extra_headers_for_playwright
        }

        scraper_tool = ChronoScraperTool(config=scraper_config_data)

        try:
            test_search_query = "Cartier crash"
            test_input_attrs = {"Brand": "Cartier", "Model": "crash", "Keywords": "Gold"}

            scrape_params = ScrapeListingsParams(search_query_string=test_search_query)

            scrape_request = ToolRequest(
                tool_name="ChronoScraperTool",
                action="scrape_listings",
                params=scrape_params.model_dump(),
                context={"original_input_attributes": test_input_attrs},
            )

            logger.info(f"Sending request to ChronoScraperTool: {scrape_request.model_dump_json(indent=2)}")
            response = await scraper_tool.execute(scrape_request)

            logger.info("Received response from ChronoScraperTool:")
            print(response.model_dump_json(indent=2))

            if response.status == "success" and response.data:
                parsed_data = ScrapedListingsData(**response.data)
                logger.info(f"Successfully scraped {len(parsed_data.scraped_items)} items for '{test_search_query}'.")
                if parsed_data.scraped_items:
                    for i, item_data in enumerate(parsed_data.scraped_items[:6]):
                        logger.info(f"Item {i + 1}: {item_data.model_dump_json(indent=2)}")
        finally:
            await scraper_tool._close_browser()

    if __name__ == "__main__":
        if not os.path.exists("config"):
            os.makedirs("config")
        if not os.path.exists("config/main_config.ini"):
            with open("config/main_config.ini", "w") as f:
                f.write("[General]\nlog_level=DEBUG\ndefault_request_timeout_seconds=60\n")
                f.write(
                    "[ChronoScraperTool]\nbase_url=https://www.chrono24.com\ndefault_search_path=/search/index.htm\nrequest_delay_seconds=1.0\nmax_retries_per_request=1\nknown_brands=rolex,cartier,patek philippe,omega\nplaywright_headless=True\n"
                )
                # Only include header configs that _get_extra_headers_for_playwright or context setup might use
                f.write("[Headers]\naccept_language=en-US,en;q=0.9\nreferer_subsequent=https://www.chrono24.com/\n")
            print(
                "WARNING: Created a dummy config/main_config.ini for test. Please ensure your actual files are configured."
            )

        asyncio.run(test_chrono_scraper_tool())
