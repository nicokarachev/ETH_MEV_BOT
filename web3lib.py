import os
import logging
import asyncio
import websockets
import json
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
        router_address = "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D", 
        factory_address = "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f",
        swap_event_signature = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822",
        filter_volume = 2.5,
        filter_slippage = 5
        ):
        """
        Monitor Uniswap V2 swap transactions
        
        Args:
            web3_provider: Web3 HTTP/WebSocket provider URL
        """
        self.w3 = Web3(Web3.HTTPProvider(web3_provider))
        
        if not self.w3.is_connected():
            print("❌ Connection failed")
            exit()

        print("✅ Connected to Ethereum mainnet")

        self.w3soc = web3_provicer_socket
                
        # Uniswap V2 Router address
        self.router_address = router_address
        
        # Uniswap V2 Factory address
        self.factory_address = factory_address
        
        # Event signatures (keccak256 hashes)
        self.swap_event_signature = swap_event_signature
        
        # Transaction Volume Thresold(Ether amount, over $10k)
        self.filter_volume = filter_volume
        
        # Slippage Thresold(percentage, 5 is 0.5%)
        self.filter_slippage = filter_slippage
        
        # ABI for parsing events
        self.pair_abi = [
            {
                "anonymous": False,
                "inputs": [
                    {"indexed": True, "name": "sender", "type": "address"},
                    {"indexed": False, "name": "amount0In", "type": "uint256"},
                    {"indexed": False, "name": "amount1In", "type": "uint256"},
                    {"indexed": False, "name": "amount0Out", "type": "uint256"},
                    {"indexed": False, "name": "amount1Out", "type": "uint256"},
                    {"indexed": True, "name": "to", "type": "address"}
                ],
                "name": "Swap",
                "type": "event"
            }
        ]
        
        self.router_abi = [
            {
                "inputs": [
                    {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                    {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
                    {"internalType": "address[]", "name": "path", "type": "address[]"},
                    {"internalType": "address", "name": "to", "type": "address"},
                    {"internalType": "uint256", "name": "deadline", "type": "uint256"}
                ],
                "name": "swapExactTokensForTokens",
                "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
                "stateMutability": "nonpayable",
                "type": "function"
            },
            {
                "inputs": [
                    {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
                    {"internalType": "address[]", "name": "path", "type": "address[]"},
                    {"internalType": "address", "name": "to", "type": "address"},
                    {"internalType": "uint256", "name": "deadline", "type": "uint256"}
                ],
                "name": "swapExactETHForTokens",
                "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
                "stateMutability": "payable",
                "type": "function"
            }
        ]
      
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
            
    async def handle_pending_tx_async(self, tx_hash):
        """Parse swap transaction details"""
        
        try:
            # Get transaction and receipt
            transaction = self.w3.eth.get_transaction(tx_hash)
            receipt = self.w3.eth.get_transaction_receipt(tx_hash)
            
            # Check if transaction is to Uniswap Router
            if not transaction['to'] or transaction['to'].lower() != self.router_address.lower():
                return None
            
            print(transaction)
            
            # Check if transaction has swap method signatures
            input_data = transaction['input'].hex()
            
            swap_flag = self.check_swap(input_data)           
            
            if swap_flag == False:
                return None
                                    
            swap_info = {
                'tx_hash': tx_hash,
                'block_number': transaction['blockNumber'],
                'from_address': transaction['from'],
                'to_address': transaction['to'],
                'gas_price': transaction['gasPrice'],
                'value': transaction['value'],  # ETH value sent
                'swaps': []
            }
            
        except Exception as e:
            logging.error(f"Error parsing transaction {tx_hash}: {e}")
            return None
            
    async def subscribe_to_pending_txs(self, websocket):
        subscription = {
            "jsonrpc": "2.0",
            "method": "eth_subscribe",
            "params": ["newPendingTransactions"],
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
                    tx_hash = data['params']['result']
                    asyncio.create_task(self.handle_pending_tx_async(tx_hash))
            except Exception as e:
                print(f"Error processing message: {e}")

    async def monitor_mempool(self):
        """Monitor mempool for pending Uniswap transactions (requires WebSocket)"""
        logging.info("Monitoring mempool for Uniswap swaps...")
        
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
        """Handle detected swap transaction"""
        logging.info(f"🔄 SWAP DETECTED!")
        logging.info(f"   TX Hash: {swap_info['tx_hash']}")
        logging.info(f"   Block: {swap_info['block_number']}")
        logging.info(f"   From: {swap_info['from_address']}")
        logging.info(f"   Gas Used: {swap_info['gas_used']:,}")
        
        for i, swap in enumerate(swap_info['swaps']):
            logging.info(f"   Swap {i+1}:")
            logging.info(f"     Pair: {swap['pair_address']}")
            logging.info(f"     Amount0In: {swap['amount0In']:,}")
            logging.info(f"     Amount1In: {swap['amount1In']:,}")
            logging.info(f"     Amount0Out: {swap['amount0Out']:,}")
            logging.info(f"     Amount1Out: {swap['amount1Out']:,}")
        
        logging.info("-" * 50)
        
        # Add your custom logic here
        # For example: save to database, send alerts, analyze patterns, etc.

        """Monitor swaps for a specific pair"""
        self.specific_pair = pair_address.lower()
        logging.info(f"Monitoring specific pair: {pair_address}")
        
        # Create filter for Swap events on specific pair
        try:
            swap_filter = self.w3.eth.filter({
                'address': pair_address,
                'topics': [self.swap_event_signature]
            })
            
            logging.info(f"Created filter for pair {pair_address}")
            
            while True:
                try:
                    # Get new swap events
                    for log in swap_filter.get_new_entries():
                        swap_data = self.decode_swap_event(log)
                        if swap_data:
                            logging.info(f"🔄 Pair swap detected:")
                            logging.info(f"   Pair: {swap_data['pair_address']}")
                            logging.info(f"   Amounts In: {swap_data['amount0In']}, {swap_data['amount1In']}")
                            logging.info(f"   Amounts Out: {swap_data['amount0Out']}, {swap_data['amount1Out']}")
                    
                    asyncio.sleep(1)
                    
                except Exception as e:
                    logging.error(f"Filter error: {e}")
                    asyncio.sleep(5)
                    
        except KeyboardInterrupt:
            logging.info("Stopping pair monitoring...")