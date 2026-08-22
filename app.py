import json
import os
import re
import time

import requests
import urllib3
from bs4 import BeautifulSoup
from flask import Flask, render_template_string, request
from playwright.sync_api import sync_playwright

# 關閉 SSL 不安全請求警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

LIST_URL = 'https://www.tacd.org.tw/ehc-tacd/s/w/edu/edu/edu1?eduIn=0'

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    )
}

# 記憶最近搜尋過的關鍵字用的檔案
# ⚠️ 注意：Render 免費方案的檔案系統是「暫時性」的，
# 每次程式重新部署或休眠後醒來，這個檔案可能會被重置、歷史紀錄會消失。
# 如果之後想要「永久」保留歷史紀錄，需要另外加裝 Render 的付費 Persistent Disk。
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(SCRIPT_DIR, 'search_history.json')
MAX_HISTORY = 10

app = Flask(__name__)


# ==================== 搜尋歷史紀錄 ====================
def load_history() -> list:
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                return data[:MAX_HISTORY]
    except Exception as e:
        print(f'⚠️ 讀取搜尋歷史失敗：{e}')
    return []


def save_history(history: list):
    try:
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history[:MAX_HISTORY], f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f'⚠️ 儲存搜尋歷史失敗：{e}')


def add_to_history(keyword: str) -> list:
    history = load_history()
    history = [h for h in history if h != keyword]
    history.insert(0, keyword)
    history = history[:MAX_HISTORY]
    save_history(history)
    return history


# ==================== 爬蟲邏輯(跟之前完全相同) ====================
def collect_all_course_links(list_url: str = LIST_URL) -> set:
    course_links = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=HEADERS['User-Agent'])

        print(f'🌐 開啟清單頁：{list_url}')
        page.goto(list_url, wait_until='networkidle', timeout=30000)
        page.wait_for_timeout(1500)

        def grab_links_on_current_page():
            hrefs = page.eval_on_selector_all(
                'a[href]', 'els => els.map(e => e.href)'
            )
            new_count = 0
            for h in hrefs:
                if '/eduInfo1/' in h:
                    clean = h.split('#')[0]
                    if clean not in course_links:
                        course_links.add(clean)
                        new_count += 1
            return new_count

        grab_links_on_current_page()

        body_text = page.inner_text('body')
        m = re.search(r'第\s*1\s*/\s*(\d+)\s*頁', body_text)
        total_pages = int(m.group(1)) if m else 1
        print(f'📄 偵測到清單共 {total_pages} 頁，已收集第 1 頁課程連結，累計 {len(course_links)} 筆')

        current_page = 1
        while current_page < total_pages:
            try:
                next_btn = page.get_by_text('下一頁', exact=True).first
                next_btn.click()
                current_page += 1

                page.wait_for_function(
                    f"document.body.innerText.includes('第{current_page}/{total_pages}頁')",
                    timeout=15000,
                )
                page.wait_for_timeout(1000)

                added = grab_links_on_current_page()
                print(
                    f'📄 已切換到第 {current_page}/{total_pages} 頁，'
                    f'新增 {added} 筆課程連結，累計 {len(course_links)} 筆'
                )
            except Exception as e:
                print(f'⚠️ 換到第 {current_page + 1} 頁時發生問題：{e}')
                break

        browser.close()

    return course_links


def search_keyword_in_links(links, keyword: str, delay: float = 0.3):
    matched_results = []
    sorted_links = sorted(links)
    total = len(sorted_links)

    for idx, url in enumerate(sorted_links, 1):
        print(f'[{idx}/{total}] 掃描中: {url}')
        try:
            response = requests.get(
                url, headers=HEADERS, timeout=10, verify=False
            )
            content_type = response.headers.get('Content-Type', '')
            if 'text/html' not in content_type:
                continue

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                page_title = (
                    soup.title.string.strip()
                    if soup.title and soup.title.string
                    else '無標題頁面'
                )

                for element in soup(['script', 'style']):
                    element.extract()

                page_text = soup.get_text()
                if keyword in page_text:
                    print(f'  └─ ✨ 找到目標關鍵字！')
                    matched_results.append({'title': page_title, 'url': url})

            time.sleep(delay)

        except Exception as e:
            print(f'  └─ ⚠️ 存取失敗: {e}')

    return matched_results


# ==================== 網頁介面 ====================
PAGE_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>基層糖尿病學會 - 課程關鍵字搜尋</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
         background:#f4f6f9; padding:30px; margin:0; color:#333; }
  .box { max-width:900px; margin:0 auto 24px auto; background:#fff; padding:28px 30px;
         border-radius:10px; box-shadow:0 4px 12px rgba(0,0,0,0.08); }
  h1 { color:#1a5276; font-size:1.4rem; margin-top:0; border-bottom:3px solid #2980b9; padding-bottom:10px; }
  h2 { color:#1a5276; font-size:1.3rem; margin:0 0 6px 0; }
  form { display:flex; gap:10px; margin-top:14px; flex-wrap:wrap; }
  input[type=text] { flex:1; min-width:200px; padding:10px; font-size:1rem; border:1px solid #ccc;
                      border-radius:6px; box-sizing:border-box; }
  button { background:#2980b9; color:#fff; border:none; padding:10px 24px;
           border-radius:6px; font-size:1rem; cursor:pointer; white-space:nowrap; }
  button:hover { background:#21618c; }
  p.hint { color:#7f8c8d; font-size:0.9rem; margin:4px 0 0 0; }
  .loading { display:none; color:#2980b9; margin-top:12px; font-size:0.9rem; }

  .history-wrap { margin-top:16px; }
  .history-label { font-size:0.85rem; color:#7f8c8d; margin-bottom:8px; }
  .history-chips { display:flex; flex-wrap:wrap; gap:8px; }
  .history-chips form { margin:0; display:inline; }
  .chip-btn { background:#ebf5fb; color:#1a5276; border:1px solid #bcd9ea; padding:6px 14px;
              border-radius:16px; font-size:0.88rem; cursor:pointer; white-space:nowrap; }
  .chip-btn:hover { background:#d6ebf7; }

  .meta-info { background-color: #ebf5fb; border-left: 4px solid #2980b9; padding: 12px 18px;
               margin-bottom: 20px; border-radius: 4px; font-size: 0.95rem; }
  .meta-info p { margin: 4px 0; }
  .results-list { list-style: none; padding: 0; margin: 0; }
  .result-item { padding: 16px; border-bottom: 1px solid #e5e7eb; }
  .result-item:hover { background-color: #f8fafc; }
  .result-item:last-child { border-bottom: none; }
  .item-title { font-size: 1.05rem; font-weight: bold; color: #2c3e50; margin-bottom: 6px; }
  .badge { background-color: #2980b9; color: white; padding: 2px 8px; border-radius: 12px;
           font-size: 0.85rem; margin-right: 6px; }
  .item-link { color: #27ae60; text-decoration: none; word-break: break-all; font-size: 0.9rem; }
  .item-link:hover { text-decoration: underline; }
</style>
</head>
<body>
  <div class="box">
    <h1>🩺 基層糖尿病學會課程搜尋</h1>
    <p class="hint">輸入想搜尋的關鍵字，系統會自動掃描全部分頁的課程(頁數即時偵測)。搜尋完可以直接在這裡繼續輸入下一個關鍵字。</p>
    <form method="POST" action="/search" onsubmit="document.getElementById('loading').style.display='block';">
      <input type="text" name="keyword" placeholder="例如：台灣腎臟醫學" value="{{ keyword or '' }}" required autofocus>
      <button type="submit">開始搜尋</button>
    </form>
    <div class="loading" id="loading">🔎 搜尋中，依課程數量可能需要 30 秒~2 分鐘，請耐心等待，不要關閉頁面...</div>

    {% if history %}
    <div class="history-wrap">
      <div class="history-label">🕘 最近搜尋過的關鍵字(點一下可直接重新搜尋)：</div>
      <div class="history-chips">
        {% for h in history %}
        <form method="POST" action="/search" onsubmit="document.getElementById('loading').style.display='block';">
          <input type="hidden" name="keyword" value="{{ h }}">
          <button type="submit" class="chip-btn">{{ h }}</button>
        </form>
        {% endfor %}
      </div>
    </div>
    {% endif %}
  </div>

  {% if searched %}
  <div class="box">
    <h2>搜尋結果</h2>
    <div class="meta-info">
        <p><strong>搜尋關鍵字：</strong> <span style="color: #c0392b;">{{ keyword }}</span></p>
        <p><strong>掃描課程總數：</strong> {{ total_scanned }} 筆</p>
        <p><strong>找到頁面筆數：</strong> {{ results|length }} 筆</p>
    </div>

    <ul class="results-list">
    {% if results %}
        {% for item in results %}
        <li class="result-item">
            <div class="item-title">
		<span class="badge">{{ loop.index }}</span>
		<a class="item-link" href="{{ item.url }}" target="_blank">{{ item.url }}</a>
            </div>
        </li>
        {% endfor %}
    {% else %}
        <li class="result-item" style="text-align:center; color:#7f8c8d;">未找到包含此關鍵字的網頁</li>
    {% endif %}
    </ul>
  </div>
  {% endif %}
</body>
</html>
"""


@app.route('/', methods=['GET'])
def index():
    return render_template_string(
        PAGE_TEMPLATE, searched=False, keyword='', history=load_history()
    )


@app.route('/search', methods=['POST'])
def search():
    keyword = request.form.get('keyword', '').strip()
    if not keyword:
        return render_template_string(
            PAGE_TEMPLATE, searched=False, keyword='', history=load_history()
        )

    history = add_to_history(keyword)

    print(f'\n{"=" * 60}')
    print(f'🚀 收到搜尋請求，關鍵字："{keyword}"')
    print('🚀 第一階段：收集所有分頁的課程連結中...\n')
    all_links = collect_all_course_links(LIST_URL)
    print(f'\n✅ 共收集到 {len(all_links)} 個課程連結\n')

    print(f'🔍 第二階段：逐一搜尋關鍵字 "{keyword}"...\n')
    results = search_keyword_in_links(all_links, keyword=keyword, delay=0.3)

    print(f'\n🎉 搜尋完成！共找到 {len(results)} 筆包含「{keyword}」的網頁\n')

    return render_template_string(
        PAGE_TEMPLATE,
        searched=True,
        keyword=keyword,
        total_scanned=len(all_links),
        results=results,
        history=history,
    )


if __name__ == '__main__':
    # Render 會透過 PORT 這個環境變數告訴我們要監聽哪個埠號，
    # host 也一定要是 0.0.0.0 才能對外接受連線(跟本機用的 127.0.0.1 不同)。
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
