#!/bin/bash

# Проверка наличия Homebrew
if ! command -v brew &> /dev/null; then
    echo "Homebrew не найден. Устанавливаю Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
else
    echo "Homebrew уже установлен."
fi

# Обновление Homebrew
echo "Обновляю Homebrew..."
brew update

# Установка Python3 (если не установлен)
if ! command -v python3 &> /dev/null; then
    echo "Устанавливаю Python3..."
    brew install python
else
    echo "Python3 уже установлен."
fi

# Установка pip (если не установлен)
if ! command -v pip3 &> /dev/null; then
    echo "Устанавливаю pip3..."
    curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py
    python3 get-pip.py
    rm get-pip.py
else
    echo "pip3 уже установлен."
fi

# Установка Tor (через Homebrew)
if ! command -v tor &> /dev/null; then
    echo "Устанавливаю Tor..."
    brew install tor
else
    echo "Tor уже установлен."
fi

# Установка Google Chrome (для selenium)
if ! [ -d "/Applications/Google Chrome.app" ]; then
    echo "Устанавливаю Google Chrome..."
    brew install --cask google-chrome
else
    echo "Google Chrome уже установлен."
fi

# Установка chromedriver (через Homebrew)
if ! command -v chromedriver &> /dev/null; then
    echo "Устанавливаю chromedriver..."
    brew install chromedriver
else
    echo "chromedriver уже установлен."
fi

# Установка необходимых Python-библиотек
REQUIRED_PYTHON_PACKAGES=(gspread google-auth-oauthlib google-auth selenium webdriver-manager yt-dlp requests beautifulsoup4)
for pkg in "${REQUIRED_PYTHON_PACKAGES[@]}"; do
    if ! python3 -c "import $pkg" &> /dev/null; then
        echo "Устанавливаю Python-библиотеку: $pkg"
        pip3 install $pkg
    else
        echo "Python-библиотека $pkg уже установлена."
    fi
done

pip install python-dotenv

echo "\nВсе необходимые зависимости установлены!" 