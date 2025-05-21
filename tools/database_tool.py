import json
import logging
from typing import Any

import asyncpg

from core.protocol_definitions import (
    QueryLatestListingsParams,
    SaveListingParams,
    SaveListingsData,
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
        base_sql = self.config.get("BASE_SQL_INSERT_LISTINGS", "")
        num_columns = 14
        from datetime import UTC, datetime

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
                                json.dumps(listing.input_search_query_attributes)
                                if listing.input_search_query_attributes
                                else None
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
                                    listing.year_of_production,
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
