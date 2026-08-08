import time
import random
import re
import os
import json
import threading
import gspread
from flask import Flask
from mastodon import Mastodon
from oauth2client.service_account import ServiceAccountCredentials

# ================= [ ⚙️ 설정 영역 ] =================
MASTODON_ACCESS_TOKEN = os.environ.get('MASTODON_ACCESS_TOKEN', '')
MASTODON_API_BASE_URL = 'https://planet.moe'

GOOGLE_SHEET_NAME = 'NEW_BOT' # ⚠️ 본인 시트 제목 정확히 작성!
# =================================================

# --- 1. Render 가짜 웹서버 ---
app = Flask('')

@app.route('/')
def home():
    return "🤖 마스토돈 봇이 정상 작동 중입니다!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
# -------------------------------------------------

# --- 2. 구글 인증 및 마스토돈 연결 ---
json_str = os.environ.get('GOOGLE_CREDS_JSON')
if json_str:
    try:
        creds_dict = json.loads(json_str)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(
            creds_dict, 
            scopes=["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        )
        gc = gspread.authorize(creds)
    except Exception as e:
        print(f"❌ 구글 인증 생성 실패: {e}")
        gc = None
else:
    print("❌ 오류: GOOGLE_CREDS_JSON 환경변수가 설정되지 않았습니다.")
    gc = None

mastodon = Mastodon(access_token=MASTODON_ACCESS_TOKEN, api_base_url=MASTODON_API_BASE_URL)

def get_google_sheet_data():
    """구글 시트에서 최신 키워드와 답변 리스트를 읽어옵니다."""
    if not gc:
        print("❌ 구글 인증(gc)이 없어 시트를 읽을 수 없습니다.")
        return {}
    try:
        sheet = gc.open(GOOGLE_SHEET_NAME).sheet1
        records = sheet.get_all_records()
        keyword_dict = {}
        for r in records:
            kw = str(r.get('keyword', '')).strip()
            rep = str(r.get('reply', '')).strip()
            if kw and rep:
                if kw not in keyword_dict:
                    keyword_dict[kw] = []
                keyword_dict[kw].append(rep)
        return keyword_dict
    except Exception as e:
        print(f"❌ 구글 시트 불러오기 실패: {e}")
        return {}

def clean_html(raw_html):
    """마스토돈 본문 멘션의 HTML 태그 제거"""
    return re.sub(r'<.*?>', '', raw_html).strip()

def process_mention(content, keyword_dict):
    """멘션 내용을 분석하여 알맞은 답변 리턴"""
    text = clean_html(content)
    
    # 1. nDm 주사위 기능
    dice_match = re.search(r'(\d+)d(\d+)(?:([+-])(\d+))?', text, re.IGNORECASE)
    if dice_match:
        count, sides = int(dice_match.group(1)), int(dice_match.group(2))
        sign = dice_match.group(3)
        modifier = int(dice_match.group(4)) if dice_match.group(4) else 0
        
        rolls = [random.randint(1, sides) for _ in range(count)]
        total = sum(rolls)
        
        if sign == '+': total += modifier
        elif sign == '-': total -= modifier
        
        if 'dice' in keyword_dict:
            try:
                template = random.choice(keyword_dict['dice'])
                return template.format(
                    count=count,
                    sides=sides,
                    total=total,
                    rolls=f"[{', '.join(map(str, rolls))}]"
                )
            except Exception as e:
                print(f"주사위 서식 적용 에러: {e}")
                return f"{count}d{sides} 결과 : {total}"
        else:
            return f"{count}d{sides} 결과 : {total}"

    # 2. YN 기능
    if re.search(r'\b(yn)\b', text, re.IGNORECASE):
        yn_result = random.choice(['Y', 'N'])
        if 'yn' in keyword_dict:
            template = random.choice(keyword_dict['yn'])
            return template.format(result=yn_result)
        else:
            return f"{yn_result}"

    # 3. [대괄호] 키워드 자동 답변
    user_brackets = re.findall(r'\[(.*?)\]', text)
    if user_brackets:
        matched_replies = []
        for b_word in user_brackets:
            b_word_clean = b_word.strip()
            if b_word_clean in keyword_dict:
                matched_replies.extend(keyword_dict[b_word_clean])
                
        if matched_replies:
            return random.choice(matched_replies)
        
    return None

def auto_toot_loop():
    """3시간~6시간 간격으로 구글 시트의 auto_toot 문구를 팔로워 전용으로 자동 작성합니다."""
    while True:
        wait_seconds = random.randint(3 * 3600, 6 * 3600)
        hours = round(wait_seconds / 3600, 2)
        print(f"⏰ 다음 자동 툿까지 {hours}시간 대기합니다.")
        time.sleep(wait_seconds)
        
        try:
            keyword_dict = get_google_sheet_data()
            if 'auto_toot' in keyword_dict and keyword_dict['auto_toot']:
                toot_text = random.choice(keyword_dict['auto_toot'])
                mastodon.status_post(status=toot_text, visibility='followers_only')
                print(f"📢 [자동 툿 성공] {toot_text}")
        except Exception as e:
            print(f"자동 툿 작성 중 오류 발생: {e}")

def main():
    print("🤖 마스토돈 15초 칼답 루프 시작!")
    last_notification_id = None
    
    try:
        init_notes = mastodon.notifications(limit=1)
        if init_notes:
            last_notification_id = init_notes[0]['id']
            print(f"📌 기준 알림 ID 설정 완료: {last_notification_id}")
    except Exception as e:
        print(f"❌ 최초 알림 로드 오류: {e}")

    while True:
        try:
            keyword_dict = get_google_sheet_data()
            notifications = mastodon.notifications(types=['mention'], min_id=last_notification_id)
            
            if notifications:
                for note in reversed(notifications):
                    if not last_notification_id or note['id'] > last_notification_id:
                        last_notification_id = note['id']
                    
                    status = note['status']
                    sender = status['account']['acct']
                    status_id = status['id']
                    content = status['content']
                    original_visibility = status['visibility']
                    
                    reply_text = process_mention(content, keyword_dict)
                    
                    if reply_text:
                        full_reply = f"@{sender} {reply_text}"
                        mastodon.status_post(
                            status=full_reply,
                            in_reply_to_id=status_id,
                            visibility=original_visibility
                        )
                        print(f"✉️ [{sender}]에게 ({original_visibility})로 답장 완료!")
            
        except Exception as e:
            print(f"❌ 감시 루프 오류 발생: {e}")
            
        time.sleep(15)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=auto_toot_loop, daemon=True).start()
    main()
