@echo off
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
pyinstaller --noconfirm --clean --onefile --windowed ^
  --name GameOptimizerPRO ^
  --hidden-import=psutil --collect-all psutil ^
  main.py
echo.
echo EXE is in the dist folder.
pause