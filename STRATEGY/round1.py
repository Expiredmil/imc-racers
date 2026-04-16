from datamodel import OrderDepth, TradingState, Order
from logger import logger
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
PEPPER_SKEW_COEF = 0.05          # fair-value push per unit of inventory
PEPPER_HEAVY_POS = 30            # |pos| above this → symmetric thresholds
PEPPER_BUY_EDGE = 0              # take buys when ap < fair - BUY_EDGE
PEPPER_SELL_EDGE = 2             # take sells when bp > fair + SELL_EDGE
PEPPER_OPEN_SAMPLES = 20         # update day_open over first N ticks, then freeze
PEPPER_VERY_HEAVY_POS = 35       # |pos| above this → widen quotes
PEPPER_HEAVY_WIDEN = 2           # tick count to back off quote on heavy side

# OSMIUM parameters
OSMIUM_EMA_WINDOW = 40
OSMIUM_SKEW_COEF = 0.05          # fair-value push per unit of inventory
OSMIUM_OFI_COEF = -0.05          # negative = fade momentum (mean-reversion)
OSMIUM_OFI_EMA = 10              # EMA window for OFI smoothing


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

        vwm = self.vw_mid()
        if vwm is not None:
            self.vw_ema_mid = self.calculate_ema("osm_vw_ema", OSMIUM_EMA_WINDOW, vwm)
        else:
            self.vw_ema_mid = self.last_traderData.get("osm_vw_ema", None)

        # OFI: Order Flow Imbalance (Cont, Kukanov & Stoikov 2014)
        self.ofi = self._compute_ofi()
        if self.ofi is not None:
            self.ofi_ema = self.calculate_ema("osm_ofi_ema", OSMIUM_OFI_EMA, self.ofi)
        else:
            self.ofi_ema = self.last_traderData.get("osm_ofi_ema", 0)

        # Store current best bid/ask for next tick's OFI
        if self.best_bid is not None:
            self.new_trader_data["osm_prev_bb"] = self.best_bid
            self.new_trader_data["osm_prev_bv"] = self.mkt_buy_orders.get(self.best_bid, 0)
        if self.best_ask is not None:
            self.new_trader_data["osm_prev_ap"] = self.best_ask
            self.new_trader_data["osm_prev_av"] = self.mkt_sell_orders.get(self.best_ask, 0)

        self.log("vw_ema_mid", self.vw_ema_mid)
        self.log("ofi", self.ofi)
        self.log("ofi_ema", self.ofi_ema)
        self.log("position", self.initial_position)

    def _compute_ofi(self):
        """Order Flow Imbalance: tracks changes in best bid/ask volume to detect pressure."""
        prev_bb = self.last_traderData.get("osm_prev_bb")
        prev_bv = self.last_traderData.get("osm_prev_bv")
        prev_ap = self.last_traderData.get("osm_prev_ap")
        prev_av = self.last_traderData.get("osm_prev_av")

        if any(v is None for v in [prev_bb, prev_bv, prev_ap, prev_av]):
            return None
        if self.best_bid is None or self.best_ask is None:
            return None

        curr_bv = self.mkt_buy_orders.get(self.best_bid, 0)
        curr_av = self.mkt_sell_orders.get(self.best_ask, 0)

        # Bid side: price up → new demand, same → volume change, down → demand withdrew
        if self.best_bid > prev_bb:
            bid_ofi = curr_bv
        elif self.best_bid == prev_bb:
            bid_ofi = curr_bv - prev_bv
        else:
            bid_ofi = -prev_bv

        # Ask side: price down → new supply, same → volume change, up → supply withdrew
        if self.best_ask < prev_ap:
            ask_ofi = -curr_av
        elif self.best_ask == prev_ap:
            ask_ofi = -(curr_av - prev_av)
        else:
            ask_ofi = prev_av

        return bid_ofi + ask_ofi

    def get_orders(self):
        if self.vw_ema_mid is None or self.bid_wall is None or self.ask_wall is None:
            return {self.name: self.orders}

        skew = -OSMIUM_SKEW_COEF * self.initial_position
        ofi_adj = OSMIUM_OFI_COEF * self.ofi_ema
        fair = self.vw_ema_mid + skew + ofi_adj
        self.log("fair_skewed", fair)

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

        # Robust day_open: Welford-style running mean over first N ticks, then frozen.
        n = self.last_traderData.get("pep_open_n", 0)
        stored_open = self.last_traderData.get("pep_day_open")

        if n >= PEPPER_OPEN_SAMPLES:
            self.day_open = stored_open
        elif self.wall_mid is not None:
            n += 1
            if stored_open is None:
                self.day_open = self.wall_mid
            else:
                self.day_open = stored_open + (self.wall_mid - stored_open) / n
            self.new_trader_data["pep_day_open"] = self.day_open
            self.new_trader_data["pep_open_n"] = n
        else:
            self.day_open = stored_open

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

        skew = -PEPPER_SKEW_COEF * self.initial_position
        fair = self.fair_value + skew
        self.log("fair_skewed", fair)
        self.log("skew", skew)

        sell_threshold = fair + PEPPER_SELL_EDGE if self.initial_position < PEPPER_HEAVY_POS else fair
        buy_threshold = fair - PEPPER_BUY_EDGE if self.initial_position > -PEPPER_HEAVY_POS else fair

        for ap, av in self.mkt_sell_orders.items():
            if ap < buy_threshold:
                self.bid(ap, av)

        for bp, bv in self.mkt_buy_orders.items():
            if bp > sell_threshold:
                self.ask(bp, bv)

        bid_price = int(self.bid_wall) + 1
        ask_price = int(self.ask_wall) - 1

        bid_price = min(bid_price, int(fair) - 1)
        ask_price = max(ask_price, int(fair) + 2)

        if self.initial_position > PEPPER_VERY_HEAVY_POS:
            bid_price -= PEPPER_HEAVY_WIDEN
        elif self.initial_position < -PEPPER_VERY_HEAVY_POS:
            ask_price += PEPPER_HEAVY_WIDEN

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

        logger.print(json.dumps(prints))
        logger.flush(state, result, 0, td)

        return result, 0, td
    
if __name__ == "__main__":
    import sys, os
    from datetime import datetime
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, root)
    os.chdir(root)
    from prosperity4bt.__main__ import main
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    round_num = 1
    for day in ["-2", "-1", "0"]:
        out_dir = f"BACKTESTS/round{round_num}/day{day}"
        os.makedirs(out_dir, exist_ok=True)
        sys.argv = [
            "prosperity4bt", __file__, f"{round_num}-{day}",
            "--data", "DATA",
            "--no-progress",
            "--out", f"{out_dir}/{ts}.log",
        ]
        try:
            main()
        except SystemExit:
            pass