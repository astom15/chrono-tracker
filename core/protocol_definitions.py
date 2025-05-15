from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

class ToolRequest(BaseModel):
    "Base class for all tool requests."
    tool_name: str = Field(..., description="The name of the tool to execute.")
    action: str = Field(...,description="The specific action to perform.")
    params: Dict[str,Any] = Field(default_factory=dict, description="Parameters for the action.")
    context: Optional[Dict[str,Any]] = Field(None, description="Optional context for the action.")

class ToolResponse(BaseModel):
    "Base class for all tool responses."
    status: str = Field(...,description="Status of the tool action (e.g., success, error)")
    data: Optional[Dict[str,Any]] = Field(None, description="Data payload if the action was successful.")
    error_message: Optional[str] = Field(None, description="Error message if the action failed.")

class ReadInputSKUsParams(BaseModel):
    "Parameters for the read_input_skus tool."
    sheet_name: str
    worksheet_name: str

# might need to change some things as ref number and movement arent always present
class InputSKUData(BaseModel):
    "Single row of SKU data."
    Brand: str
    Model: str
    ReferenceNumber: Optional[str] = None
    Movement: str
    Case: str
    DialColor: Optional[str] = None
    Dial: Optional[str] = None
    Bracelet: Optional[str] = None
    Bezel: Optional[str] = None
    ListPrice: Optional[float] = None
    ExcludeKeywords: Optional[str] = None

class ReadInputSKUsData(BaseModel):
    "Data returned by read_input_skus tool."
    skus: List[InputSKUData]

class ScrapeListingsParams(BaseModel):
    "Parameters for the 'scrape_listings' action of ChronoScraperTool."
    search_query_string:str

class ScrapedListingData(BaseModel):
    "Single scraped listing data sans ID."
    input_search_query_attributes: Optional[Dict[str, Any]] = None
    listing_url: str
    brand: Optional[str] = None
    model: Optional[str] = None
    case_material: Optional[str] = None
    reference_number: Optional[str] = None
    dial: Optional[str] = None
    dial_color: Optional[str] = None
    movement: Optional[str] = None
    listing_title: Optional[str] = None
    price: Optional[float] = None
    currency: Optional[str] = None
    condition: Optional[str] = None
    year_of_production: Optional[int] = None
    location: Optional[str] = None
    seller_name: Optional[str] = None

class ScrapedListingsData(BaseModel):
    "Data returned by scrape_listings action."
    scraped_items: List[ScrapedListingData]

class SaveListingParams(BaseModel):
    "Parameters for save_listings action."
    listings_data: List[ScrapedListingData]

class SaveListingsData(BaseModel):
    listings_saved_count: int
    listings_not_saved_count: int

class QueryLatestListingsParams(BaseModel):
    "Parameters for query_latest_filtered_listings action."
    input_sku_attributes_json: str
    target_condition: Optional[str] = None
    target_year_min: Optional[int] = None
    target_year_max: Optional[int] = None
    target_location: Optional[str] = None
    exclude_keywords: Optional[List[str]] = None
    limit: int = 20

class QueryLatestListingsData(BaseModel):
    "Data returned by query_latest_filtered_listings action."
    listings: List[ScrapedListingData]

class CalculateMarketAverageParams(BaseModel):
    "Parameters for calculate_market_average action."
    listings_data: List[ScrapedListingData]
    your_list_price: float  

class MarketAverageData(BaseModel):
    "Data returned by calculate_market_average"
    input_sku_attributes_json: Optional[Dict[str, Any]] = None
    your_list_price: float
    calculated_average_market_price: Optional[float] = None
    delta_percentage: Optional[float] = None
    bottom_n_listings_details: Optional[List[Dict[str, Any]]] = None
    bottom_5_listings_prices: Optional[List[float]] = None
    listings_considered_count: int


