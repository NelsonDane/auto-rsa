import asyncio
from tastyRSAAPI import *


tastytrade_session = tastytrade_init('maxxrk', 'Yq%FF0e8WG#VGS')
print(tastytrade_session)

loop = asyncio.get_event_loop()

loop.run_until_complete(tastytrade_holdings(tastytrade_session, ctx=None))
loop.run_until_complete(tastytrade_transaction(tastytrade_session=tastytrade_session, action='sell', stock='ARVL', amount=1, time='', DRY=False))