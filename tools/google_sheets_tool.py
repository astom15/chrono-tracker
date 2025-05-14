import asyncio
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
from typing import Dict, Any, Optional, List

from tools.base_tool import BaseTool
from core.protocol_definitions import ToolRequest, ToolResponse, ReadInputSKUsParams, ReadInputSKUsData, InputSKUData
from core.config_loader import get_setting


class GoogleSheetsTool(BaseTool):
    """
    Tool for interacting with Google Sheets.
    Handles reading input SKUs and writing analysis results.
    """
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__("google_sheets", config)
        self.credentials_path = self.config.get("credentials_path")
        self.input_sheet_name = self.config.get("input_sheet_name")
        self.input_worksheet_name = self.config.get("input_worksheet_name")
        self.output_sheet_name = self.config.get("output_sheet_name")
        self.output_worksheet_name = self.config.get("output_worksheet_name")
        
        self.gc = None

        if not self.credentials_path:
            self.logger.error("Google Cloud credentials path not provided in config.")

    async def _connect(self):
        "Connect to google sheets"
        if self.gc: 
            return self.gc
        if not self.credentials_path:
            raise ConnectionError("Google Cloud credentials path not configured for GST.")
        
        def connect_sync():
            scope = ['https//spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
            creds = ServiceAccountCredentials.from_json_keyfile_name(self.credentials_path, scope)
            client = gspread.authorize(creds)
            return client

        try: 
            self.logger.debug("Attempting to connect to Google Sheets API...")
            loop = asyncio.get_event_loop()
            self.gc = await loop.run_in_executor(None, connect_sync)
            self.logger.info("Successfully connected to Sheets API")
            return self.gc
        except Exception as e:
            self.logger.exception(f"Failed to connect to Sheets API: {e}")
            raise ConnectionError(f"GST: Failed to connect - {e}")

    async def execute(self, request: ToolRequest) -> ToolResponse:
        "Executes an action requested for the GST"
        self.logger.info(f"Received request: {request.action} with params: {request.params}")
        if not self.gc:
            try:
                await self._connect()
            except ConnectionError as e:
                return self._create_error_response(str(e), request.params)

        action_handler = None
        if request.action == "read_input_skus":
            action_handler = self._handle_read_input_skus
        elif request.action == "write_summary_results":
            return self._create_error_response("Not implemented: {request.action}")
        else:
            return self._create_error_response(f"Unknown action: {request.action} for tool: {self.tool_name}", request_params=request.params)
        
        if action_handler:
            try:
                if request.action == "read_input_skus":
                    params_model = ReadInputSKUsParams(**request.params)
                    response_data_model = await action_handler(params_model)
                    return self._create_success_response(data=response_data_model.model_dump(), request_params=request.params)
            except Exception as e:
                self.logger.exception(f"Error in {request.action}: {str(e)}")
                return self._create_error_response(f"Error in {request.action}: {str(e)}", request_params=request.params)

    async def _handle_read_input_skus(self, params: ReadInputSKUsParams) -> ReadInputSKUsData:
        "Handles reading SKU data from the specified google sheet and worksheet."
        self.logger.info(f"Reading input SKUs from sheet: '{params.sheet_name}' and worksheet: '{params.worksheet_name}'")
        def read_sheet_sync():
            try:
                sheet = self.gc.open(params.sheet_name)
                worksheet = sheet.open(params.worksheet_name)
                records = worksheet.get_all_records()
                return records
            except gspread.exceptions.SpreadsheetNotFound:
                self.logger.error(f"Spreadsheet '{params.sheet_name}' not found.")
                raise
            except gspread.exceptions.WorksheetNotFound:
                self.logger.error(f"Worksheet '{params.worksheet_name}' not found in spreadsheet '{params.sheet_name}'.")
                raise
            except Exception as e:
                self.logger.error(f"Error accessing sheet: {str(e)}")
                raise ConnectionError(f"Error accessing sheet: {str(e)}")
            
        loop = asyncio.get_event_loop()
        try:
            records_list_of_dicts = await loop.run_in_executor(None, read_sheet_sync)
            self.logger.info(f"Successfully read {len(records_list_of_dicts)} records.")
            input_skus_data_list: List[InputSKUData] = []
            for i, record in enumerate(records_list_of_dicts):
                try:
                    sku_data = InputSKUData(**record)
                    input_skus_data_list.append(sku_data)
                except Exception as e:
                    self.logger.warning(f"Skipping row {i+2} due to error: {str(e)}. Record: {record}")
            self.logger.info(f"Successfully parsed {len(input_skus_data_list)} SKUs.")
            return ReadInputSKUsData(skus=input_skus_data_list)
        except Exception as e:
            raise RuntimeError(f"Error reading input SKUs: {str(e)}")
    