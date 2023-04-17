import aiohttp

class Security(object):
    def __init__(self, ticker: str):
        self.ticker = ticker
        self.url = f'https://vast.tastyworks.com/nbbo-snapshot/{ticker}'
        self.symbol = str
        self.last = str
        self.last_exchange_code = str
        self.last_size = str
        self.bid = str
        self.bid_exchange_code = str
        self.bid_size = str
        self.ask = str
        self.ask_exchange_code = str
        self.ask_size = str

    
    async def get_security_price(self, session):
        print(self.ticker)
        print(self.url)
        async with aiohttp.request('GET', url=self.url, headers=session.get_request_headers()) as response:
            if response.status != 200:
                raise Exception('Could not get live orders info from Tastyworks...')
            data = (await response.json())['data']['items']
            # parse the data
            data = data[0]
            self.symbol = data['symbol']
            self.last = data['last']
            self.last_exchange_code = data['last-exchange-code']
            self.last_size = data['last-size']
            self.bid = data['bid']
            self.bid_exchange_code = data['bid-exchange-code']
            self.bid_size = data['bid-size']
            self.ask = data['ask']
            self.ask_exchange_code = data['ask-exchange-code']
            self.ask_size = data['ask-size']
