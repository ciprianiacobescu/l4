from dataclasses import dataclass


def label(order):
    return str(order)


@dataclass
class Order:
    total: float
    code: str
