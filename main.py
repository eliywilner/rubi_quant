# For any question contact me: julianvene@gmail.com
import os
import socket

import numpy as np
import requests
from requests import RequestException
from ibapi.contract import *
from Bot import Bot
from Config import Config
from ConnectionMonitor import ConnectionMonitor
from Log import Log
from SymbolData import SymbolData
from utils import *

import warnings


DEBUG = True

# Ignore all FutureWarnings
warnings.simplefilter(action="ignore", category=FutureWarning)
i = Config(file_path="CONFIG.json")

hostname = socket.gethostname()
delayed_data = False

# Directory for storing trade files
trades_dir = "TRADES"

# Check if the directory exists, if not, create it
if not os.path.exists(trades_dir):
    os.makedirs(trades_dir)

market_open_time = nyTimeTools.createNyDatetime("9:30:00")
market_closing_time = nyTimeTools.createNyDatetime("16:29:30")
end_strategy_time = nyTimeTools.createNyDatetime(i.END_TRADING_TIME)

logger = Log(debug=DEBUG)

logger.printAndLog("For any question contact me: julianvene@gmail.com")
TEST_DISCONNECTION = False


def execution_main_body(bot: Bot):

    # - # - # - # - # - # - # - # - # - # - #
    # START OF THE EXECUTION - TRADING LOGIC GOES HERE
    # - # - # - # - # - # - # - # - # - # - #

    # # Fill contract
    contract = Contract()
    contract.symbol = i.SYMBOL
    contract = bot.myRequest_fillContract(contract, US_stock=True)

    bot.symbol_datas[contract.symbol] = SymbolData(contract.symbol)
    bot.symbol_datas[contract.symbol].updateContract(contract)

    # # Get current position for each contract
    bot.myRequest_currentPositions([contract])

    query_time = ""

    bot.myRequest_HistoricalData(
        contract=contract,
        query_time=query_time,
        time_amount="2 D",
        bar_string_size="1 min",
        only_rth=True,
        up_to_date=False,
    )

    # Get today's date in the required format
    today = datetime.now().strftime("%Y%m%d")

    df = bot.symbol_datas[i.SYMBOL].historical_data
    df["logReturn"] = np.log(df["close"] / df["close"].shift(i.SHIFT_AMOUNT))

    # Check the last row's date and remove it if it matches today's date
    if df.iloc[-1]["date"].startswith(today):
        i.OFFSET_AMOUNT += 1
        df = df.iloc[:-1]

    print(df.iloc[-5:])

    bot.prices = df["close"].to_list()
    bot.log_returns = df["logReturn"].to_list()

    if nyTimeTools.currentTimeInNy() < market_open_time:
        nyTimeTools.waitTillTime(market_open_time)

    #     # Requesting live datass updates
    bot.log.printAndLog(f"Setting up live-data connection for: {contract.symbol}")
    bot.myRequest_mktData(contract, wait_first_price=True)

    # Start callBack1min Here
    bot.startCallBack()

    logger.printAndLog("CONNECTION ARE SET UP.")

    return True


# Ignore following function
def run_bot():
    logger.debugAndLog(f"run_bot executed.")

    new_bot_instance = Bot(logger, config=i)

    # Start connection
    logger.printAndLog(f"Connecting now to TWS")
    new_bot_instance.start()

    if delayed_data:
        new_bot_instance.delayed_data = True
        new_bot_instance.reqMarketDataType(3)

    all_good = execution_main_body(new_bot_instance)

    if not all_good:
        sys.exit()

    while (
        connection_monitor.connectionStatus()
        and nyTimeTools.currentTimeInNy() < end_strategy_time
        and nyTimeTools.currentTimeInNy() < market_closing_time
    ):
        time.sleep(0.5)

    return (
        not connection_monitor.connectionStatus(),
        new_bot_instance.connection_failed,
        new_bot_instance,
    )


if __name__ == "__main__":

    backup_bot = None
    disconnection_time = None
    print("\n\n")

    # Execute MonitorConnection
    connection_monitor = ConnectionMonitor(
        logger,
        forced_wait=1,
        disconnection_threshold=5,
    )

    connection_monitor.waitConnectionBack()
    connection_monitor.start()
    time.sleep(1)

    connection_lost, connection_failed, bot = run_bot()

    connection_monitor.stop()
    if connection_lost or connection_failed:
        logger.printAndLog(
            "[WARNING] Connection lost. Restart manually the bot for resuming operations"
        )

        connection_monitor.stop()
        bot.disconnect()
        end_operations()

    else:

        # - # - # - # - # - # - # - # - # - # - #
        # END OF DAY - TRADING LOGIC GOES HERE
        # - # - # - # - # - # - # - # - # - # - #

        logger.printAndLog(f"END OF TRADING DAY reached. Deactivating the bot.")

        # Delete orders
        contract = bot.symbol_datas[i.SYMBOL].contract
        bot.myRequest_deleteOrders([contract])

        # Close positions
        end_of_day_operations = {
            contract: bot.symbol_datas[contract.symbol].active_position
        }
        time.sleep(3)
        for contract, position in end_of_day_operations.items():
            if position != 0:
                order_action = "BUY" if position < 0 else "SELL"
                total_quantity = abs(position)

                _ = bot.myRequest_PlaceOrder(
                    contract, "MKT", order_action, total_quantity
                )

        timer = datetime.now() + timedelta(seconds=7.5)

        while datetime.now() < timer:
            time.sleep(0.5)

        bot.disconnect()
        bot.log.printAndLog(f"Bot is now disconnected.")
        bot.stopCallBack()
        time.sleep(2)
        del bot
        del connection_monitor

        input("Press Enter to quit...")
        sys.exit()
