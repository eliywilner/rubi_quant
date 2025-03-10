### app/services/account_config.py ###
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.account_summary_tags import AccountSummaryTags
from loguru import logger
import threading
import time
import sys
import os

class IBKRAccountConfig(EWrapper, EClient):
    """Retrieves portfolio and trading parameter configuration from Interactive Brokers (IBKR) via IB Gateway, scalable for multiple accounts."""
    def __init__(self, host=None, port=None, client_id=None):
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.account_data = {}
        self.managed_accounts = []
        self.connected = threading.Event()

        # Load configuration from environment variables
        self.host = host or os.getenv("IB_GATEWAY_HOST", "127.0.0.1")
        self.port = port or int(os.getenv("IB_GATEWAY_PORT", 4002))  # 4002 for paper, 4001 for live
        self.client_id = client_id or int(os.getenv("IB_CLIENT_ID", 123))

    def connect_and_run(self):
        """Establishes connection to IB Gateway and starts data retrieval."""
        logger.info(f"Connecting to IB Gateway at {self.host}:{self.port} with client ID {self.client_id}...")
        self.connect(self.host, self.port, self.client_id)
        thread = threading.Thread(target=self.run, daemon=True)
        thread.start()
        time.sleep(2)
        self.connected.set()
        logger.info("Connected to IB Gateway.")
        self.reqManagedAccts()  # Request available accounts

    def error(self, reqId, errorCode, errorString):
        """Handles IBKR API errors."""
        logger.error(f"IBKR Error {errorCode}: {errorString}")
        if errorCode in [1100, 1300]:  # Connection lost or API error
            logger.warning("Reconnecting to IB Gateway...")
            self.disconnect()
            time.sleep(5)
            self.connect_and_run()

    def managedAccounts(self, accountsList):
        """Handles managed accounts response."""
        self.managed_accounts = accountsList.split(",")
        logger.info(f"Managed accounts retrieved: {self.managed_accounts}")

    def accountSummary(self, reqId, account, tag, value, currency):
        """Handles account summary responses for multiple accounts."""
        if account not in self.account_data:
            self.account_data[account] = {}
        self.account_data[account][tag] = value
        logger.info(f"Account: {account}, {tag}: {value} {currency}")

    def request_account_summary(self, single_account=None):
        """Requests account summary data for a single account or all accounts."""
        if not self.managed_accounts:
            logger.warning("No managed accounts found. Requesting again...")
            self.reqManagedAccts()
            time.sleep(2)

        accounts_to_query = [single_account] if single_account else self.managed_accounts
        for account in accounts_to_query:
            logger.info(f"Requesting account summary for {account}...")
            self.reqAccountSummary(1, account, AccountSummaryTags.AllTags)
        
        time.sleep(5)
        self.disconnect()
        return self.account_data

if __name__ == "__main__":
    ibkr_config = IBKRAccountConfig()
    try:
        ibkr_config.connect_and_run()
        time.sleep(3)
        
        # Run for a single account first (modify as needed for multiple accounts later)
        account_data = ibkr_config.request_account_summary(single_account=os.getenv("IB_SINGLE_ACCOUNT"))
        logger.info(f"Retrieved Account Configuration: {account_data}")
    except KeyboardInterrupt:
        logger.info("Shutting down IBKR connection...")
        ibkr_config.disconnect()
        sys.exit(0)
