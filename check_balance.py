from kalshi_client import KalshiClient
client = KalshiClient()
balance = client.get_balance()
print(f"Current Kalshi Balance: ${balance:.2f}")
