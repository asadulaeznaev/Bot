from telebot.asyncio_handler_backends import State, StatesGroup

class UserStates(StatesGroup):
    WAITING_FOR_RECIPIENT = State()
    WAITING_FOR_AMOUNT = State()
    CONFIRMING_SEND = State()
    ADMIN_SET_PRICE = State()
    ADMIN_MINT_RECIPIENT = State()
    ADMIN_MINT_AMOUNT = State()
    # Farming States
    FARMING_MENU = State()
    WAITING_FOR_STAKE_AMOUNT = State()
    WAITING_FOR_UNSTAKE_ID = State()
    STAKING_AMOUNT = State()
    UNSTAKING_SELECT_STAKE = State()
    CLAIMING_SELECT_STAKE = State()
    BOOSTER_STORE = State()
    CONFIRM_BUY_BOOSTER = State()
    SELLING_HKN_AMOUNT = State()
    WAITING_FOR_SELL_AMOUNT = State()
