import json


class Config:
    def __init__(self, file_path="CONFIG.json"):

        self.RUN_ON_REAL = None
        self.SYMBOL = None
        self.SHIFT_AMOUNT = None
        self.BUY_THRESHOLD = None
        self.SELL_THRESHOLD = None
        self.LIMIT_ORDER_MAX_FILLING_TIME = None
        self.N_CANDLES_TO_CLOSE_OPEN_POSITION = None
        self.LONG_ALLOWED = None
        self.SHORT_ALLOWED = None
        self.TRAILING_SL_PERCENTAGE = None
        self.POSITION_SIZE = None
        self.START_TRADING_TIME = None
        self.END_TRADING_TIME = None
        self.OFFSET_AMOUNT = None

        self.file_path = file_path
        self.config_data = self.read_config_file()
        self.mapping = {
            "Execute on Real Account": "RUN_ON_REAL",
            "Symbol": "SYMBOL",
            "Shift parameter": "SHIFT_AMOUNT",
            "Offset parameter": "OFFSET_AMOUNT",
            "Buy threshold": "BUY_THRESHOLD",
            "Sell threshold": "SELL_THRESHOLD",
            "Limit order max filling time": "LIMIT_ORDER_MAX_FILLING_TIME",
            "N candles to close open position": "N_CANDLES_TO_CLOSE_OPEN_POSITION",
            "Long allowed": "LONG_ALLOWED",
            "Short allowed": "SHORT_ALLOWED",
            "Trailing SL percentage": "TRAILING_SL_PERCENTAGE",
            "Position size": "POSITION_SIZE",
            "Start trading time": "START_TRADING_TIME",
            "End trading time": "END_TRADING_TIME",
        }

        self.apply_config()

    def read_config_file(self):
        try:
            with open(self.file_path, "r") as file:
                return json.load(file)
        except:
            print("SEVERE WARNING: Unable to find the CONFIG.json file")
            exit()

    def apply_config(self):
        for human_key, var_name in self.mapping.items():
            value = self.config_data.get(human_key)
            if value is None:
                print(f"SEVERE WARNING: Issue with: {human_key} - attribute.")
                print(
                    "Execution halted due to unexpected attributes in JSON. "
                    "Double check the CONFIG.json attributes, or restore it using the backup"
                )
                exit()

            setattr(self, var_name, value)
