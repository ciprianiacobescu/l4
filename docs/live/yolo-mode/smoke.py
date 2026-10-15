"""End-to-end smoke of the integrated dummy: every feature of the ten specs, with the specs' own examples,
used together.
Run from the repository root with the project's interpreter: python smoke.py (src/ is put on the path)."""

import importlib
import pkgutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "src"))
checks = 0


def check(label, got, want):
    global checks
    assert got == want, f"{label}: got {got!r}, want {want!r}"
    checks += 1


def raises(label, fn):
    global checks
    try:
        fn()
    except ValueError:
        checks += 1
        return
    raise AssertionError(f"{label}: no ValueError")


# every module imports
mods = []
for pkg in ("pricing", "inventory", "billing"):
    p = importlib.import_module(pkg)
    for m in pkgutil.iter_modules(p.__path__):
        mods.append(importlib.import_module(f"{pkg}.{m.name}").__name__)
print("imported:", ", ".join(sorted(mods)))

from billing.invoice import invoice_line, invoice_lines  # noqa: E402
from inventory.ledger import StockLedger  # noqa: E402
from inventory.shelf import shelf_label  # noqa: E402
from inventory.summary import valuation_summary  # noqa: E402
from inventory.valuation import stock_value  # noqa: E402
from pricing.money import from_cents  # noqa: E402
from pricing.vat import vat_cents  # noqa: E402

# A add-money-format, C add-vat
check("from_cents(1234)", str(from_cents(1234)), "12.34")
check("from_cents(-5)", str(from_cents(-5)), "-0.05")
check("from_cents(0)", str(from_cents(0)), "0.00")
check("vat_cents(1999, 19)", vat_cents(1999, 19), 380)
check("vat_cents(250, 10)", vat_cents(250, 10), 25)
raises("vat_cents(100, -1)", lambda: vat_cents(100, -1))
# B stock-ledger
led = StockLedger()
led.receive("sku-b", 5)
led.receive("sku-a", 5)
led.ship("sku-a", 2)
check("on_hand after ship", led.on_hand("sku-a"), 3)
check("never received", led.on_hand("nope"), 0)
check("skus sorted", led.skus(), ["sku-a", "sku-b"])
raises("ship 4 of 3", lambda: led.ship("sku-a", 4))
check("count kept after refused ship", led.on_hand("sku-a"), 3)
raises("receive 0", lambda: led.receive("x", 0))
# D add-stock-valuation, F add-valuation-summary, H add-summary-currency (using A, B, C)
l2 = StockLedger()
l2.receive("a", 2)
l2.receive("b", 3)
l2.receive("c", 1)
l2.ship("c", 1)
prices = {"a": 150, "b": 200}
check("stock_value", stock_value(l2, prices, 10), {"net": "9.00", "vat": "0.90", "gross": "9.90"})
check("empty ledger", stock_value(StockLedger(), {}, 10), {"net": "0.00", "vat": "0.00", "gross": "0.00"})
l3 = StockLedger()
l3.receive("c", 1)
raises("missing price", lambda: stock_value(l3, {}, 10))
check("summary", valuation_summary(l2, prices, 10), "net 9.00 | vat 0.90 | gross 9.90")
check("summary RON", valuation_summary(l2, prices, 10, currency="RON"), "net 9.00 RON | vat 0.90 RON | gross 9.90 RON")
# E invoice-line, G invoice-lines (using A, B, C)
l4 = StockLedger()
l4.receive("a", 5)
l4.receive("b", 5)
check(
    "invoice_line",
    invoice_line(l4, "a", 3, 250, 10),
    {"sku": "a", "qty": 3, "net": "7.50", "vat": "0.75", "gross": "8.25"},
)
check(
    "half-up line",
    invoice_line(l4, "a", 1, 5, 50),
    {"sku": "a", "qty": 1, "net": "0.05", "vat": "0.03", "gross": "0.08"},
)
check("qty equal to stock", invoice_line(l4, "a", 5, 1, 0)["qty"], 5)
raises("qty above stock", lambda: invoice_line(l4, "a", 6, 1, 10))
raises("qty 0", lambda: invoice_line(l4, "a", 0, 1, 10))
raises("never received", lambda: invoice_line(l4, "zz", 1, 1, 10))
check("ledger unchanged", l4.on_hand("a"), 5)
check(
    "invoice_lines",
    invoice_lines(l4, [("a", 1, 100), ("b", 3, 50)], 10),
    [
        {"sku": "a", "qty": 1, "net": "1.00", "vat": "0.10", "gross": "1.10"},
        {"sku": "b", "qty": 3, "net": "1.50", "vat": "0.15", "gross": "1.65"},
    ],
)
raises("summed stock", lambda: invoice_lines(l4, [("a", 4, 100), ("a", 4, 100)], 10))
check("summed within stock", len(invoice_lines(l4, [("a", 2, 100), ("a", 3, 100)], 10)), 2)
raises("empty invoice", lambda: invoice_lines(l4, [], 10))
raises("bad line", lambda: invoice_lines(l4, [("a", 1, 100), ("b", 0, 50)], 10))
# I add-shelf-label
check("shelf_label", shelf_label(3, 7, " bolts "), "A03-S07 bolts")
raises("empty name", lambda: shelf_label(3, 7, "  "))
# J units-surplus
from inventory.stock import units_surplus  # noqa: E402

check("surplus 9-4", units_surplus(9, 4), 5)
check("surplus floor", units_surplus(3, 4), 0)
raises("negative", lambda: units_surplus(-1, 4))
print(f"smoke: {checks} checks passed")
