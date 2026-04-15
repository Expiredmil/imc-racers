from datamodel import OrderDepth, TradingState, Order
import json

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

OSMIUM = "ASH_COATED_OSMIUM"
PEPPER = "INTARIAN_PEPPER_ROOT"

POS_LIMITS = {
    OSMIUM: 50,
    PEPPER: 50,
}

# PEPPER trend parameters (from data analysis: ~+1000 drift per day over 1M ts)
PEPPER_DAILY_DRIFT = 1000
PEPPER_MAX_TIMESTAMP = 1_000_000

# OSMIUM EMA parameter (window=40 corresponds to alpha ≈ 0.05)
OSMIUM_EMA_WINDOW = 40


# ─────────────────────────────────────────────────────────────────────────────
# BASE CLASS
# ─────────────────────────────────────────────────────────────────────────────

class ProductTrader:
    def __init__(self, name, state, prints, new_trader_data):
        self.orders = []
        self.name = name
        self.state = state
        self.prints = prints
        self.new_trader_data = new_trader_data

        self.last_traderData = self._load_traderData()

        self.position_limit = POS_LIMITS.get(self.name, 0)
        self.initial_position = self.state.position.get(self.name, 0)

        self.mkt_buy_orders, self.mkt_sell_orders = self._get_order_depth()
        self.bid_wall, self.wall_mid, self.ask_wall = self._get_walls()
        self.best_bid, self.best_ask = self._get_best_bid_ask()

        self.max_allowed_buy_volume, self.max_allowed_sell_volume = self._get_max_allowed_volume()

    def _load_traderData(self):
        if self.state.traderData:
            try:
                return json.loads(self.state.traderData)
            except Exception:
                return {}
        return {}

    def _get_order_depth(self):
        buy_orders, sell_orders = {}, {}
        try:
            od: OrderDepth = self.state.order_depths[self.name]
            buy_orders = {p: abs(v) for p, v in sorted(od.buy_orders.items(), reverse=True)}
            sell_orders = {p: abs(v) for p, v in sorted(od.sell_orders.items())}
        except Exception:
            pass
        return buy_orders, sell_orders

    def _get_best_bid_ask(self):
        best_bid = max(self.mkt_buy_orders.keys()) if self.mkt_buy_orders else None
        best_ask = min(self.mkt_sell_orders.keys()) if self.mkt_sell_orders else None
        return best_bid, best_ask

    def _get_walls(self):
        bid_wall = min(self.mkt_buy_orders.keys()) if self.mkt_buy_orders else None
        ask_wall = max(self.mkt_sell_orders.keys()) if self.mkt_sell_orders else None
        wall_mid = (bid_wall + ask_wall) / 2 if (bid_wall is not None and ask_wall is not None) else None
        return bid_wall, wall_mid, ask_wall

    def _get_max_allowed_volume(self):
        return self.position_limit - self.initial_position, self.position_limit + self.initial_position

    def bid(self, price, volume):
        vol = min(abs(int(volume)), self.max_allowed_buy_volume)
        if vol <= 0:
            return
        self.orders.append(Order(self.name, int(price), vol))
        self.max_allowed_buy_volume -= vol

    def ask(self, price, volume):
        vol = min(abs(int(volume)), self.max_allowed_sell_volume)
        if vol <= 0:
            return
        self.orders.append(Order(self.name, int(price), -vol))
        self.max_allowed_sell_volume -= vol

    def calculate_ema(self, key, window, value):
        old = self.last_traderData.get(key, value)
        alpha = 2 / (window + 1)
        new = alpha * value + (1 - alpha) * old
        self.new_trader_data[key] = new
        return new

    def vw_mid(self):
        def vw_side(orders):
            if not orders:
                return None
            total = sum(orders.values())
            return sum(p * v for p, v in orders.items()) / total if total > 0 else None
        wb = vw_side(self.mkt_buy_orders)
        wa = vw_side(self.mkt_sell_orders)
        if wb is None or wa is None:
            return None
        return (wb + wa) / 2

    def log(self, key, value):
        bucket = self.prints.setdefault(self.name, {})
        bucket[key] = value

    def get_orders(self):
        return {self.name: self.orders}


# ─────────────────────────────────────────────────────────────────────────────
# OSMIUM — mean-reversion market maker around 10000
# ─────────────────────────────────────────────────────────────────────────────

class OsmiumTrader(ProductTrader):
    def __init__(self, state, prints, new_trader_data):
        super().__init__(OSMIUM, state, prints, new_trader_data)

        # Two mid methods computed every tick so we can compare
        self.simple_wall_mid = self.wall_mid  # (bid_wall + ask_wall) / 2 — prior-year approach

        vwm = self.vw_mid()
        if vwm is not None:
            self.vw_ema_mid = self.calculate_ema("osm_vw_ema", OSMIUM_EMA_WINDOW, vwm)
        else:
            self.vw_ema_mid = self.last_traderData.get("osm_vw_ema", None)

        # Log both for later comparison
        self.log("simple_wall_mid", self.simple_wall_mid)
        self.log("vw_ema_mid", self.vw_ema_mid)
        self.log("position", self.initial_position)

    def get_orders(self):
        fair = self.vw_ema_mid  # PRIMARY fair value
        if fair is None or self.bid_wall is None or self.ask_wall is None:
            return {self.name: self.orders}

        # ── 1) TAKING: aggressively hit mispriced quotes
        for ap, av in self.mkt_sell_orders.items():
            if ap <= fair - 1:
                self.bid(ap, av)
            elif ap <= fair and self.initial_position < 0:
                self.bid(ap, min(av, abs(self.initial_position)))

        for bp, bv in self.mkt_buy_orders.items():
            if bp >= fair + 1:
                self.ask(bp, bv)
            elif bp >= fair and self.initial_position > 0:
                self.ask(bp, min(bv, self.initial_position))

        # ── 2) MAKING: post just inside the walls
        bid_price = int(self.bid_wall) + 1
        ask_price = int(self.ask_wall) - 1

        # Overbid best bid if there's room below fair
        for bp, bv in self.mkt_buy_orders.items():
            if bv > 1 and bp + 1 < fair:
                bid_price = max(bid_price, bp + 1)
                break
            elif bp < fair:
                bid_price = max(bid_price, bp)
                break

        # Underbid best ask if there's room above fair
        for ap, av in self.mkt_sell_orders.items():
            if av > 1 and ap - 1 > fair:
                ask_price = min(ask_price, ap - 1)
                break
            elif ap > fair:
                ask_price = min(ask_price, ap)
                break

        self.bid(bid_price, self.max_allowed_buy_volume)
        self.ask(ask_price, self.max_allowed_sell_volume)

        return {self.name: self.orders}


# ─────────────────────────────────────────────────────────────────────────────
# PEPPER — linear trend, long-biased
# ─────────────────────────────────────────────────────────────────────────────

class PepperTrader(ProductTrader):
    def __init__(self, state, prints, new_trader_data):
        super().__init__(PEPPER, state, prints, new_trader_data)

        # Capture day_open at timestamp 0, persist across ticks within the day
        stored_open = self.last_traderData.get("pep_day_open")
        if self.state.timestamp == 0 and self.wall_mid is not None:
            self.day_open = self.wall_mid
        elif stored_open is not None:
            self.day_open = stored_open
        else:
            self.day_open = self.wall_mid  # fallback for mid-day starts

        if self.day_open is not None:
            self.new_trader_data["pep_day_open"] = self.day_open

        # Fair value = day_open + linear drift
        if self.day_open is not None:
            self.fair_value = self.day_open + (self.state.timestamp / PEPPER_MAX_TIMESTAMP) * PEPPER_DAILY_DRIFT
        else:
            self.fair_value = None

        self.log("day_open", self.day_open)
        self.log("fair_value", self.fair_value)
        self.log("wall_mid", self.wall_mid)
        self.log("position", self.initial_position)

    def get_orders(self):
        if self.fair_value is None or self.bid_wall is None or self.ask_wall is None:
            return {self.name: self.orders}

        fair = self.fair_value

        # ── 1) TAKING: aggressively buy anything meaningfully below fair,
        #              sell only when well above fair (long bias)
        for ap, av in self.mkt_sell_orders.items():
            if ap < fair - 1:
                self.bid(ap, av)

        for bp, bv in self.mkt_buy_orders.items():
            if bp > fair + 2:   # wider threshold on sell side to keep long
                self.ask(bp, bv)

        # ── 2) MAKING: long-biased quotes
        bid_price = int(self.bid_wall) + 1
        ask_price = int(self.ask_wall) - 1

        bid_price = min(bid_price, int(fair) - 1)
        ask_price = max(ask_price, int(fair) + 2)

        self.bid(bid_price, self.max_allowed_buy_volume)
        self.ask(ask_price, self.max_allowed_sell_volume)

        return {self.name: self.orders}


# ─────────────────────────────────────────────────────────────────────────────
# MAIN TRADER — routes each product to its strategy class
# ─────────────────────────────────────────────────────────────────────────────

class Trader:
    def run(self, state: TradingState):
        result: dict = {}
        new_trader_data: dict = {}
        prints: dict = {
            "timestamp": state.timestamp,
            "position": dict(state.position),
        }

        product_traders = {
            OSMIUM: OsmiumTrader,
            PEPPER: PepperTrader,
        }

        for symbol, cls in product_traders.items():
            if symbol in state.order_depths:
                try:
                    t = cls(state, prints, new_trader_data)
                    result.update(t.get_orders())
                except Exception as e:
                    print(f"ERROR {symbol}: {e}")

        try:
            td = json.dumps(new_trader_data)
        except Exception:
            td = ""

        try:
            print(json.dumps(prints))
        except Exception:
            pass

        return result, 0, td