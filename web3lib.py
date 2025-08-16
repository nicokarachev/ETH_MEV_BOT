import os
import logging
import asyncio
import websockets
import json
import constant
from hexbytes import HexBytes
from pathlib import Path
from web3 import Web3
from eth_account import Account

# Configure logging
# logging.basicConfig(
#     filename="log.txt",
#     level=logging.INFO,  # Levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
#     format="%(asctime)s - %(levelname)s - %(message)s"
# )

def create_mainwallet(filename='private_key.bin'):
    """
    Read private key from file if exists, otherwise create new one.
    
    Returns:
        bytes: 32-byte private key
    """
    try:
        # Try to read existing private key
        if Path(filename).exists():
            with open(filename, 'rb') as f:
                private_key_bytes = f.read()
                
            # Validate it's exactly 32 bytes
            if len(private_key_bytes) == 32:
                print(f"✅ Private key loaded from {filename}")
                return private_key_bytes
            else:
                print(f"⚠️ Invalid key length in {filename}, creating new one...")
        else:
            print(f"📁 {filename} not found, creating new private key...")
            
    except Exception as e:
        print(f"❌ Error reading {filename}: {e}")
        print("🔄 Creating new private key...")
    
    # Create new private key if reading failed or file doesn't exist
    private_key_bytes = os.urandom(32)
    
    try:
        # Write new private key to file
        with open(filename, 'wb') as f:
            f.write(private_key_bytes)
        print(f"✅ New private key created and saved to {filename}")
        
    except Exception as e:
        print(f"❌ Error writing to {filename}: {e}")
    
    return private_key_bytes


class UniswapV2Monitor:
    def __init__(
        self, 
        web3_provider, 
        web3_provicer_socket,
        router_address = constant.ROUTER_ADDRESS, 
        factory_address = constant.FACTORY_ADDRESS,
        filter_volume = constant.FILTER_VOLUME,
        filter_slippage = constant.FILTER_SLIPPAGE,
        weth_address = constant.WETH_ADDRESS,
        multicall_address = constant.MULTICALL_ADDRESS):
        """
        Monitor Uniswap V2 swap transactions
        
        Args:
            web3_provider: Web3 HTTP/WebSocket provider URL
        """
        
        print(f"here ! {web3_provicer_socket}")
        
        self.w3 = Web3(Web3.LegacyWebSocketProvider(web3_provicer_socket))
        
        if not self.w3.is_connected():
            print("❌ Connection failed")
            exit()

        print("✅ Connected to Ethereum mainnet")

        self.w3soc = web3_provicer_socket
                
        # Uniswap V2 Router address
        self.router_address = router_address
        self.router_contract = self.w3.eth.contract(
            address = self.router_address,
            abi = constant.ROUTER_ABI
        )
        
        # Uniswap V2 Factory address
        self.factory_address = factory_address
        self.factory_contract = self.w3.eth.contract(
            address = self.factory_address,
            abi = constant.FACTORY_ABI
        )
        
        # Uniswap Multicall address
        self.multicall_address = multicall_address
        self.multicall_contract = self.w3.eth.contract(
            address = self.multicall_address,
            abi = constant.MULTICALL3_ABI
        )
                
        # Transaction Volume Thresold(Ether amount, over $10k)
        self.filter_volume = filter_volume
        
        # Slippage Thresold(percentage, 5 is 0.5%)
        self.filter_slippage = filter_slippage
        
        # WETH address
        self.weth_address = weth_address
        
      
    def decode_swap_event(self, log):
        """Decode Uniswap V2 Swap event from log"""
        try:
            # Create contract instance for decoding
            contract = self.w3.eth.contract(abi=self.pair_abi)
            
            # Decode the log
            decoded_log = contract.events.Swap().processLog(log)
            
            swap_data = {
                'pair_address': log['address'],
                'sender': decoded_log['args']['sender'],
                'to': decoded_log['args']['to'],
                'amount0In': decoded_log['args']['amount0In'],
                'amount1In': decoded_log['args']['amount1In'],
                'amount0Out': decoded_log['args']['amount0Out'],
                'amount1Out': decoded_log['args']['amount1Out'],
            }
            
            return swap_data
            
        except Exception as e:
            logging.error(f"Error decoding swap event: {e}")
            return None
        
    def check_swap(self, input_data):
        
        swap_signatures = [
            'fb3bdb41', #swapETHForExactTokens
            '7ff36ab5', #swapExactETHForTOkens
            'b6f9de95', #swapExactETHForTOkens
            #'18cbafe5', #swapExactETHForTOkens
            #'791ac947', #swapExactETHForTOkens
            #'38ed1739', #swapExactETHForTOkens
            #'4a25d94a', #swapExactETHForTOkens
        ]
        
        for sig in swap_signatures:
            if input_data.startswith(sig):
                return True
        return False
            
    async def handle_pending_tx_async(self, transaction):
        """Parse swap transaction details"""
        
        try:
                        
            print(transaction['hash'])
            
            
            # Check if transaction is to Uniswap Router
            if not transaction['to'] or transaction['to'].lower() != self.router_address.lower():
                return None
                        
            # Check if transaction has swap method signatures
            input_data = transaction['input']
            
            swap_flag = self.check_swap(input_data)         
            
            if swap_flag == False:
                return None
            
            print("swap tx")  
                        
            swap_info = {
                'tx_hash': transaction['hash'],
                'block_number': transaction['blockNumber'],
                'from_address': transaction['from'],
                'to_address': transaction['to'],
                'gas_price': transaction['gasPrice'],
                'value': transaction['value'],  # ETH value sent
                'out': int(input_data[8:72], 16),
                'token': input_data[8+64*5:]
            }
            
            print(swap_info['tx_hash'])
            print(f"eth value: {swap_info['value']}")
            print(f"token amount: {swap_info['out']}")
                        
            if swap_info['value'] < self.filter_volume:
                return None
                        
            
            
            
            
                       
            
        except Exception as e:
            logging.error(f"Error parsing transaction {transaction['hash']}: {e}")
            return None
            
    async def subscribe_to_pending_txs(self, websocket):
        subscription = {
            "jsonrpc": "2.0", 
            "method": "eth_subscribe",
            "params": [
                "alchemy_pendingTransactions",
                {
                    "toAddress": [self.router_address], 
                    "hashesOnly": False
                }
            ],
            "id": 1
        }
        await websocket.send(json.dumps(subscription))
        response = await websocket.recv()
        print(f"Subscription confirmed: {response}")
    
    async def listen_for_transactions(self, websocket):
        async for message in websocket:
            try:
                data = json.loads(message)
                if 'params' in data and 'result' in data['params']:
                    transaction = data['params']['result']
                    asyncio.create_task(self.handle_pending_tx_async(transaction))
            except Exception as e:
                print(f"Error processing message: {e}")

    async def monitor_mempool(self):
        """Monitor mempool for pending Uniswap transactions (requires WebSocket)"""
        logging.info("Monitoring mempool for Uniswap swaps...")
        
        print(f"why? {self.w3soc}")
        
        while True:
            try:
                async with websockets.connect(self.w3soc) as websocket:
                    await self.subscribe_to_pending_txs(websocket)
                    await self.listen_for_transactions(websocket)
            except Exception as e:
                print(f"WebSocket connection failed: {e}")
                print("Reconnecting in 5 seconds...")
                await asyncio.sleep(5)

    def handle_swap_detected(self, swap_info):
        return None