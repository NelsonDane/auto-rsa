import csv
import time

from datetime import datetime, timedelta
from helperAPI import printAndDiscord, maskString, Brokerage
from robin_stocks.robinhood import orders as rh_orders

class OrderManager:
    def __init__(self, brokerage: Brokerage):
        self.brokerage = brokerage

    def get_orders(self, key: str, account: str):
        try:
            all_orders = rh_orders.get_all_stock_orders()
            return all_orders
        except Exception as e:
            print(f"Error fetching orders for {key}: {e}")
            return []

    def get_order_details(self, order_id: str):
        try:
            order_info = rh_orders.get_stock_order_info(order_id)
            if order_info is None:
                print(f"Order info is None for order ID: {order_id}")
                return {}
            return order_info
        except Exception as e:
            print(f"Error fetching details for order {order_id}: {e}")
            return {}

    def filter_orders_by_date(self, orders, start_date, end_date):
        filtered_orders = []
        for order in orders:
            for execution in order.get('executions', []):
                execution_date = datetime.fromisoformat(execution['timestamp'].replace('Z', '+00:00')).date()
                if start_date <= execution_date <= end_date:
                    filtered_orders.append(order)
                    break  # Stop checking other executions for this order
        return filtered_orders
        printAndDiscord(filtered_orders)
    def print_order_totals(self, totals, title):
        print(f"\nTotals for {title}:")
        for symbol, data in totals.items():
            quantity = round(data['quantity'], 1)
            total_value = round(data['total_value'], 2)
            printAndDiscord(f"{symbol}: Quantity: {quantity} Total Value: ${total_value:.2f}")
    def get_ticker_from_instrument_url(self, instrument_url):
        try:
            response = self.brokerage.get_instrument_details(instrument_url)  # Adjust this according to your API
            return response.get('symbol', 'Unknown')
        except Exception as e:
            print(f"Error fetching instrument details from {instrument_url}: {e}")
            return 'Unknown'
    def totals_to_csv(self, loop=None, days=1, csv_filename="orders.csv"):
        today = datetime.now().date()
        start_date = today - timedelta(days=days)
        printAndDiscord(f"Processing orders from {start_date} to {today}", loop)

        totals = {"buy": {}, "sell": {}}
        orders_by_symbol = {}  # To track orders by symbol
        orders_to_save = []

        for key in self.brokerage.get_account_numbers():
            for account in self.brokerage.get_account_numbers(key):
                all_orders = self.get_orders(key, account)
                stock_orders_filtered = self.filter_orders_by_date(all_orders, start_date, today)

                for order in stock_orders_filtered:
                    order_id = order.get('id')
                    order_details = self.get_order_details(order_id)
                    if not order_details:
                        continue  # Skip if details are not available

                        # Check if the order is filled
                    if order_details.get('state', '') != 'filled':
                        continue  # Skip orders that are not fully filled

                    # Handle the instrument key safely
                    instrument = order_details.get('instrument', {})
                    if isinstance(instrument, str):
                        # `instrument` is likely a URL; you may need to make an additional request here
                        ticker_symbol = self.get_ticker_from_instrument_url(instrument)
                    elif isinstance(instrument, dict):
                        ticker_symbol = instrument.get('symbol', 'Unknown')
                    else:
                        ticker_symbol = 'Unknown'

                    if ticker_symbol == 'Unknown':
                        print(f"Warning: Could not retrieve ticker symbol for order ID {order_id}.")
                    quantity_str = order_details.get('cumulative_quantity', '0')
                    average_price_str = order_details.get('average_price', '0')

                    quantity = float(quantity_str or '0')
                    average_price = float(average_price_str or '0')
                    order_type = order_details.get('side', 'buy')

                    if order_type not in totals:
                        totals[order_type] = {}

                    if ticker_symbol not in totals[order_type]:
                        totals[order_type][ticker_symbol] = {"quantity": 0, "total_value": 0}

                    totals[order_type][ticker_symbol]["quantity"] += quantity
                    totals[order_type][ticker_symbol]["total_value"] += quantity * average_price

                    # Track orders by symbol
                    if ticker_symbol not in orders_by_symbol:
                        orders_by_symbol[ticker_symbol] = []
                    orders_by_symbol[ticker_symbol].append({
                        "account": f"{key} ({self.maskString(account)})",
                        "quantity": quantity,
                        "average_price": average_price,
                        "side": order_type,
                        "timestamp": order_details.get('timestamp', 'N/A')
                    })

                    orders_to_save.append({
                        "account": f"{key} ({self.maskString(account)})",
                        "symbol": ticker_symbol,
                        "quantity": quantity,
                        "average_price": average_price,
                        "side": order_type,
                        "timestamp": order_details.get('timestamp', 'N/A')
                    })

        # Print totals
        for action in ["buy", "sell"]:
            printAndDiscord(f"\nTotals for {action}:", loop)
            for symbol, details in totals[action].items():
                printAndDiscord(f"{symbol}: Quantity: {details['quantity']} Total Value: ${details['total_value']:.2f}", loop)

        # Print orders grouped by symbol
        printAndDiscord("\nOrders grouped by symbol:", loop)
        for symbol, orders in orders_by_symbol.items():
            printAndDiscord(f"\n{symbol}:", loop)
            for order in orders:
                printAndDiscord(f"Account: {order['account']} | Quantity: {order['quantity']} | Average Price: ${order['average_price']:.2f} | Side: {order['side']} | Timestamp: {order['timestamp']}", loop)

        # Save orders to CSV
        with open(csv_filename, mode='w', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=["account", "symbol", "quantity", "average_price", "side", "timestamp"])
            writer.writeheader()
            writer.writerows(orders_to_save)

        printAndDiscord(f"Orders saved to {csv_filename}", loop)

    def maskString(self, account):
        return f"xxxx{account[-4:]}"
