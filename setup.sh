#!/bin/bash
# setup.sh — One-click setup for Deriv MA Crossover Trading Bot
# Usage: bash setup.sh

set -e

echo "================================================"
echo "  Deriv MA Crossover Bot — Setup Script"
echo "================================================"

# Check Python version
python3 --version 2>&1 | grep -q "Python 3" || { echo "Python 3 is required."; exit 1; }

echo "[1/4] Installing Python dependencies..."
pip3 install -r requirements.txt

echo "[2/4] Initialising Django database..."
python3 manage.py migrate --run-syncdb 2>/dev/null || true

echo "[3/4] Collecting static files..."
python3 manage.py collectstatic --noinput 2>/dev/null || true

echo "[4/4] All done!"
echo ""
echo "To run the dashboard locally:"
echo "  python3 manage.py runserver 8008"
echo ""
echo "Then open your browser at: http://127.0.0.1:8008"
echo ""
echo "To run a quick offline backtest test:"
echo "  python3 test_with_synthetic_data.py"
echo ""
echo "To run a live Deriv backtest:"
echo "  python3 run_backtest.py --symbol R_75 --granularity 60 --resample 5min --fast 10 --slow 30"
echo ""
echo "================================================"
