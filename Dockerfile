# 用微軟官方的 Playwright 映像檔，Chromium 跟所有系統相依套件都已經裝好，
# 避免自己在雲端環境手動安裝瀏覽器套件時失敗。
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Render 會自動設定 PORT 環境變數，app.py 裡已經會讀取它
CMD ["python", "app.py"]
