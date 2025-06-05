#!/bin/bash

# Script to set up the environment and run the HelgyKoin Telegram Bot

# --- Configuration ---
PYTHON_CMD="python3" # Change to "python" if python3 is not your default for Python 3
VENV_DIR="venv"
REQUIREMENTS_FILE="requirements.txt"
MAIN_SCRIPT="main .py" # Note the space in the filename

# --- Helper Functions ---
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

echo_info() {
    echo "[INFO] $1"
}

echo_error() {
    echo "[ERROR] $1" >&2
}

# --- Main Script ---

# 1. Check for Python 3
if ! command_exists $PYTHON_CMD; then
    echo_error "$PYTHON_CMD is not found. Please install Python 3."
    exit 1
fi
echo_info "Python 3 found."

# 2. Check/Create Virtual Environment
if [ ! -d "$VENV_DIR" ]; then
    echo_info "Virtual environment '$VENV_DIR' not found. Creating..."
    $PYTHON_CMD -m venv $VENV_DIR
    if [ $? -ne 0 ]; then
        echo_error "Failed to create virtual environment."
        exit 1
    fi
    echo_info "Virtual environment created."
else
    echo_info "Virtual environment '$VENV_DIR' found."
fi

# 3. Activate Virtual Environment
# Source command must be used in the current shell, not a subshell.
# This part of the script makes more sense if the user sources this script,
# or if the script itself executes the final python command within the same context.
# For a directly executable script, we'll run python from the venv directly.
VENV_PYTHON="$VENV_DIR/bin/python"
if [ ! -f "$VENV_PYTHON" ]; then
    echo_error "Virtual environment python executable not found at $VENV_PYTHON."
    echo_error "Try deleting the '$VENV_DIR' directory and running this script again."
    exit 1
fi
echo_info "Using Python from virtual environment: $VENV_PYTHON"

# 4. Install/Update Dependencies
echo_info "Installing/updating dependencies from $REQUIREMENTS_FILE..."
"$VENV_PYTHON" -m pip install -r "$REQUIREMENTS_FILE"
if [ $? -ne 0 ]; then
    echo_error "Failed to install dependencies."
    exit 1
fi
echo_info "Dependencies installed successfully."

# 5. Run the Bot
echo_info "Starting the bot: $MAIN_SCRIPT..."
"$VENV_PYTHON" "$MAIN_SCRIPT" # Ensure quotes handle the space in filename

echo_info "Bot script finished or was interrupted."
