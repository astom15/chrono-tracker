import json
import logging
import time
from datetime import UTC
from typing import Any

import asyncpg

from core.protocol_definitions import (
    QueryLatestListingsData,
    QueryLatestListingsParams,
    SaveListingParams,
    SaveListingsData,
    ScrapedListingData,
    ToolRequest,
    ToolResponse,
)
from tools.base_tool import BaseTool


class DatabaseTool(BaseTool):
    """
    Tool for interacting with Postgres.
    Handles storing scraped listings and querying data.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        "Db tool init"
        super().__init__(tool_name="DatabaseTool", config=config)
        self.db_host = self.config.get("DB_HOST")
        self.db_port = self.config.get("DB_PORT")
        self.db_user = self.config.get("DB_USER")
        self.db_name = self.config.get("DB_NAME")
        self.pool: asyncpg.Pool | None = None
        if not hasattr(self, "logger"):
            self.logger = logging.getLogger(f"tool.{self.tool_name}")
        self.logger.info(f"Db initialized for db: {self.db_name} at {self.db_host}:{self.db_port}")

    async def _get_pool(self) -> asyncpg.Pool:
        "Initialize the database connection pool"
        try:
            self.logger.info("Creating postgres connection pool")
            self.pool = await asyncpg.create_pool(
                user=self.db_user,
                database=self.db_name,
                host=self.db_host,
                port=self.db_port,
                min_size=self.config.get("DB_MIN_POOL_SIZE", 1),
                max_size=self.config.get("DB_MAX_POOL_SIZE", 10),
            )
            self.logger.info("Postgres connection pool created")
        except ConnectionError as e:
            self.logger.exception(f"DatabaseTool: failed to create postgres connection pool: {e}")
            raise
        if self.pool is None:
            raise ConnectionError("DatabaseTool: failed to create postgres connection pool")
        return self.pool

    async def _close_pool(self):
        if self.pool and not self.pool._closed:
            self.logger.info("Closing postgres connection pool...")
            await self.pool.close()
            self.logger.info("Postgres connection pool closed")
        self.pool = None

    async def execute(self, request: ToolRequest) -> ToolResponse:
        "Executes an action for the DatabaseTool"
        self.logger.info(f"Received request: {request.action} with params: {request.params}")
        try:
            await self._get_pool()
        except ConnectionError as e:
            return self._create_error_response(str(e), request_params=request.params)

        action_handler = None
        if request.action == "save_listings":
            action_handler = self._handle_save_listings
        elif request.action == "query_latest_listings":
            action_handler = self._handle_query_latest_listings
        else:
            return self._create_error_response(f"Invalid action: {request.action} for {self.tool_name}")

        if action_handler:
            try:
                if request.action == "save_listings":
                    params_model = SaveListingParams(**request.params)
                    response_data = await action_handler(params_model)
                    return self._create_success_response(data=response_data.model_dump(), request_params=request.params)
                elif request.action == "query_latest_listings":
                    params_model = QueryLatestListingsParams(**request.params)
                    response_data = await action_handler(params_model)
                    return self._create_success_response(data=response_data.model_dump(), request_params=request.params)
            except Exception as e:
                self.logger.exception(f"Error executing DB action {request.action}: {e}")
                return self._create_error_response(str(e), request_params=request.params)
        return self._create_error_response(f"Invalid action: {request.action}", request_params=request.params)

    async def _handle_save_listings(self, params: SaveListingParams) -> SaveListingsData:
        "Handle save_listings action"
        if not params.listings_data:
            self.logger.info("No listings provided to save.")
            return SaveListingsData(listings_saved_count=0, listings_not_saved_count=0)
        pool = await self._get_pool()
        stored_count = 0
        failed_count = 0
        # might need to figure out the optimal size
        batch_size = self.config.get("DB_BATCH_SIZE", 50)
        base_sql = """
            INSERT INTO listings (
                input_sku_attributes,
                listing_url,
                listing_title,
                brand,
                model,
                price,
                currency,
                movement,
                case_material,
                production_year,
                condition,
                location,
                reference_number,
                scraped_timestamp) VALUES
            """
        num_columns = 14
        from datetime import datetime

        async with pool.acquire() as connection:
            async with connection.transaction():
                for i in range(0, len(params.listings_data), batch_size):
                    batch = params.listings_data[i : i + batch_size]
                    if not batch:
                        continue
                    values_parts = []
                    param_values: list[Any] = []
                    param_index = 1
                    for listing in batch:
                        try:
                            input_attrs_json = (
                                json.dumps(listing.input_sku_attributes) if listing.input_sku_attributes else None
                            )
                            placeholders = [f"${j}" for j in range(param_index, param_index + num_columns)]
                            values_parts.append(f"({','.join(placeholders)})")
                            param_index += 1

                            values_parts.append(f"({','.join(placeholders)})")
                            param_values.extend(
                                [
                                    input_attrs_json,
                                    listing.listing_url,
                                    listing.listing_title,
                                    listing.brand,
                                    listing.model,
                                    listing.price,
                                    listing.currency,
                                    listing.movement,
                                    listing.case_material,
                                    listing.production_year,
                                    listing.condition,
                                    listing.location,
                                    listing.reference_number,
                                    datetime.now(UTC),
                                ]
                            )
                        except Exception as e:
                            self.logger.exception(
                                f"Error preparing listing {getattr(listing, 'listing_url', 'N/A')}): {e}"
                            )
                            failed_count += 1
                    if not values_parts:
                        continue
                    batch_sql = base_sql + ",\n".join(values_parts)
                    try:
                        result_status: str | None = await connection.execute(batch_sql, *param_values)
                        if result_status and result_status.startswith("INSERT"):
                            try:
                                rows_inserted = int(result_status.split(" ")[2])
                                stored_count += rows_inserted
                                self.logger.debug(
                                    f"Batch insert successful. Status: {result_status}. Rows inserted: {rows_inserted}."
                                )
                            except (ValueError, IndexError) as parse_err:
                                self.logger.warning(
                                    f"Could not parse insert count from status string '{result_status}': {parse_err}. Assuming batch size for success if no error."
                                )
                                failed_count += len(batch)
                        else:
                            self.logger.warning(f"Batch insert status unclear: {result_status}")
                            failed_count += len(batch)
                    except asyncpg.PostgresError as pg_err:
                        self.logger.exception(f"Database error during batch insert execution: {pg_err}")
                        failed_count += len(batch)
                    except Exception as e:
                        self.logger.exception(f"Unexpected error during batch insert execution: {e}")
                        failed_count += len(batch)

        self.logger.info(f"Attempted to store {len(params.listings_data)} listings.Successfully stored {stored_count}.")
        return SaveListingsData(
            listings_saved_count=stored_count, listings_not_saved_count=len(params.listings_data) - stored_count
        )

    async def _handle_query_latest_listings(self, params: QueryLatestListingsParams) -> QueryLatestListingsData:
        "Handles querying db for listings matching criteria"
        self.logger.info(f"Query DB for listings matching criteria: {params.model_dump_json(indent=2)}")
        pool = await self._get_pool()
        base_query_select_fields = """
            id,
            input_sku_attributes,
            scraped_timestamp,
            listing_url,
            listing_title,
            price,
            currency,
            condition,
            production_year,
            location,
            reference_number,
            brand,
            model,
            movement,
            case_material
        """
        base_query = f"""
        WITH RankedListings AS (
            SELECT *,
                ROW_NUMBER() OVER (PARTITION BY listing_url ORDER BY scraped_timestamp DESC) AS rn
            FROM listings
            WHERE input_sku_attributes @> $1::jsonb
                OR (input_sku_attributes IS NULL AND $1::jsonb IS NULL)
            )
        SELECT {base_query_select_fields} FROM RankedListings WHERE RN = 1
        """
        conditions = []
        query_params: list[Any] = [params.input_sku_attributes_json]
        param_index = 2
        if params.target_condition:
            conditions.append(f"LOWER(condition) = LOWER(${param_index})")
            query_params.append(params.target_condition)
            param_index += 1
        if params.target_year_min is not None:
            conditions.append(f"production_year >= ${param_index}")
            query_params.append(params.target_year_min)
            param_index += 1
        if params.target_year_max is not None:
            conditions.append(f"production_year <= ${param_index}")
            query_params.append(params.target_year_max)
            param_index += 1
        if params.target_location:
            conditions.append(f"LOWER(location) = LOWER(${param_index})")
            query_params.append(params.target_location)
            param_index += 1
        if params.exclude_keywords:
            for _, keyword in enumerate(params.exclude_keywords):
                conditions.append(f"listing_title NOT ILIKE ${param_index}")
                query_params.append(f"%{keyword}%")
                param_index += 1
        final_query = base_query
        if conditions:
            final_query = f"""
            WITH RankedListings AS (
                SELECT 
                s1.*,
                ROW_NUMBER() OVER (PARTITION BY s1.listing_url ORDER BY s1.scraped_timestamp DESC) AS rn
                FROM listings s1
                WHERE s1.input_sku_attributes @> $1::jsonb
                    OR (s1.input_sku_attributes IS NULL AND $1::jsonb IS NULL)
            )
                SELECT {base_query_select_fields}
                FROM RankedListings
                WHERE rn = 1 AND ({" AND ".join(conditions)})
                ORDER BY price ASC NULLS LAST LIMIT ${param_index}
            """
        else:
            final_query = base_query + f" ORDER BY price ASC NULLS LAST LIMIT ${param_index}"

        query_params.append(params.limit)
        self.logger.debug(f"Executing DB Query: {final_query} with params: {query_params}")
        fetched_listings: list[ScrapedListingData] = []
        async with pool.acquire() as connection:
            try:
                records = await connection.fetch(final_query, *query_params)
                for record_dict in records:
                    record = dict(record_dict)
                    fetched_listings.append(ScrapedListingData(**record))
                    self.logger.info(f"Fetched {len(fetched_listings)} listings")
            except Exception:
                self.logger.exception("Error querying latest listings: {e}")
        return QueryLatestListingsData(listings=fetched_listings)


async def test_batch_insert_performance(db_tool: DatabaseTool, num_records: int = 1000):
    logger = logging.getLogger("TestBatchPerformance")
    logger.info(f"--- Starting Batch Insert Performance Test ({num_records} records) ---")
    from datetime import datetime

    # 1. Generate Dummy Data
    dummy_listings: list[ScrapedListingData] = []
    base_url = "https://www.chrono24.com/test/item"
    for i in range(num_records):
        dummy_listings.append(
            ScrapedListingData(
                input_sku_attributes={"Test": f"Batch{i}"},
                listing_url=f"{base_url}_{i}.htm",
                listing_title=f"Test Watch Batch {i}",
                brand="PerfTestBrand",
                model=f"ModelX{i}",
                price=float(1000 + i),
                currency="USD",
                condition="New",
                production_year=2024,
                location="Test Location",
                movement="Automatic",
                case_material="Steel",
                reference_number=f"REF{i}",
            )
        )
    print(len(dummy_listings))
    pool = await db_tool._get_pool()

    async def insert_with_multi_values(connection, batch_data):
        # This is your existing logic from _handle_store_listings, adapted
        total_inserted_count = 0
        total_failed_count = 0  # Not strictly used for timing but good for consistency
        batch_size = db_tool.config.get("db_batch_insert_size", 50)

        base_sql_columns = """
            INSERT INTO listings (
                input_sku_attributes, listing_url, listing_title, brand, model,
                price, currency, condition, production_year, location,
                movement, case_material, reference_number, scraped_timestamp
            ) VALUES 
        """
        num_columns_to_insert = 14

        for i in range(0, len(batch_data), batch_size):
            batch = batch_data[i : i + batch_size]
            if not batch:
                continue
            values_parts = []
            param_values: list[Any] = []
            current_placeholder_idx = 1
            for listing in batch:
                input_attrs_json = json.dumps(listing.input_sku_attributes) if listing.input_sku_attributes else None
                placeholders = [
                    f"${j}" for j in range(current_placeholder_idx, current_placeholder_idx + num_columns_to_insert)
                ]
                values_parts.append(f"({','.join(placeholders)})")
                current_placeholder_idx += num_columns_to_insert
                param_values.extend(
                    [
                        input_attrs_json,
                        listing.listing_url,
                        listing.listing_title,
                        listing.brand,
                        listing.model,
                        listing.price,
                        listing.currency,
                        listing.condition,
                        listing.production_year,
                        listing.location,
                        listing.movement,
                        listing.case_material,
                        listing.reference_number,
                        datetime.now(UTC),
                    ]
                )
            if not values_parts:
                continue
            batch_sql = base_sql_columns + ",\n".join(values_parts)
            result_status_string: str | None = await connection.execute(batch_sql, *param_values)
            if result_status_string and result_status_string.startswith("INSERT"):
                try:
                    total_inserted_count += int(result_status_string.split(" ")[2])
                except (IndexError, ValueError):
                    total_inserted_count += len(batch)  # Fallback assumption
            return total_inserted_count

    async with pool.acquire() as conn:
        logger.info("Truncating listings table for performance test...")
        await conn.execute("TRUNCATE TABLE listings RESTART IDENTITY;")

        logger.info("Testing Multi-VALUES INSERT method...")
        start_time_multi_values = time.perf_counter()
        async with conn.transaction():
            inserted_mv = await insert_with_multi_values(conn, dummy_listings)
        end_time_multi_values = time.perf_counter()
        duration_multi_values = end_time_multi_values - start_time_multi_values
        logger.info(f"Multi-VALUES INSERT: {inserted_mv} records in {duration_multi_values:.4f} seconds.")

    logger.info("--- Batch Insert Performance Test Finished ---")


if __name__ == "__main__":
    import asyncio
    import os

    async def main_test_runner():
        from core.config_loader import get_setting
        from core.config_loader import load_configurations as load_app_configurations
        from core.logging_config import setup_logging

        load_app_configurations()
        log_level_str = get_setting("General", "log_level", default="INFO")
        numeric_log_level = getattr(logging, log_level_str.upper(), logging.INFO)
        setup_logging(log_level=numeric_log_level)
        logger = logging.getLogger("TestBatchPerformance")
        db_config = {
            "DB_HOST": "localhost",
            "DB_PORT": "5432",
            "DB_USER": "andretom",
            "DB_NAME": "watch_dev",
            "DB_MIN_POOL_SIZE": 1,
            "DB_MAX_POOL_SIZE": 2,
            "DB_BATCH_SIZE": 50,
        }
        if not all([db_config["DB_NAME"], db_config["DB_USER"], db_config["DB_HOST"]]):
            logger.error(
                "Database connection details not fully configured for test. Check .env or main_config.ini [PostgreSQL] section."
            )
            return
        db_tool = DatabaseTool(config=db_config)
        try:
            test_listing_1 = ScrapedListingData(
                input_sku_attributes={"Test": "Batch1"},
                listing_url="https://www.chrono24.com/test/item1.htm",
                listing_title="Test Watch Batch 1",
                brand="PerfTestBrand",
                model="ModelX1",
                price=1000,
                currency="USD",
            )
            store_params = SaveListingParams(listings_data=[test_listing_1])
            store_request = ToolRequest(
                tool_name="DatabaseTool", action="save_listings", params=store_params.model_dump()
            )
            logger.info(f"Sending store_listings request (main test): {store_request.model_dump_json(indent=2)}")
            response_store = await db_tool.execute(store_request)

            logger.info("Received response from store_listings (main test):")
            print(response_store.model_dump_json(indent=2))

            # --- Now run the performance test ---
            await test_batch_insert_performance(db_tool, num_records=500)
        except Exception as e:
            logger.exception(f"Error in main test runner: {e}")
        finally:
            await db_tool._close_pool()
            # Create dummy config if needed for standalone run

    if not os.path.exists("config"):
        os.makedirs("config")
    if not os.path.exists("config/main_config.ini"):
        with open("config/main_config.ini", "w") as f:
            f.write("[General]\nlog_level=DEBUG\n")
            f.write("[PostgreSQL]\ndb_host=localhost\ndb_port=5432\ndb_name=watch_dev\ndb_user=your_user\n")
            f.write("[DatabaseTool]\nbatch_insert_size=50\n")
        print(
            "WARNING: Created a minimal dummy config/main_config.ini for test. Please ensure your actual files are configured."
        )

    asyncio.run(main_test_runner())
