import json


class Logger:
    def __init__(self):
        self.logs = ""

    def print(self, *args, sep=" ", end="\n"):
        self.logs += sep.join(str(a) for a in args) + end

    def flush(self, state, orders, conversions, trader_data):
        compressed_state = [
            state.timestamp,
            state.traderData,
            [[l.symbol, l.product, l.denomination] for l in state.listings.values()],
            {s: [od.buy_orders, od.sell_orders] for s, od in state.order_depths.items()},
            [[t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp]
             for trades in state.own_trades.values() for t in trades],
            [[t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp]
             for trades in state.market_trades.values() for t in trades],
            dict(state.position),
            [{}, {}],
        ]

        compressed_orders = []
        for symbol, order_list in orders.items():
            for order in order_list:
                compressed_orders.append([order.symbol, order.price, order.quantity])

        row = [
            compressed_state,
            compressed_orders,
            conversions,
            trader_data,
            self.logs,
        ]

        print(json.dumps(row, separators=(",", ":")))
        self.logs = ""


logger = Logger()
