import os
import web3lib
import asyncio
import constant
from dotenv import load_dotenv

# Create main wallet
web3lib.create_mainwallet(constant.PRIV_KEY)

# Create bot object
bot = web3lib.UniswapV2Monitor(
    constant.RPC_URL,
    constant.WEBSOCKET_URL
)

asyncio.run(bot.monitor_mempool())