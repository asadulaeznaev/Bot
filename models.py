from dataclasses import dataclass

@dataclass
class Token:
    name: str
    symbol: str
    decimals: int
    total_supply: float
    current_price: float

@dataclass
class Wallet:
    user_id: int
    username: str
    balance: float
    created_at: str

@dataclass
class Transaction:
    id: int
    timestamp: str
    sender_id: int
    receiver_id: int
    amount: float
    description: str | None
