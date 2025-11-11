import streamlit as st
import pandas as pd
import re
import sqlite3
import gdown  # 구글 드라이브 다운로드용
import os     # 파일이 존재하는지 확인용

# 1. 데이터 로드 (DB 다운로드 및 연결)
@st.cache_resource  # DB 연결은 @st.cache_resource 사용
def load_data():
    """druglist.db 파일을 다운로드하고 연결합니다."""
    
    DB_FILE = 'druglist.db'
    # [수정됨] 사용자님이 주신 링크의 파일 ID
    GDRIVE_FILE_ID = '11B6_WtJWs5AIfCAbN67F2sqaAkWCyJob' 
    
    try:
        # Streamlit Cloud 서버에는 파일이 없으므로, 파일이 없을 때만 다운로드
        if not os.path.exists(DB_FILE):
            st.info(f"'{DB_FILE}' 파일이 없어 Google Drive에서 다운로드합니다... (시간이 걸릴 수 있습니다)")
            gdown.download(id=GDRIVE_FILE_ID, output=DB_FILE, quiet=False)
            st.info("데이터베이스 다운로드 완료!")

        # DB 파일에 연결
        conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        
        # [중요] DB에 'normalize' 함수를 다시 생성 (Streamlit Cloud에서 필요)
        def normalize_text(text):
            if text is None: return None
            return re.sub(r'[\s\(\)\[\]_/-]|주사제|정제|정|약|캡슐|시럽', '', str(text)).strip().lower()
        conn.create_function("normalize", 1, normalize_text)
        
        print("✅ (Streamlit) 약물 데이터베이스 로드 성공!")
        return conn
        
    except Exception as e:
        st.error(f"❌ 데이터베이스 로드 실패: {e}")
        st.error("Google Drive 링크가 '링크가 있는 모든 사용자'로 공유되었는지 확인해주세요.")
        return None

# 데이터베이스 연결 실행
conn = load_data()

# 2. 약물 검색 및 상호작용 함수들
def find_drug_info(db_conn, query):
    """(수정) SQL을 사용해 DB에서 유연하게 검색합니다."""
    
    cleaned_query = re.sub(r'[\s\(\)\[\]_/-]|주사제|정제|정|약|캡슐|시럽', '', query).strip().lower()
    
    if len(cleaned_query) < 2:
        return pd.DataFrame() 
    
    try:
        search_pattern = f"%{cleaned_query}%"
        sql_query = """
        SELECT DISTINCT 제품명A, 성분명A, 제품명B, 성분명B 
        FROM druglist 
        WHERE normalize(제품명A) LIKE ? OR normalize(성분명A) LIKE ? OR normalize(제품명B) LIKE ? OR normalize(성분명B) LIKE ?
        """
        search_results = pd.read_sql(sql_query, db_conn, params=(search_pattern, search_pattern, search_pattern, search_pattern))
        
        return search_results

    except Exception as e:
        print(f"DEBUG: find_drug_info (SQL)에서 오류 발생 - {e}")
        return pd.DataFrame()
    

def check_drug_interaction_flexible(db_conn, drug_A_query, drug_B_query):
    """ [수정됨] 괄호/공백 무시 + 부분 검색 + 모호성 감지 로직 (SQL 버전) """
    
    cleaned_A = re.sub(r'[\s\(\)\[\]_/-]|주사제|정제|정|약|캡슐|시럽', '', drug_A_query).strip().lower()
    cleaned_B = re.sub(r'[\s\(\)\[\]_/-]|주사제|정제|정|약|캡슐|시럽', '', drug_B_query).strip().lower()

    if len(cleaned_A) < 2 or len(cleaned_B) < 2:
        return "정보 없음", "약물 이름이 너무 짧습니다. (2글자 이상 입력)"

    pattern_A = f"%{cleaned_A}%"
    pattern_B = f"%{cleaned_B}%"

    try:
        query_a_cols = "(normalize(제품명A) LIKE ? OR normalize(성분명A) LIKE ?)"
        query_b_cols = "(normalize(제품명B) LIKE ? OR normalize(성분명B) LIKE ?)"
        
        sql_query = f"""
        SELECT DISTINCT 제품명A, 제품명B, 상세정보 
        FROM druglist 
        WHERE 
            ({query_a_cols} AND {query_b_cols}) 
            OR 
            ({query_b_cols.replace('B', 'A')} AND {query_a_cols.replace('A', 'B')})
        """
        
        interactions = pd.read_sql(sql_query, db_conn, params=(
            pattern_A, pattern_A, pattern_B, pattern_B,
            pattern_B, pattern_B, pattern_A, pattern_A
        ))

    except Exception as e:
        print(f"DEBUG: check_drug_interaction (SQL)에서 오류 발생 - {e}")
        return "오류", "데이터베이스 검색 중 오류가 발생했습니다."

    if interactions.empty:
        return "안전", f"'{drug_A_query}'와 '{drug_B_query}' 간의 상호작용 정보가 없습니다."

    unique_products = set(interactions['제품명A']).union(set(interactions['제품명B']))
    
    if len(unique_products) > 2:
        risk_level = "정보 확인" 
        warning_msg = f"🔍 **검색 결과가 너무 많습니다.**\n\n'{drug_A_query}' 또는 '{drug_B_query}'에 해당하는 제품/용량이 여러 개 있습니다. 약물 이름을 더 정확하게 입력해주세요.\n(예: '구주염산페치딘주 50mg')"
        return risk_level, warning_msg

    interactions = interactions.drop_duplicates(subset=['상세정보'])
    
    dangerous_keywords = ["사망", "흥분", "정신착란", "금기", "투여 금지", "독성 증가", "치명적인", "심각한", "유산 산성증", "고칼륨혈증", "심실성 부정맥", "위험성 증가", "위험 증가", "심장 부정맥", "QT간격 연장 위험 증가", "QT연장", "심부정맥", "중대한", "심장 모니터링", "병용금기", "Torsade de pointes 위험 증가", "위험이 증가함", "약물이상반응 발생 위험", "독성", "허혈", "혈관경련", ]
    caution_keywords = ["치료 효과가 제한적", "중증의 위장관계 이상반응", "Alfuzosin 혈중농도 증가", "양쪽 약물 모두 혈장농도 상승 가능", "Amiodarone 혈중농도 증가", "혈중농도 증가", "횡문근융해와 같은 중증의 근육이상 보고",  "혈장 농도 증가", "Finerenone 혈중농도의 현저한 증가가 예상됨"]
    
    risk_level, reasons, processed_details = "안전", [], set() 
    for detail in interactions['상세정보'].unique():
        if detail in processed_details: continue
        detail_str = str(detail)
        processed_details.add(detail)
        found_danger = False
        for keyword in dangerous_keywords:
            if keyword in detail_str:
                risk_level = "위험" 
                reasons.append(f"🚨 **위험**: {detail_str}")
                found_danger = True
                break 
        if not found_danger:
            for keyword in caution_keywords:
                if keyword in detail_str:
                    if risk_level != "위험": risk_level = "주의"
                    reasons.append(f"⚠️ **주의**: {detail_str}")
                    break 
    if not reasons:
        risk_level = "정보 확인"
        reasons.append("ℹ️ 상호작용 정보가 있으나, 지정된 위험/주의 키워드는 발견되지 않았습니다. 전문가와 상담하세요.")
    
    return risk_level, "\n\n".join(reasons)

# 3. Streamlit 웹사이트 UI 코드
st.title("💊 약물 상호작용 챗봇")
st.caption("캡스톤 프로젝트: 약물 상호작용 정보 검색 챗봇")

if "messages" not in st.session_state:
    st.session_state.messages = []

if not st.session_state.messages:
    st.session_state.messages.append(
        {"role": "assistant", "content": "안녕하세요! 약물 상호작용 챗봇입니다.\n\n[질문 예시]\n1. 타이레놀 성분이 뭐야?\n2. 타이레놀과 아스피린을 같이 복용해도 돼?"}
    )

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if conn is None:
    st.error("데이터베이스 연결 실패로 챗봇을 실행할 수 없습니다.")
else:
    if prompt := st.chat_input("질문을 입력하세요... (예: 타이레놀과 아스피린)"):
        
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        reply_message = ""
        
        match_component = re.match(r'(.+?)\s*성분[이]?[ ]?(뭐야|알려줘)\??', prompt.strip())
        if match_component:
            drug_name = match_component.group(1).strip('() ')
            if drug_name:
                results = find_drug_info(conn, drug_name)
                if not results.empty:
                    components = set(results['성분명A']).union(set(results['성분명B']))
                    components = {str(d) for d in components if pd.notna(d) and len(str(d)) > 1 and str(d) != 'nan'}
                    
                    if components:
                        reply_message = f"✅ '{drug_name}'의 관련 성분은 다음과 같습니다:\n\n* {', '.join(components)}"
                    else:
                        reply_message = f"ℹ️ '{drug_name}'을(를) 찾았으나, 연관된 성분 정보를 추출하지 못했습니다."
                else:
                    reply_message = f"ℹ️ '{drug_name}'에 대한 정보를 상호작용 데이터베이스에서 찾을 수 없습니다."
            else:
                reply_message = "❌ 어떤 약물의 성분을 알고 싶으신가요? 약물 이름을 입력해주세요."
        
        match_interaction = re.match(r'(.+?)\s*(?:이랑|랑|과|와|하고)\s+(.+?)(?:를|을)?\s+(?:같이|함께)\s+(?:복용해도|먹어도)\s+(?:돼|되나|될까|되나요)\??', prompt.strip())
        
        if not match_interaction:
             match_interaction_simple = re.match(r'^\s*([^\s]+)\s+([^\s]+)\s*$', prompt.strip())
             if match_interaction_simple:
                 match_interaction = match_interaction_simple

        if match_interaction and not reply_message:
            drug_A_query = match_interaction.group(1).strip('() ')
            drug_B_query = match_interaction.group(2).strip('() ')
            
            if drug_A_query and drug_B_query:
                with st.spinner(f"🔄 '{drug_A_query}'와 '{drug_B_query}' 상호작용 검색 중..."):
                    risk, explanation = check_drug_interaction_flexible(conn, drug_A_query, drug_B_query)
                
                if risk == "정보 없음":
                    reply_message = f"**💊 약물 상호작용 위험도: 정보 없음**\n\n**💡 상세 정보:**\n\n{explanation}"
                else:
                    reply_message = f"**💊 약물 상호작용 위험도: {risk}**\n\n**💡 상세 정보:**\n\n{explanation}"
            else:
                reply_message = "❌ 두 약물 이름을 정확히 입력해주세요. 예: (A)약물과 (B)약물을 같이 복용해도 돼?"
        
        elif not match_component and not match_interaction:
            reply_message = "🤔 죄송합니다. 질문 형식을 이해하지 못했습니다.\n\n  **[질문 예시]**\n  * 타이레놀과 아스피린\n  * 타이레놀 성분이 뭐야?"

        st.session_state.messages.append({"role": "assistant", "content": reply_message})
        with st.chat_message("assistant"):
            st.markdown(reply_message)