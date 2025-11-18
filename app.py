import streamlit as st
import pandas as pd
import re
import sqlite3
import gdown
import os

# 1. 데이터 로드
@st.cache_resource
def load_data():
    """druglist.db 파일을 다운로드하고 연결합니다."""
    file_path = r'druglist.db'
    try:
        if not os.path.exists(file_path):
            # 구글 드라이브 파일 ID (본인의 파일 ID로 변경 필요 시 수정)
            GDRIVE_FILE_ID = '11B6_WtJWs5AIfCAbN67F2sqaAkWCyJob' 
            st.info(f"'{file_path}' 파일이 없어 Google Drive에서 다운로드합니다... (시간이 걸릴 수 있습니다)")
            gdown.download(id=GDRIVE_FILE_ID, output=file_path, quiet=False, fuzzy=True)
            st.info("데이터베이스 다운로드 완료!")

        conn = sqlite3.connect(file_path, check_same_thread=False)
        
        def normalize_text(text):
            if text is None: return None
            return re.sub(r'[\s\(\)\[\]_/-]|주사제|정제|정|약|캡슐|시럽', '', str(text)).strip().lower()
        conn.create_function("normalize", 1, normalize_text)
        
        print("✅ (Streamlit) 약물 데이터베이스 로드 성공!")
        return conn
    except Exception as e:
        st.error(f"❌ 데이터베이스 로드 실패: {e}")
        return None

conn = load_data()

# 2. 검색 함수들
def find_drug_info(db_conn, query):
    """SQL을 사용해 DB에서 검색하고 DataFrame을 반환합니다."""
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
        return pd.read_sql(sql_query, db_conn, params=(search_pattern, search_pattern, search_pattern, search_pattern))
    except Exception as e:
        print(f"DEBUG: find_drug_info 오류 - {e}")
        return pd.DataFrame()

def check_drug_interaction_flexible(db_conn, drug_A_query, drug_B_query):
    """상호작용 검색 함수"""
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
        interactions = pd.read_sql(sql_query, db_conn, params=(pattern_A, pattern_A, pattern_B, pattern_B, pattern_B, pattern_B, pattern_A, pattern_A))

    except Exception as e:
        return "오류", "데이터베이스 검색 중 오류가 발생했습니다."

    if interactions.empty:
        return "안전", f"'{drug_A_query}'와 '{drug_B_query}' 간의 상호작용 정보가 없습니다."

    unique_products = set(interactions['제품명A']).union(set(interactions['제품명B']))
    if len(unique_products) > 2:
        risk_level = "정보 확인" 
        warning_msg = f"🔍 **검색 결과가 너무 많습니다.**\n\n해당하는 제품/용량이 여러 개 있습니다. 약물 이름을 더 정확하게 입력해주세요.\n(예: '구주염산페치딘주 50mg')"
        return risk_level, warning_msg

    interactions = interactions.drop_duplicates(subset=['상세정보'])
    
    dangerous_keywords = ["사망", "흥분", "정신착란", "금기", "투여 금지", "독성 증가", "치명적인", "심각한", "유산 산성증", "고칼륨혈증", "심실성 부정맥", "위험성 증가", "위험 증가", "심장 부정맥", "QT간격 연장 위험 증가", "QT연장", "심부정맥", "중대한", "심장 모니터링", "병용금기", "Torsade de pointes 위험 증가", "위험이 증가함", "약물이상반응 발생 위험", "독성", "허혈", "혈관경련", ]
    caution_keywords = ["치료 효과가 제한적", "중증의 위장관계 이상반응", "Alfuzosin 혈중농도 증가", "양쪽 약물 모두 혈장농도 상승 가능", "Amiodarone 혈중농도 증가", "혈중농도 증가", "횡문근융해와 같은 중증의 근육이상 보고",  "혈장 농도 증가", "Finerenone 혈중농도의 현저한 증가가 예상됨"]
    
    risk_level = "안전"
    reasons = []
    processed_details = set() 
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

# --- 3. UI 및 로직 ---
st.title("💊 약물 상호작용 챗봇")
st.caption("캡스톤 프로젝트: 약물 상호작용 정보 검색 챗봇")

if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "안녕하세요! 약물 상호작용 챗봇입니다.\n\n[질문 예시]\n1. 타이레놀 성분이 뭐야?\n2. 타이레놀과 아스피린을 같이 복용해도 돼?"}]

# [기능 추가] 선택지 상태 관리
if "selection_mode" not in st.session_state:
    st.session_state.selection_mode = False
if "selection_options" not in st.session_state:
    st.session_state.selection_options = []
if "original_query" not in st.session_state:
    st.session_state.original_query = ""

# 이전 대화 기록 표시
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# [기능 추가] 선택지가 있을 경우 버튼 표시
if st.session_state.selection_mode:
    st.write("👇 **원하는 제품을 선택해주세요:**")
    
    # 버튼을 가로로 나열하거나 세로로 나열
    cols = st.columns(min(len(st.session_state.selection_options), 3)) # 최대 3열
    
    for i, option in enumerate(st.session_state.selection_options):
        # 버튼 클릭 시 동작
        if st.button(option, key=f"btn_{i}"):
            # 1. 사용자가 선택한 내용을 대화창에 표시 (선택한 척)
            st.session_state.messages.append({"role": "user", "content": f"{option} 선택"})
            
            # 2. 선택한 약물에 대한 성분 검색 수행
            results = find_drug_info(conn, option)
            
            # 선택한 'option'과 정확히 일치하는 성분만 추출
            components = set()
            # 이름에 괄호 등이 있을 수 있으므로 escape 처리
            target_pattern = re.escape(option)
            
            for _, row in results.iterrows():
                if pd.notna(row['제품명A']) and re.search(target_pattern, row['제품명A'], re.IGNORECASE):
                    if pd.notna(row['성분명A']): components.add(row['성분명A'])
                if pd.notna(row['제품명B']) and re.search(target_pattern, row['제품명B'], re.IGNORECASE):
                    if pd.notna(row['성분명B']): components.add(row['성분명B'])
            
            components = {str(d) for d in components if pd.notna(d) and len(str(d)) > 1 and str(d) != 'nan'}
            
            if components:
                final_response = f"✅ **'{option}'**의 성분은 다음과 같습니다:\n\n* {', '.join(components)}"
            else:
                final_response = f"ℹ️ '{option}'을(를) 선택하셨으나, 성분 정보를 찾을 수 없습니다."

            # 3. 답변 저장 및 상태 초기화
            st.session_state.messages.append({"role": "assistant", "content": final_response})
            st.session_state.selection_mode = False
            st.session_state.selection_options = []
            st.rerun() # 화면 새로고침

# 사용자 입력 처리 (선택 모드가 아닐 때만 입력 가능하게 하거나, 항상 열어둠)
if not st.session_state.selection_mode:
    if prompt := st.chat_input("질문을 입력하세요..."):
        
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        reply_message = ""

        # --- 1. 성분 질문 분석 ---
        match_component = re.match(r'(.+?)\s*성분[이]?[ ]?(뭐야|알려줘)\??', prompt.strip())
        
        if match_component:
            drug_name = match_component.group(1).strip('() ')
            if drug_name:
                results = find_drug_info(conn, drug_name)
                
                if not results.empty:
                    # 관련된 모든 제품명 찾기
                    # 제품명A와 제품명B 컬럼에서 검색어가 포함된 제품명들을 싹 긁어모음
                    found_products = set()
                    target_clean = re.sub(r'[\s\(\)\[\]_/-]|주사제|정제|정|약|캡슐|시럽', '', drug_name).strip().lower()
                    
                    for _, row in results.iterrows():
                        # A컬럼 확인
                        val_a = str(row['제품명A']).lower()
                        clean_a = re.sub(r'[\s\(\)\[\]_/-]|주사제|정제|정|약|캡슐|시럽', '', val_a)
                        if target_clean in clean_a and pd.notna(row['제품명A']):
                            found_products.add(row['제품명A'])
                        
                        # B컬럼 확인
                        val_b = str(row['제품명B']).lower()
                        clean_b = re.sub(r'[\s\(\)\[\]_/-]|주사제|정제|정|약|캡슐|시럽', '', val_b)
                        if target_clean in clean_b and pd.notna(row['제품명B']):
                            found_products.add(row['제품명B'])
                    
                    found_products = sorted(list(found_products))

                    # [핵심 기능] 결과가 2개 이상이면 선택지 제공
                    if len(found_products) > 1:
                        reply_message = f"🔍 **'{drug_name}'** 관련 제품이 **{len(found_products)}개** 발견되었습니다.\n아래에서 원하시는 제품을 선택해주세요."
                        st.session_state.selection_mode = True
                        st.session_state.selection_options = found_products
                        st.session_state.original_query = drug_name
                        
                    # 결과가 1개면 바로 보여줌
                    elif len(found_products) == 1:
                        product = found_products[0]
                        # 다시 그 제품명으로 성분 찾기 (위의 버튼 클릭 로직과 동일)
                        components = set()
                        t_pat = re.escape(product)
                        for _, row in results.iterrows():
                            if pd.notna(row['제품명A']) and re.search(t_pat, row['제품명A'], re.IGNORECASE):
                                if pd.notna(row['성분명A']): components.add(row['성분명A'])
                            if pd.notna(row['제품명B']) and re.search(t_pat, row['제품명B'], re.IGNORECASE):
                                if pd.notna(row['성분명B']): components.add(row['성분명B'])
                        
                        components = {str(d) for d in components if pd.notna(d) and len(str(d)) > 1 and str(d) != 'nan'}
                        reply_message = f"✅ **'{product}'**의 성분은 다음과 같습니다:\n\n* {', '.join(components)}"
                    
                    else:
                        # 제품명은 없는데 성분명으로만 매칭된 경우 등
                        reply_message = f"ℹ️ '{drug_name}'에 대한 정확한 제품 정보를 찾을 수 없습니다."

                else:
                    reply_message = f"❌ '{drug_name}' 정보를 찾을 수 없습니다."
            else:
                reply_message = "❌ 약물 이름을 입력해주세요."

        # --- 2. 상호작용 질문 분석 ---
        else:
            match_interaction = re.match(r'(.+?)\s*(?:이랑|랑|과|와|하고)\s+(.+?)(?:를|을)?\s+(?:같이|함께)\s+(?:복용해도|먹어도)\s+(?:돼|되나|될까|되나요)\??', prompt.strip())
            if not match_interaction:
                match_interaction_simple = re.match(r'^\s*([^\s]+)\s+([^\s]+)\s*$', prompt.strip())
                if match_interaction_simple:
                    match_interaction = match_interaction_simple

            if match_interaction:
                drug_A = match_interaction.group(1).strip('() ')
                drug_B = match_interaction.group(2).strip('() ')
                
                if drug_A and drug_B:
                    with st.spinner(f"🔄 '{drug_A}'와 '{drug_B}' 분석 중..."):
                        risk, explanation = check_drug_interaction_flexible(conn, drug_A, drug_B)
                    
                    if risk == "정보 없음":
                        reply_message = f"**💊 분석 불가**\n\n{explanation}"
                    else:
                        reply_message = f"**💊 위험도: {risk}**\n\n**💡 상세 정보:**\n\n{explanation}"
                else:
                    reply_message = "❌ 두 약물 이름을 정확히 입력해주세요."
            
            elif not match_component:
                reply_message = "🤔 죄송합니다. 질문 형식을 이해하지 못했습니다."

        # 챗봇 응답 표시
        if reply_message:
            st.session_state.messages.append({"role": "assistant", "content": reply_message})
            with st.chat_message("assistant"):
                st.markdown(reply_message)
            
            # 선택 모드가 활성화되었다면 즉시 화면 갱신하여 버튼 보여주기
            if st.session_state.selection_mode:
                st.rerun()