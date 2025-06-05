# HelgyKoin Telegram Bot

This is a Telegram bot that simulates a simple cryptocurrency called HelgyKoin (HKN). Users can create wallets, check balances, transfer HKN to other users, and get information about the token. Admins have additional capabilities like setting the token price and minting new tokens.

## Features

*   **Wallet Creation:** New users automatically get a wallet with a startup bonus.
*   **Balance Checking:** Users can check their HKN balance.
*   **Transfers:** Users can send HKN to each other using Telegram ID or username.
*   **Token Information:** View details about HKN (name, symbol, total supply, current price).
*   **Market Capitalization:** View the current market cap of HKN.
*   **Transaction History:** Users can view their recent transaction history.
*   **Admin Functions:**
    *   Set token price.
    *   Mint new tokens to a user's wallet.

## Farming and Economy Features

The bot includes features for users to earn more HelgyKoin (HKN) through farming and interaction with the bot's economy.

*   **HKN Staking:**
    *   Users can "stake" their HKN to earn rewards over time.
    *   Rewards are calculated based on the staked amount and duration.
    *   Users can stake, unstake, and claim rewards through the "🌾 Фарминг" (Farming) menu.

*   **Farming Boosters:**
    *   Users can purchase "Ускорители" (Boosters) using HKN from the "🚀 Ускорители" section within the Farming menu.
    *   Example Booster: "Ускоритель х1.5 (24ч)" increases farming rewards by 50% for 24 hours.
    *   Active boosters automatically apply to staking rewards.

*   **Sell HKN to System:**
    *   Users can sell their HKN back to the bot system at a predetermined conceptual rate (e.g., for "BotUSD").
    *   This feature is accessible via the "🏦 Продать HKN" button in the main menu.

## Prerequisites

*   Python 3.7+
*   `aiosqlite` library
*   `pyTelegramBotAPI` library

## Setup Instructions

1.  **Clone the repository:**
    ```bash
    git clone <repository_url> # Replace <repository_url> with the actual URL
    cd <repository_directory>
    ```

2.  **Install dependencies:**
    It's recommended to use a virtual environment.
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    pip install -r requirements.txt
    ```
    *(The `requirements.txt` file should now exist in the repository).*

3.  **Configure the Bot:**
    Open `config.py` and set your actual bot token and admin ID(s):
    ```python
    class BotConfig:
        BOT_TOKEN = "YOUR_ACTUAL_BOT_TOKEN"  # Replace with your bot token from BotFather
        ADMIN_IDS = [YOUR_ADMIN_TELEGRAM_ID]   # Replace with your numeric Telegram ID
        DB_PATH = "helgykoin.db" # Default database name
    ```

4.  **Initialize the Database (if running for the first time):**
    The bot will attempt to create and initialize the database (`helgykoin.db`) on its first run. This includes creating all necessary tables.

5.  **Note on Updates:** If you are updating from an older version of the bot, and new database tables have been added (like `stakes` or `active_boosters`), you might need to delete your existing `helgykoin.db` file to allow the bot to create it fresh with the new schema. Make sure to back up any important data if necessary. A more robust solution would be a migration system, but for this project, this note serves as guidance.


## Running the Bot

Once the setup is complete, you can run the bot using:

```bash
python "main .py"
```
*(Note the space in "main .py" if you haven't renamed it).*

Make sure your virtual environment is activated if you used one. The bot will start polling for messages.
