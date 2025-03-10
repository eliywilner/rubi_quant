import csv
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Dict
from ibapi.order_condition import TimeCondition
import numpy as np
import pandas as pd
from ibapi.account_summary_tags import AccountSummaryTags
from ibapi.client import EClient
from ibapi.contract import *
from ibapi.execution import Execution
from ibapi.order import Order
from ibapi.wrapper import EWrapper
from ibapi.common import BarData, SetOfFloat, SetOfString
import pytz
from Config import Config
from Log import Log
from utils import nyTimeTools
from SymbolData import SymbolData


class Bot(EWrapper, EClient):

    def __init__(self, log: Log, config: Config, connect=False):
        # INITIALIZAZION # ----------------------------------------------------- #

        bot_version = 1.0
        EWrapper.__init__(self)
        EClient.__init__(self, self)

        # VARIABLES STRATEGY RELATED #

        # INTERNAL VARIABLES #
        self.trading_is_active = False
        self.option_chain_dict = {}
        self.stock_contracts = {}
        self.log = log
        self.CONNECTED = False
        self.i = config
        self.ID = 0
        self.temp_orderId = -1
        self.symbol_datas: Dict[str, SymbolData] = {}  # Symbol -> SymbolData()
        self.port = 0
        self.strike_list = None
        self.expiry_list = None
        self.delete_orders_list_of_contract = None
        self.delayed_data = False
        self.connection_failed = False
        self.pending_trades = {}
        self.trade_commissions = {}  # Store commissions by execution ID
        self.timer = None
        self.flag_test = True
        self.start_trading_time = nyTimeTools.createNyDatetime(
            self.i.START_TRADING_TIME
        )
        self.callback_thread = threading.Thread(target=self.oneMinuteCallback)
        self.stop_thread = threading.Event()
        self.prices = []
        self.log_returns = []

        self.ids_to_contract = {
            "hist": {},
            "live": {},
            "order": {},
            "contract": {},
            "other": {},
        }
        self.contract_to_ids = {
            "hist": {},
            "live": {},
            "order": {},
            "contract": {},
            "other": {},
        }

        # EVENTS() || id -> Event()

        self.historicalData_events = {}
        self.contractDetails_events = {}
        self.liveData_events = {}
        self.openOrders_events = {}
        self.option_events = {}
        self.account_summary = {}

    def start(self):
        self.port = 7496 if self.i.RUN_ON_REAL else 7497
        self.connect("127.0.0.1", self.port, 1)

        t = threading.Thread(target=self.run)
        t.start()
        time.sleep(1)

        self.reqIds(1)

        # Wait for IBKR's servers to answer back.
        while self.temp_orderId == -1:
            time.sleep(0.01)

        if not self.connection_failed:
            self.CONNECTED = True
            self.log.printAndLog("Bot connected to IBKR on port: " + str(self.port))
            self.log.printAndLog("")
            self.log.printAndLog("Running on real account: " + str(self.i.RUN_ON_REAL))

    def tickPrice(self, reqId, tickType, price: float, attrib):

        # - # - # - # - # - # - # - # - # - # - #
        # ON TICK UPDATE - TRADING LOGIC GOES HERE
        # - # - # - # - # - # - # - # - # - # - #

        # Init
        contract = self.ids_to_contract["live"][reqId]

        # Stock:
        if contract.secType == "STK" or contract.secType == "IND":
            if self.liveData_events.get(reqId):
                self.symbol_datas[contract.symbol].updateCurrentPrice(price)
                self.liveData_events[reqId].set()
                self.log.debugAndLog(
                    f"Received first price for {contract.symbol}: {price}"
                )
                self.trading_is_active = True

            # Last
            if tickType == 4:
                self.symbol_datas[contract.symbol].updateCurrentPrice(price)

            # Best bid
            if tickType == 1:
                self.symbol_datas[contract.symbol].bid = price

            # Best ask
            if tickType == 2:
                self.symbol_datas[contract.symbol].ask = price

    def myRequest_currentPositions(self, contract_list: list):
        print()
        self.log.printAndLog("Checking if there is an active position on symbol.")
        self.temp_contract_list_for_pos_request = contract_list

        self.liveData_events[1234567] = threading.Event()

        self.reqPositions()

        self.liveData_events[1234567].wait()
        self.liveData_events[1234567].clear()
        del self.liveData_events[1234567]

        self.cancelPositions()

    def position(self, account: str, contract: Contract, position: float, avgCost: float):

        for ct in self.temp_contract_list_for_pos_request:
            if contract.symbol == ct.symbol and contract.secType == ct.secType:

                for _, symboldata in self.symbol_datas.items():
                    if (
                        symboldata.contract.symbol == contract.symbol
                        and symboldata.contract.secType == contract.secType
                        and position != 0.0
                    ):
                        self.log.printAndLog(
                            f"Updating position of {contract.symbol} to: {position}"
                        )
                        symboldata.active_position = position

                        return

    def positionEnd(self):
        self.liveData_events[1234567].set()

    # IMPLEMENT HERE THE LOGIC FOR EACH SYMBOL
    def check_entry_conditions(self, deviation):
        # - # - # - # - # - # - # - # - # - # - #
        # ON ENTRY CONDITION CHECK (EVERY MINUTE) - TRADING LOGIC GOES HERE
        # - # - # - # - # - # - # - # - # - # - #

        self.log.debugAndLog(f"Checking new entry condition")
        self.log.debugAndLog(f"Current offset deviation: {deviation}")

        open_long, open_short = self.check_enter_order(deviation)

        if open_long:

            # 1) Parent limit buy order:
            #    - Transmit=False (we'll transmit on the final child)
            #    - Time-based cancel after self.i.LIMIT_ORDER_MAX_FILLING_TIME seconds
            bid = self.symbol_datas[self.i.SYMBOL].bid
            ask = self.symbol_datas[self.i.SYMBOL].ask

            limit_price = round(
                (bid + ask) / 2,
                2,
            )

            self.log.printAndLog(f"Current Book -- Bid: {bid} || Ask: {ask}")

            parent_order = self.myRequest_PlaceOrder(
                contract=self.symbol_datas[self.i.SYMBOL].contract,
                order_type="LMT",
                order_action="BUY",
                qty=self.i.POSITION_SIZE,
                transmit=False,
                lmt_price=limit_price,
                flag="LONG_ENTRY",
                # For time-based cancel:
                time_condition_type="cancel",  # "cancel" => TWS cancels unfilled portion after X seconds
                time_condition_secs=self.i.LIMIT_ORDER_MAX_FILLING_TIME,
            )

            # 2) Child trailing stop order:
            #    - Must reference parent_id = parent_order.orderId
            #    - trailingPercent = self.i.TRAILING_SL_PERCENTAGE
            #    - Transmit=False, so we can place the final child below
            _ = self.myRequest_PlaceOrder(
                contract=self.symbol_datas[self.i.SYMBOL].contract,
                order_type="TRAIL",
                order_action="SELL",
                qty=self.i.POSITION_SIZE,
                transmit=False,
                parent_id=parent_order.orderId,
                trailing_percent=self.i.TRAILING_SL_PERCENTAGE,
                flag="SL_TRAIL",
            )

            # 3) Child take-profit (time-based) Market order:
            #    - Also references parent_id
            #    - We want it to *activate* (not cancel) after N_CANDLES_TO_CLOSE_OPEN_POSITION minutes
            #    - So we use time_condition_type="trigger"
            #    - We set transmit=True here, causing TWS to transmit all orders (the bracket)
            #
            # Convert minutes -> seconds for time_condition_secs
            tp_seconds = self.i.N_CANDLES_TO_CLOSE_OPEN_POSITION * 60

            _ = self.myRequest_PlaceOrder(
                contract=self.symbol_datas[self.i.SYMBOL].contract,
                order_type="MKT",
                order_action="SELL",
                qty=self.i.POSITION_SIZE,
                transmit=True,
                parent_id=parent_order.orderId,
                # For time-based trigger:
                time_condition_type="trigger",  # "trigger" => order *activates* after time_condition_secs
                time_condition_secs=tp_seconds,
                flag="MKT_TIME_TRIG",
            )

            self.log.printAndLog(f"Placed bracket order:")
            self.log.printAndLog(
                f" - Parent LMT buy with time-cancel ({self.i.LIMIT_ORDER_MAX_FILLING_TIME}s)"
            )
            self.log.printAndLog(
                f" - Child TR trailing stop ({self.i.TRAILING_SL_PERCENTAGE}%)"
            )
            self.log.printAndLog(
                f" - Child MKT take-profit triggered after {self.i.N_CANDLES_TO_CLOSE_OPEN_POSITION} candle(s)"
            )
            self.log.printAndLog(f" - Parent ID: {parent_order.orderId}")

        elif open_short:

            bid = self.symbol_datas[self.i.SYMBOL].bid
            ask = self.symbol_datas[self.i.SYMBOL].ask

            limit_price = round(
                (bid + ask) / 2,
                2,
            )

            self.log.printAndLog(f"Current Book -- Bid: {bid} || Ask: {ask}")

            # 1) Parent limit SELL
            parent_order_short = self.myRequest_PlaceOrder(
                contract=self.symbol_datas[self.i.SYMBOL].contract,
                order_type="LMT",
                order_action="SELL",
                qty=self.i.POSITION_SIZE,
                transmit=False,
                lmt_price=limit_price,
                flag="SHORT_ENTRY",
                time_condition_type="cancel",  # TWS cancels unfilled portion after X seconds
                time_condition_secs=self.i.LIMIT_ORDER_MAX_FILLING_TIME,
            )

            # 2) Child trailing stop BUY
            _ = self.myRequest_PlaceOrder(
                contract=self.symbol_datas[self.i.SYMBOL].contract,
                order_type="TRAIL",
                order_action="BUY",
                qty=self.i.POSITION_SIZE,
                transmit=False,
                parent_id=parent_order_short.orderId,
                trailing_percent=self.i.TRAILING_SL_PERCENTAGE,
                flag="SL_TRAIL",
            )

            tp_seconds = self.i.N_CANDLES_TO_CLOSE_OPEN_POSITION * 60

            # 3) Child MKT BUY triggered by time
            _ = self.myRequest_PlaceOrder(
                contract=self.symbol_datas[self.i.SYMBOL].contract,
                order_type="MKT",
                order_action="BUY",
                qty=self.i.POSITION_SIZE,
                transmit=True,
                parent_id=parent_order_short.orderId,
                time_condition_type="trigger",  # activates after time_condition_secs
                time_condition_secs=tp_seconds,
                flag="MKT_TIME_TRIG",
            )

            self.log.printAndLog(f"Placed SHORT bracket order:")
            self.log.printAndLog(
                f" - Parent LMT SELL (time-cancel={self.i.LIMIT_ORDER_MAX_FILLING_TIME}s)"
            )
            self.log.printAndLog(
                f" - Child TR BUY stop ({self.i.TRAILING_SL_PERCENTAGE}%)"
            )
            self.log.printAndLog(
                f" - Child MKT BUY triggered after {self.i.N_CANDLES_TO_CLOSE_OPEN_POSITION} candle(s)"
            )
            self.log.printAndLog(f" - Parent ID: {parent_order_short.orderId}")

    def check_enter_order(self, deviation):

        if self.symbol_datas[self.i.SYMBOL].active_position != 0:
            self.log.printAndLog(
                f"Skipping entry conditions because there is an active position."
            )

            return False, False

        # Buy condition
        open_long, open_short = False, False
        if self.i.LONG_ALLOWED and (deviation < self.i.BUY_THRESHOLD):
            self.log.printAndLog(f"BUY condition verified.")
            self.log.printAndLog(
                f"Current deviation: {deviation}. Buy threshold: {1 + self.i.BUY_THRESHOLD}"
            )
            open_long = True

        elif self.i.SHORT_ALLOWED and (deviation > self.i.SELL_THRESHOLD):
            self.log.printAndLog(f"SELL condition verified.")
            self.log.printAndLog(
                f"Current deviation: {deviation}. Sell threshold: {1 + self.i.SELL_THRESHOLD}"
            )
            open_short = True

        return open_long, open_short

    def update_timer(self) -> bool:
        if self.timer is None:

            if nyTimeTools.currentTimeInNy() < nyTimeTools.createNyDatetime("09:30:00"):
                # Define the NY time zone
                ny_tz = pytz.timezone("America/New_York")
                local_tz = datetime.now().astimezone().tzinfo

                # Get the current date in NY time and set the time to 09:30:00
                ny_datetime = ny_tz.localize(
                    datetime.now().replace(hour=9, minute=30, second=0, microsecond=0)
                )

                # Convert NY datetime to the computer's local time zone
                self.timer = ny_datetime.astimezone(local_tz).replace(tzinfo=None)

            else:
                self.timer = datetime.now().replace(
                    second=0, microsecond=0
                ) + timedelta(minutes=1)

            self.log.printAndLog(f"Next checking timer: {self.timer}")
            return False

        if datetime.now() > self.timer:
            self.timer = self.timer + timedelta(minutes=1)
            self.log.printAndLog(f"Next checking timer: {self.timer}")

            return True

    def writeTradeToCSV(self, trade_details):
        file_path = (
            f"TRADES/TRADES_{nyTimeTools.currentTimeInNy().strftime('%d%m%Y')}.csv"
        )

        # Check if TRADES directory exists, if not, create it
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        # Check if file exists and write headers if it does not
        file_exists = os.path.isfile(file_path)
        with open(file_path, "a", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=trade_details.keys())
            if not file_exists:
                writer.writeheader()  # File doesn't exist, write a header
            writer.writerow(trade_details)  # Write the trade details

    def startCallBack(self):
        self.log.debugAndLog(f"STARTING SEPARATED THREAD FOR ENTRY CONDITION CHECK")
        self.callback_thread.daemon = True
        self.callback_thread.start()

    def stopCallBack(self):
        self.log.debugAndLog(f"CLOSING DEDICATED THREAD FOR ENTRY CONDITION CHECK")
        self.stop_thread.set()
        self.callback_thread.join()

    def oneMinuteCallback(self):

        # Setup INITIAL check time
        _ = self.update_timer()
        time.sleep((self.timer - datetime.now()).total_seconds())

        while (
            nyTimeTools.currentTimeInNy() < nyTimeTools.createNyDatetime("15:29:00")
            and not self.stop_thread.is_set()
        ):
            # - # - # - # - # - # - # - # - # - # - #
            # DEFINITION OF OPERATIONAL-LOOP (EVERY MINUTE) - TRADING LOGIC GOES HERE
            # - # - # - # - # - # - # - # - # - # - #
            self.log.printAndLog("")

            # Update new price and log return
            price = self.symbol_datas[self.i.SYMBOL].price
            self.log.debugAndLog(
                f"Using for logreturn computation: {price}, {self.prices[-self.i.SHIFT_AMOUNT]}"
            )
            self.prices.append(price)
            log_return = float(
                np.log(self.prices[-1] / self.prices[-self.i.SHIFT_AMOUNT])
            )
            self.log_returns.append(log_return)

            self.log.printAndLog(
                f'New price for {datetime.now().strftime("%H:%M:%S")}. Price: {price} - LogReturn: {log_return}'
            )

            # self.log.debugAndLog(f"Last prices: {self.prices[-self.i.SHIFT_AMOUNT:]}")
            # self.log.debugAndLog(f"Last Log returns: {self.log_returns[-self.i.OFFSET_AMOUNT:]}")

            if (
                self.trading_is_active
                and nyTimeTools.currentTimeInNy() > self.start_trading_time
            ):
                # Select threshold
                deviation_logreturn = self.log_returns[-self.i.OFFSET_AMOUNT]

                self.check_entry_conditions(deviation_logreturn)

            time.sleep(60)

    def commissionReport(self, commissionReport):
        execId = commissionReport.execId
        commission = commissionReport.commission

        # If the execId is in pending_trades, update it with commission
        if execId in self.pending_trades:
            self.pending_trades[execId]["COMMISSIONS"] = commission
            self.writeTradeToCSV(self.pending_trades[execId])
            # Remove the trade from pending_trades as it's now complete
            del self.pending_trades[execId]

    def myRequest_deleteOrders(self, list_of_contracts):
        self.delete_orders_list_of_contract = [
            contract.conId for contract in list_of_contracts
        ]
        self.openOrders_events[999] = threading.Event()
        self.reqOpenOrders()
        self.openOrders_events[999].wait()

    def openOrder(self, orderId, contract: Contract, order: Order, orderState):

        if self.openOrders_events.get(999):
            if contract.conId in self.delete_orders_list_of_contract:
                self.cancelOrder(order.orderId)

    def openOrderEnd(self):
        if self.openOrders_events.get(999):
            self.openOrders_events.get(999).set()

    def execDetails(self, reqId: int, contract: Contract, execution: Execution):
        if contract.secType == "STK":
            symbol = self.ids_to_contract["order"][execution.orderId].symbol

            # Update variables
            flag = self.symbol_datas[symbol].orders[execution.orderId]["flag"]
            self.symbol_datas[symbol].orders[execution.orderId][
                "filled"
            ] += execution.shares

            if execution.side == "BOT":
                self.symbol_datas[symbol].active_position += execution.shares
            else:
                self.symbol_datas[symbol].active_position -= execution.shares

            self.log.printAndLog(
                f'{symbol} - [Order ID: {execution.orderId}] - EXECUTION - Filled {flag} order: {self.symbol_datas[symbol].orders[execution.orderId]["filled"]}/'
                f'{self.symbol_datas[symbol].orders[execution.orderId]["order"].totalQuantity}. Avg Price: {execution.avgPrice}'
            )
            self.log.printAndLog(
                f"{symbol} - Current position: {self.symbol_datas[symbol].active_position}"
            )

        partial_fill = self.symbol_datas[contract.symbol].orders[execution.orderId][
            "filled"
        ]

        tot_qty = (
            self.symbol_datas[contract.symbol]
            .orders[execution.orderId]["order"]
            .totalQuantity
        )

        if partial_fill == tot_qty:
            symbol = contract.symbol
            fill_time = nyTimeTools.currentTimeInNy().strftime("%H:%M:%S")
            quantity = execution.shares
            avg_price = execution.avgPrice
            df_flag = flag

            self.pending_trades[execution.execId] = {
                "SYMBOL": symbol,
                "FILL_TIME": fill_time,
                "ACTION": execution.side,
                "QUANTITY": quantity,
                "AVG_PRICE": avg_price,
                "COMMISSIONS": 0,
                "FLAG": df_flag,
            }

    def myRequest_PlaceOrder(self,contract,order_type,order_action,qty,transmit=True,lmt_price=None,aux_price=None,parent_id=None,flag="",
        # Trailing-stop parameter (use if order_type == "TRAIL")
        trailing_percent=None,
        # Time condition parameters
        time_condition_type=None,  # can be "cancel", "trigger", or None
        time_condition_secs=0,):

        # Create the IB Order
        order = Order()
        order.orderId = self.getNextOrderID(contract)

        if parent_id:
            order.parentId = parent_id

        order.action = order_action

        # Set the main prices
        if lmt_price is not None:
            order.lmtPrice = lmt_price
        if aux_price is not None:
            order.auxPrice = aux_price

        order.orderType = order_type
        order.totalQuantity = qty
        order.triggerMethod = 7  # default or your preference
        order.transmit = transmit

        # If it's a trailing stop
        if order_type.upper() == "TRAIL":
            if trailing_percent is None:
                raise ValueError(
                    "If order_type='TRAIL', you must provide trailing_percent."
                )
            order.trailingPercent = trailing_percent

        # Attempt eTradeOnly / firmQuoteOnly
        try:
            order.eTradeOnly = False
        except:
            pass
        try:
            order.firmQuoteOnly = False
        except:
            pass

        # ---- Add the order to your SymbolData tracking (STK vs OPT) ----
        if contract.secType == "STK":
            self.symbol_datas[contract.symbol].addOrder(order, flag)
        elif contract.secType == "OPT":
            self.symbol_datas[contract.symbol].addOptionOrder(contract, order, flag)

        # ---- Time Condition logic (use US/Eastern for the time) ----
        if time_condition_type is not None and time_condition_secs > 0:
            eastern_tz = pytz.timezone("US/Eastern")
            now_eastern = datetime.now(eastern_tz)
            target_time = now_eastern + timedelta(seconds=time_condition_secs)

            tc = TimeCondition()
            # "IsMore=True" => triggers once 'current time' > 'target_time'
            tc.isMore = True
            tc.time = target_time.strftime("%Y%m%d %H:%M:%S US/Eastern")
            tc.isConjunctionConnection = True  # single condition => doesn't matter

            order.conditions = [tc]

            # If "cancel", TWS will cancel the unfilled portion after the condition is met.
            # If "trigger", TWS will *activate* this order after the condition is met.
            if time_condition_type == "cancel":
                order.conditionsCancelOrder = True
            else:  # e.g. "trigger"
                order.conditionsCancelOrder = False

        # ---- Logging output ----
        ct_string_identifier = f"{contract.symbol}{contract.right}{contract.lastTradeDateOrContractMonth}{contract.strike}"

        if order_type == "MKT":
            self.log.printAndLog(
                f"{ct_string_identifier} - [Order ID: {order.orderId}] || "
                f"Placing {flag} {order_action} {order_type} order with size {qty}"
            )
        elif order_type.upper() == "TRAIL":
            self.log.printAndLog(
                f"{ct_string_identifier} - [Order ID: {order.orderId}] || "
                f"Placing {flag} {order_action} TRAIL order with trailingPercent={trailing_percent} "
                f"and size {qty}"
            )
        else:
            price = lmt_price if lmt_price is not None else aux_price
            self.log.printAndLog(
                f"{ct_string_identifier} - [Order ID: {order.orderId}] || "
                f"Placing {flag} {order_action} {order_type} order at price: {price}, with size {qty}"
            )

        # ---- Place the order ----
        self.placeOrder(order.orderId, contract, order)

        return order

    def myRequest_fillContract(self, contracts, US_stock):
        self.stock_contracts = {}

        if not isinstance(contracts, list):
            contracts = [contracts]

        contract_details_ids = []

        for ct in contracts:

            if US_stock:
                ct.secType = "STK"
                ct.currency = "USD"
                ct.exchange = "SMART"

            if ct.secType == "STK":
                self.log.printAndLog(f"Filling contract for: {ct.symbol}")
            elif ct.secType in [
                "OPT",
                "FUT",
            ]:  # Assuming other types like 'OPT', 'FUT', etc.
                ct_string_identifier = (
                    f"{ct.symbol}{ct.right}{ct.lastTradeDateOrContractMonth}{ct.strike}"
                )
                ct_string_identifier.replace(" ", "")
                self.log.printAndLog(f"Filling contract for: {ct_string_identifier}")

            contract_details_id = self.getNewReqID(category="contract", contract=ct)
            self.contractDetails_events[contract_details_id] = threading.Event()
            self.reqContractDetails(contract_details_id, ct)
            contract_details_ids.append(contract_details_id)
            time.sleep(0.05)

        for id in contract_details_ids:
            self.contractDetails_events[id].wait()
            self.contractDetails_events[id].clear()
            del self.contractDetails_events[id]
            self.log.debugAndLog(f"Contract filled for: {self.stock_contracts.get(id)}")

        if len(contracts) == 1:
            return self.stock_contracts.get(contract_details_ids[0])
        else:
            return self.stock_contracts

    def contractDetails(self, reqId: int, cd: ContractDetails):
        self.stock_contracts[reqId] = cd.contract

    def contractDetailsEnd(self, reqId: int):
        self.contractDetails_events[reqId].set()

    def myRequest_HistoricalData(
        self, contract, query_time, time_amount, bar_string_size, only_rth, up_to_date
    ):
        temp_id = self.getNewReqID(category="hist", contract=contract)
        self.historicalData_events[temp_id] = threading.Event()
        self.reqHistoricalData(
            temp_id,
            contract,
            query_time,
            time_amount,
            bar_string_size,
            "TRADES",
            only_rth,
            1,
            up_to_date,
            [],
        )

        self.historicalData_events[temp_id].wait()
        self.historicalData_events[temp_id].clear()
        del self.historicalData_events[temp_id]

    def historicalData(self, reqId: int, bar: BarData):
        symbol = self.ids_to_contract["hist"][reqId].symbol
        self.symbol_datas[symbol].addHistoricalData(bar)

    def historicalDataEnd(self, reqId: int, start: str, end: str):

        self.historicalData_events[reqId].set()

    def myRequest_mktData(self, contract, wait_first_price=False):
        if contract.strike == 0:
            self.log.debugAndLog(f"Requesting LIVE datass for: {contract.symbol}")
        else:
            self.log.debugAndLog(
                f"Requesting LIVE datass for: {contract.symbol} {contract.right} {contract.lastTradeDateOrContractMonth} {contract.strike}"
            )
        temp_id = self.getNewReqID(category="live", contract=contract)

        self.liveData_events[temp_id] = threading.Event()

        self.reqMktData(temp_id, contract, "", False, False, [])

        if wait_first_price:
            self.liveData_events[temp_id].wait()

        self.liveData_events[temp_id].clear()
        del self.liveData_events[temp_id]

    # DO NOT MODIFY # ---------------------------------------------------------------- #

    # Categories: 'hist' , 'live' , 'order' , 'contract' , 'other'
    def addMapping(self, category, reqId, contract: Contract):
        """Adds a two-way mapping between reqId and symbol"""

        self.ids_to_contract[category][reqId] = contract
        self.contract_to_ids[category][contract] = reqId

    def removeMapping(self, category, reqId=None, symbol=None):
        """Removes a two-way mapping. Can specify either reqId or symbol"""
        if reqId:
            symbol = self.ids_to_contract[category][reqId]
            del self.ids_to_contract[category][reqId]
            del self.contract_to_ids[category][symbol]
        elif symbol:
            reqId = self.contract_to_ids[category][symbol]
            del self.contract_to_ids[category][symbol]
            del self.ids_to_contract[category][reqId]

    def getNewReqID(self, category, contract: Contract):
        self.ID += 1
        self.addMapping(category, self.ID - 1, contract)
        return self.ID - 1

    def nextValidId(self, orderId: int):
        self.temp_orderId = orderId

    def getNextOrderID(self, contract: Contract):
        self.temp_orderId += 1
        self.addMapping("order", self.temp_orderId - 1, contract)
        return self.temp_orderId - 1

    def error(self, reqId, errorCode, errorString):

        if errorCode not in [
            2168,
            2169,
            2108,
            399,
            2176,
            202,
            10147,
            10148,
            2104,
            1100,
            1102,
            10090,
            10167,
            504,
        ]:
            self.log.printAndLog(
                "Message: "
                + str(errorCode)
                + ", ID: "
                + str(reqId)
                + " => "
                + str(errorString)
            )

        else:
            if errorCode != 2176:
                self.log.debugAndLog(
                    "Message: "
                    + str(errorCode)
                    + ", ID: "
                    + str(reqId)
                    + " => "
                    + str(errorString)
                )

        if reqId in self.historicalData_events and errorCode != 2176:
            self.historicalData_events[reqId].set()

        if reqId in self.contractDetails_events:
            self.contractDetails_events[reqId].set()

        if errorCode == 504:
            self.log.printAndLog(f"[WARNING] Failed to connect to TWS")
            self.connection_failed = True
            self.temp_orderId = -99
