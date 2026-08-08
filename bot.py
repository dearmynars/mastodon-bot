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

GOOGLE_SHEET_NAME = '네_구글_스프레드시트_정확한_이름' # ⚠️ 본인 시트 제목 확인!
# =================================================

# --- 1. Render 가짜 웹서버 (Timed Out 방지용) ---
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
    creds_dict = json.loads(json_str)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        creds_dict, 
        scopes=["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    )
else:
    print("❌ 오류: GOOGLE_CREDS_JSON 환경변수가 설정되지 않았습니다.")

gc = gspread.authorize(creds)
mastodon = Mastodon(access_token=MASTODON_ACCESS_TOKEN, api_base_url=MASTODON_API_BASE_URL)

def get_google_sheet_data():
    """구글 시트에서 최신 키워드와 답변 리스트를 읽어옵니다."""
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
        print(f"구글 시트 불러오기 실패: {e}")
        return {}

def clean_html(raw_html):
    """마스토돈 본문 멘션의 HTML 태그 제거"""
    return re.sub(r'<.*?>', '', raw_html).strip()

def process_mention(content, keyword_dict):
    """멘션 내용을 분석하여 알맞은 답변 리턴"""
    text = clean_html(content)
    
# 1. nDm 주사위 기능 (예: 1d100, 2d50+10, 3d6-2 등)
    dice_match = re.search(r'(\d+)d(\d+)(?:([+-])(\d+))?', text, re.IGNORECASE)
    if dice_match:
        count, sides = int(dice_match.group(1)), int(dice_match.group(2))
        sign = dice_match.group(3)
        modifier = int(dice_match.group(4)) if dice_match.group(4) else 0
        
        rolls = [random.randint(1, sides) for _ in range(count)]
        total = sum(rolls)
        
        if sign == '+': total += modifier
        elif sign == '-': total -= modifier
        
        # 시트에 'dice' 키워드가 있으면 시트 양식 사용
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

    # 2. YN 기능에 대한 답변
    if re.search(r'\b(yn)\b', text, re.IGNORECASE):
        yn_result = random.choice(['Y', 'N'])
        
        # 시트에 'yn' 키워드가 있으면 시트 양식 사용, 없으면 기본 양식
        if 'yn' in keyword_dict:
            template = random.choice(keyword_dict['yn'])
            return template.format(result=yn_result)
        else:
            return f"{yn_result}"

    # 3. [대괄호] 키워드 자동 답변 기능
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

def main():
    print("🤖 마스토돈 15초 칼답 봇이 가동되었습니다!")
    last_notification_id = None
    
    try:
        init_notes = mastodon.notifications(limit=1)
        if init_notes:
            last_notification_id = init_notes[0]['id']
    except Exception as e:
        print(f"최초 알림 로드 오류: {e}")

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
                        print(f"[{sender}]에게 ({original_visibility})로 답장 완료!")
            
        except Exception as e:
            print(f"오류 발생: {e}")
            
        time.sleep(15)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    main()
