import os
import web3lib
import asyncio
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get private key from environment
PRIV_KEY = os.getenv('PRIV_KEY')

# Create main wallet
web3lib.create_mainwallet(PRIV_KEY)

# Create bot object
bot = web3lib.UniswapV2Monitor(
    os.getenv('RPC_URL'),
    os.getenv('WEBSOCKET_URL')
)

asyncio.run(bot.monitor_mempool())