"""
deriv_live_client.py

Authenticated Deriv WebSocket client for paper and live trade execution.

Supports:
  - Account authorization with API token (`authorize`)
  - Real-time contract proposal generation (`proposal`)
  - Order execution (`buy` / `sell`)
  - Paper trading simulation mode (`--paper`)
"""

import asyncio
import json
import ssl
import sys
from typing import Dict, Any, Optional
import websockets

DERIV_WS_URL = "wss://ws.derivws.com/websockets/v3?app_id={app_id}"


class DerivLiveClient:
    """
    Authenticated client for executing trade proposals and orders on Deriv.
    """

    def __init__(self, api_token: str = "", app_id: str = "1089", paper_mode: bool = True):
        self.api_token = api_token
        self.app_id = app_id
        self.paper_mode = paper_mode
        self.ws_url = DERIV_WS_URL.format(app_id=app_id)
        self.authorized = False
        self.account_info: Dict[str, Any] = {}

    def _get_ssl_context(self):
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        return ssl_context

    async def connect_and_authorize(self) -> bool:
        """
        Establishes WebSocket connection and authorizes using API token.
        """
        if self.paper_mode and not self.api_token:
            print("[DerivLiveClient] Paper Mode: Running in simulated execution environment (no live token required).")
            self.authorized = True
            self.account_info = {"email": "paper_trader@deriv.sim", "currency": "USD", "balance": 10000.0}
            return True

        if not self.api_token:
            raise ValueError("API token is required for live account authorization.")

        async with websockets.connect(self.ws_url, ssl=self._get_ssl_context()) as ws:
            auth_msg = {"authorize": self.api_token}
            await ws.send(json.dumps(auth_msg))
            resp = json.loads(await ws.recv())

            if "error" in resp:
                raise RuntimeError(f"Authorization failed: {resp['error'].get('message')}")

            self.authorized = True
            self.account_info = resp.get("authorize", {})
            print(f"[DerivLiveClient] Authorized successfully for account: {self.account_info.get('email')} (Balance: ${self.account_info.get('balance')})")
            return True

    async def execute_trade(
        self,
        symbol: str,
        contract_type: str,  # 'CALL' (Buy/Long) or 'PUT' (Sell/Short)
        stake: float,
        duration: int = 5,
        duration_unit: str = "m",
    ) -> Dict[str, Any]:
        """
        Requests a trade proposal and buys contract.
        """
        if not self.authorized:
            await self.connect_and_authorize()

        if self.paper_mode and not self.api_token:
            # Paper execution simulator
            await asyncio.sleep(0.2)
            contract_id = f"PAPER_{int(asyncio.get_event_loop().time() * 1000)}"
            print(f"[PAPER TRADING] Executed {contract_type} contract on '{symbol}' for ${stake:.2f} (Duration: {duration}{duration_unit}). Contract ID: {contract_id}")
            return {
                "status": "success",
                "mode": "PAPER",
                "contract_id": contract_id,
                "symbol": symbol,
                "contract_type": contract_type,
                "stake": stake,
            }

        async with websockets.connect(self.ws_url, ssl=self._get_ssl_context()) as ws:
            # 1. Authorize connection
            await ws.send(json.dumps({"authorize": self.api_token}))
            await ws.recv()

            # 2. Get trade proposal
            proposal_req = {
                "proposal": 1,
                "amount": stake,
                "basis": "stake",
                "contract_type": contract_type.upper(),
                "currency": "USD",
                "symbol": symbol,
                "duration": duration,
                "duration_unit": duration_unit,
            }
            await ws.send(json.dumps(proposal_req))
            prop_resp = json.loads(await ws.recv())

            if "error" in prop_resp:
                raise RuntimeError(f"Proposal error: {prop_resp['error'].get('message')}")

            proposal_id = prop_resp["proposal"]["id"]
            ask_price = prop_resp["proposal"]["ask_price"]

            # 3. Execute Buy
            buy_req = {"buy": proposal_id, "price": ask_price}
            await ws.send(json.dumps(buy_req))
            buy_resp = json.loads(await ws.recv())

            if "error" in buy_resp:
                raise RuntimeError(f"Order placement error: {buy_resp['error'].get('message')}")

            receipt = buy_resp.get("buy", {})
            print(f"[LIVE TRADING] Order placed! Contract ID: {receipt.get('contract_id')} Purchased for ${receipt.get('buy_price')}")
            return {
                "status": "success",
                "mode": "LIVE",
                "contract_id": receipt.get("contract_id"),
                "symbol": symbol,
                "contract_type": contract_type,
                "stake": stake,
                "buy_price": receipt.get("buy_price"),
            }


if __name__ == "__main__":
    # Test execution in paper mode
    print("=== Testing Deriv Live/Paper Client ===")
    client = DerivLiveClient(paper_mode=True)
    res = asyncio.run(client.execute_trade(symbol="R_75", contract_type="CALL", stake=10.0, duration=5, duration_unit="m"))
    print(res)
