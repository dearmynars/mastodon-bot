import time
import random
import re
import os
import json
import gspread
from mastodon import Mastodon
from oauth2client.service_account import ServiceAccountCredentials

# ================= [ ⚙️ 설정 영역 ] =================
# 마스토돈 토큰은 Render 환경변수에서 가져오거나, 없으면 아래 기본값을 씁니다.
MASTODON_ACCESS_TOKEN = os.environ.get('MASTODON_ACCESS_TOKEN', '여기에_네_마스토돈_토큰을_넣어두어도_돼')
MASTODON_API_BASE_URL = 'https://planet.moe'  # planet.moe 주소 지정

GOOGLE_SHEET_NAME = 'NEW_BOT' # ⚠️ 구글 시트 제목 적기!
# =================================================--

# 1. 구글 인증 정보 로드 (Render 환경변수에서 읽어옴)
json_str = os.environ.get('GOOGLE_CREDS_JSON')
if json_str:
    creds_dict = json.loads(json_str)
    # from_service_account_info 대신 from_json_keyfile_dict 로 변경되었습니다!
    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        creds_dict, 
        scopes=["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    )
else:
    # 혹시 환경변수가 설정 안 되었을 때를 대비한 예외 처리
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
        print(f"구글 시트 불러오기 실패 (재시도 예정): {e}")
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
        
        mod_text = f" {sign} {modifier}" if sign else ""
        if sign == '+': total += modifier
        elif sign == '-': total -= modifier
            
        return f"🎲 주사위 결과 ({count}d{sides}{mod_text}):\n각각 [{', '.join(map(str, rolls))}] 나옴\n총합: {total}"

    # 2. YN 기능에 대한 답변 (yn, YN, yN, Yn 대소문자 구분 없음)
    if re.search(r'\b(yn)\b', text, re.IGNORECASE):
        return f"🔮 질문에 대한 답변: {random.choice(['Y', 'N'])}"

    # 3. [대괄호] 키워드 자동 답변 기능
    # 사용자가 보낸 텍스트에서 [단어] 형태인 것들을 모두 추출합니다. (예: "[사과]가 먹고싶다" -> ["사과"])
    user_brackets = re.findall(r'\[(.*?)\]', text)
    
    if user_brackets:
        matched_replies = []
        
        # 사용자가 대괄호 안에 적은 단어들 중 구글 시트에 등록된 키워드가 있는지 확인
        for b_word in user_brackets:
            b_word_clean = b_word.strip()
            if b_word_clean in keyword_dict:
                matched_replies.extend(keyword_dict[b_word_clean])
                
        if matched_replies:
            # 매칭된 답변 중 동일한 확률로 무작위 추첨
            return random.choice(matched_replies)
        
    return None

def main():
    print("🤖 마스토돈 15초 칼답 봇이 가동되었습니다!")
    last_notification_id = None
    
    # 처음 켤 때 기존 알림은 무시
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
                    original_visibility = status['visibility'] # 상대방 공개설정 낚아채기!
                    
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
            
        time.sleep(15) # 15초마다 마스토돈 감시

if __name__ == "__main__":
    main()
