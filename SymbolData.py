import pandas as pd
from ibapi.contract import *
from ibapi.order import Order
from ibapi.common import BarData


class SymbolData:
    def __init__(self, symbol):
        self.symbol = symbol
        self.contract = None
        self.orders = {}
        self.active_position = 0
        self.historical_data = pd.DataFrame(
            columns=["date", "open", "high", "low", "close", "volume", "logReturn"]
        )
        self.price = -1
        self.ask = -1
        self.bid = -1

    def updateContract(self, contract):
        """Update contract information."""
        self.contract = contract

    def save_data_to_csv(self, file_name=None, directory=None):
        if file_name is None:
            file_name = self.symbol + ".csv"

        if directory is not None:
            file_name = directory + "/" + file_name

        self.historical_data.to_csv(file_name, index=False)

    def updateCurrentPrice(self, price):
        """Update the current price."""
        self.price = price

    def addOrder(self, order, flag):
        """Add an open order."""
        # [contract] [order_id] [order, flag -> '' | 'TP' | 'SL' OR PERSONALIZED, filled]
        self.orders[order.orderId] = {}
        self.orders[order.orderId]["order"] = order
        self.orders[order.orderId]["flag"] = flag
        self.orders[order.orderId]["filled"] = 0

    def updatePosition(self, quantity):
        """Update active position."""
        self.active_position += quantity

    def addHistoricalData(self, bar: BarData):
        if bar.date not in self.historical_data["date"].values:
            # Create a new DataFrame for the row to be added
            new_row = pd.DataFrame(
                [
                    {
                        "date": bar.date,
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume,
                        "logReturn": None,
                    }
                ]
            )

            # Use pd.concat to concatenate the new row with the existing DataFrame
            self.historical_data = pd.concat(
                [self.historical_data, new_row], ignore_index=True
            )
