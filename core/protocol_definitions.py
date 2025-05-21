from typing import Any

from pydantic import BaseModel, Field


class ToolRequest(BaseModel):
    "Base class for all tool requests."

    tool_name: str = Field(..., description="The name of the tool to execute.")
    action: str = Field(..., description="The specific action to perform.")
    params: dict[str, Any] = Field(default_factory=dict, description="Parameters for the action.")
    context: dict[str, Any] | None = Field(None, description="Optional context for the action.")


class ToolResponse(BaseModel):
    "Base class for all tool responses."

    status: str = Field(..., description="Status of the tool action (e.g., success, error)")
    data: dict[str, Any] | None = Field(None, description="Data payload if the action was successful.")
    error_message: str | None = Field(None, description="Error message if the action failed.")


class ReadInputSKUsParams(BaseModel):
    "Parameters for the read_input_skus tool."

    sheet_name: str
    worksheet_name: str


# might need to change some things as ref number and movement arent always present
class InputSKUData(BaseModel):
    "Single row of SKU data."

    Brand: str
    Model: str
    ReferenceNumber: str | None = None
    Movement: str
    Case: str
    DialColor: str | None = None
    Dial: str | None = None
    Bracelet: str | None = None
    Bezel: str | None = None
    ListPrice: float | str | None = None
    ExcludeKeywords: str | None = None


class ReadInputSKUsData(BaseModel):
    "Data returned by read_input_skus tool."

    skus: list[InputSKUData]


class ScrapeListingsParams(BaseModel):
    "Parameters for the 'scrape_listings' action of ChronoScraperTool."

    search_query_string: str


class ScrapedListingData(BaseModel):
    "Single scraped listing data sans ID."

    input_sku_attributes: dict[str, Any] | None = None
    listing_url: str
    brand: str | None = None
    model: str | None = None
    case_material: str | None = None
    reference_number: str | None = None
    dial: str | None = None
    dial_color: str | None = None
    movement: str | None = None
    listing_title: str | None = None
    price: float | str | None = None
    currency: str | None = None
    condition: str | None = None
    production_year: int | None = None
    location: str | None = None
    seller_name: str | None = None


class ScrapedListingsData(BaseModel):
    "Data returned by scrape_listings action."

    scraped_items: list[ScrapedListingData]


class SaveListingParams(BaseModel):
    "Parameters for save_listings action."

    listings_data: list[ScrapedListingData]


class SaveListingsData(BaseModel):
    listings_saved_count: int
    listings_not_saved_count: int


class QueryLatestListingsParams(BaseModel):
    "Parameters for query_latest_filtered_listings action."

    input_sku_attributes_json: str
    target_condition: str | None = None
    target_year_min: int | None = None
    target_year_max: int | None = None
    target_location: str | None = None
    exclude_keywords: list[str] | None = None
    limit: int = 50


class QueryLatestListingsData(BaseModel):
    "Data returned by query_latest_filtered_listings action."

    listings: list[ScrapedListingData]


class CalculateMarketAverageParams(BaseModel):
    "Parameters for calculate_market_average action."

    listings_data: list[ScrapedListingData]
    your_list_price: float | str


class MarketAverageData(BaseModel):
    "Data returned by calculate_market_average"

    input_sku_attributes_json: dict[str, Any] | None = None
    your_list_price: float
    calculated_average_market_price: float | None = None
    delta_percentage: float | None = None
    bottom_n_listings_details: list[dict[str, Any]] | None = None
    bottom_5_listings_prices: list[float] | None = None
    listings_considered_count: int
