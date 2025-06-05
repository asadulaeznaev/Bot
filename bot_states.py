from telebot.handler_backends import State, StatesGroup

class UserStates(StatesGroup):
    WAITING_FOR_RECIPIENT = State()
    WAITING_FOR_AMOUNT = State()
    CONFIRMING_SEND = State()
    ADMIN_SET_PRICE = State()
    ADMIN_MINT_RECIPIENT = State()
    ADMIN_MINT_AMOUNT = State()
