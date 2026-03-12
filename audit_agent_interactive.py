
import pandas as pd
import json
import os
from pathlib import Path
from typing import Dict, List, Optional
from dotenv import load_dotenv
from openai import AzureOpenAI
from datetime import datetime

from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
from langchain_neo4j import Neo4jGraph
from local_search import Neo4jLocalSearch

# 載入環境變數
load_dotenv()

# ==========================================
# 配置区
# ==========================================

RULES_FILE = "/home/boya/Sino_ISO/錯誤樣態.xlsx"
OUTPUT_DIR = Path(__file__).parent / "audit_reports"
OUTPUT_DIR.mkdir(exist_ok=True)


# Azure OpenAI 配置（用於 Query Generation + 合規分析）
client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
)

DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o-mini")


# ==========================================
# 核心功能
# ==========================================

def load_audit_rules(filepath: str) -> List[Dict]:
    """載入稽核規則"""
    try:
        df = pd.read_excel(filepath)
        df.columns = df.columns.str.strip()

        rules = []
        for index, row in df.iterrows():
            rule = {
                "id": f"RULE_{index+1:03d}",
                "category": str(row.get('檢核項目', '')).strip(),
                "risk_pattern": str(row.get('錯誤樣態/提醒項目', '')).strip(),
                "action": str(row.get('投標前應採行動', '')).strip(),
                "explanation": str(row.get('釋疑內容', '')).strip()
            }
            rules.append(rule)

        return rules

    except Exception as e:
        print(f"❌ 讀取規則檔案失敗: {e}")
        return []


def generate_optimized_query(rule: Dict) -> Dict:
    """
    Query Generation Agent
    將稽核規則轉換成優化的 GraphRAG Local Search 查詢
    """
    system_prompt = """你是一位專業的契約檢索查詢優化專家。

    你的任務是將稽核規則轉換成適合 GraphRAG Local Search 的查詢語句。

    優化原則：
    1. **擴展關鍵詞**：包含同義詞、相關術語、法律用語
    2. **明確目標**：清楚說明要找什麼資訊（受益人、金額、期限等）
    3. **結構化提問**：使用「是否」、「誰」、「多少」、「如何」等明確問法
    4. **指定範圍**：明確要檢索的條款類型或章節

    範例：
    輸入規則：
    - 檢核項目: 責任險
    - 錯誤樣態: 甲方/機關為受益人

    優化查詢：
    「請檢索契約中關於『責任險』或『專業責任險』的條款，確認保險單的『受益人』或『賠款受領人』是誰？是否有約定機關（甲方）為受益人？」

    請以 JSON 格式返回：
    {
    "graph_query": "優化後的完整查詢語句",
    "key_terms": ["關鍵詞1", "關鍵詞2"],
    "search_focus": "檢索重點的簡短說明"
    }
    """

    user_prompt = f"""請為以下稽核規則生成優化的查詢語句：

    【稽核規則】
    檢核項目: {rule['category']}
    錯誤樣態/風險點: {rule['risk_pattern']}
    標準釋疑內容: {rule['explanation']}

    請生成優化的 GraphRAG Local Search 查詢。
    """

    try:
        response = client.chat.completions.create(
            model=DEPLOYMENT_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
        )

        result = json.loads(response.choices[0].message.content)
        return result

    except Exception as e:
        print(f"⚠️ 查詢生成失敗: {e}")
        # 降級到簡單查詢
        return {
            "graph_query": f"請檢索契約中關於『{rule['category']}』的條款，特別關注『{rule['risk_pattern']}』的相關規定。",
            "key_terms": [rule['category'], rule['risk_pattern']],
            "search_focus": "基礎檢索"
        }


_neo4j_search: Optional[Neo4jLocalSearch] = None


def get_neo4j_search() -> Neo4jLocalSearch:
    """Lazy 初始化 Neo4jLocalSearch 單例（首次呼叫時才連線）"""
    global _neo4j_search
    if _neo4j_search is None:
        print("\n🔧 初始化 Neo4j Local Search...")
        graph = Neo4jGraph(
            url=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            username=os.getenv("NEO4J_USER", "neo4j"),
            password=os.getenv("NEO4J_PASSWORD"),
        )
        llm = AzureChatOpenAI(
            azure_deployment=DEPLOYMENT_NAME,
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            max_retries=3,
            request_timeout=60,
        )
        embeddings = AzureOpenAIEmbeddings(
            azure_deployment=os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-large"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        )
        _neo4j_search = Neo4jLocalSearch(graph, llm, embeddings)
        print("✅ Neo4j Local Search 初始化完成\n")
    return _neo4j_search


def query_contract_local_search(query: str) -> Dict:
    """
    直接使用 Neo4jLocalSearch 查詢契約

    Args:
        query: 優化後的查詢語句

    Returns:
        Dict: 查詢結果
    """
    print(f"\n   🔍 執行 Local Search...")

    try:
        search = get_neo4j_search()
        answer = search.search(query, max_hops=2)

        return {
            "success": True,
            "answer": answer,
        }

    except Exception as e:
        print(f"   ❌ Local Search 失敗: {e}")
        return {
            "success": False,
            "answer": f"查詢錯誤: {str(e)}",
        }


def analyze_compliance(rule: Dict, query_info: Dict, rag_result: Dict) -> Dict:
    """
    使用 LLM 分析合規性
    """
    system_prompt = """你是一位專業的政府採購契約稽核專家。

    你的任務是根據「稽核規則」和「契約檢索結果」，判斷契約是否符合規範。

    判斷標準：
    1. **RISK_DETECTED (風險偵測)**：契約內容明確包含錯誤樣態，或缺少必要條款
    2. **COMPLIANT (合規)**：契約內容符合規範，未發現錯誤樣態
    3. **UNCERTAIN (不確定)**：檢索資訊不足，無法明確判斷
    4. **NOT_APPLICABLE (不適用)**：規則不適用於此契約類型

    風險等級：
    - HIGH: 嚴重違規，可能導致法律糾紛或重大損失
    - MEDIUM: 中度風險，建議修正
    - LOW: 輕微問題，提醒注意

    請以 JSON 格式返回：
    {
    "status": "RISK_DETECTED | COMPLIANT | UNCERTAIN | NOT_APPLICABLE",
    "severity": "HIGH | MEDIUM | LOW",
    "reason": "判斷理由（150字內）",
    "evidence": "契約中的關鍵證據文字（直接引用）",
    "clause_reference": "條款編號或位置",
    "recommendation": "建議行動"
    }
    """

    user_prompt = f"""【稽核規則】
    檢核項目: {rule['category']}
    錯誤樣態: {rule['risk_pattern']}
    標準釋疑: {rule['explanation']}

    【優化查詢】
    {query_info['graph_query']}

    【契約檢索結果】
    {rag_result.get('answer', '無檢索結果')}

    請根據上述資訊進行合規性判斷。
    """

    try:
        response = client.chat.completions.create(
            model=DEPLOYMENT_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
        )

        result = json.loads(response.choices[0].message.content)
        return result

    except Exception as e:
        print(f"   ⚠️ 合規分析失敗: {e}")
        return {
            "status": "ERROR",
            "severity": "UNKNOWN",
            "reason": f"分析錯誤: {str(e)}",
            "evidence": "",
            "clause_reference": "",
            "recommendation": "需人工審查"
        }


def preview_and_confirm(rule: Dict, query_info: Dict) -> bool:
    """
    預覽生成的查詢，等待使用者確認

    Returns:
        bool: True 繼續執行，False 跳過
    """
    print("\n" + "="*80)
    print("📋 查詢預覽")
    print("="*80)
    print(f"\n【稽核規則】")
    print(f"  規則編號: {rule['id']}")
    print(f"  檢核項目: {rule['category']}")
    print(f"  錯誤樣態: {rule['risk_pattern']}")
    print(f"\n【Query Generation Agent 生成的查詢】")
    print(f"  查詢語句: {query_info['graph_query']}")
    print(f"  關鍵詞: {', '.join(query_info['key_terms'])}")
    print(f"  檢索重點: {query_info['search_focus']}")
    print(f"\n【查詢引擎】")
    print(f"  Local Search (強制)")
    print("="*80)

    while True:
        choice = input("\n是否執行此查詢？(y)執行 / (e)編輯查詢 / (s)跳過 / (q)退出: ").strip().lower()

        if choice == 'y':
            return True
        elif choice == 's':
            print("⏭️  跳過此規則\n")
            return False
        elif choice == 'q':
            print("👋 程式退出")
            exit(0)
        elif choice == 'e':
            print("\n請輸入修改後的查詢語句（留空使用原查詢）:")
            new_query = input("> ").strip()
            if new_query:
                query_info['graph_query'] = new_query
                query_info['search_focus'] = "使用者自訂"
                print(f"✅ 查詢已更新為: {new_query}")
            return True
        else:
            print("⚠️  無效輸入，請重新選擇")


def display_rule_menu(rules: List[Dict]) -> Optional[Dict]:
    """
    顯示規則選單，讓使用者選擇

    Returns:
        Optional[Dict]: 選中的規則，或 None
    """
    print("\n" + "="*80)
    print("📚 可用的稽核規則")
    print("="*80)

    for idx, rule in enumerate(rules, 1):
        print(f"{idx:2d}. [{rule['id']}] {rule['category']} - {rule['risk_pattern']}")

    print("="*80)

    while True:
        choice = input("\n請選擇要測試的規則編號 (1-{}) 或 (a)全部執行 / (q)退出: ".format(len(rules))).strip().lower()

        if choice == 'q':
            return None
        elif choice == 'a':
            return 'all'
        elif choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(rules):
                return rules[idx - 1]
            else:
                print(f"⚠️  請輸入 1-{len(rules)} 之間的數字")
        else:
            print("⚠️  無效輸入")


def save_result(rule: Dict, query_info: Dict, rag_result: Dict, compliance: Dict):
    """
    儲存單個稽核結果到檔案
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = OUTPUT_DIR / f"稽核_{rule['id']}_{timestamp}.json"

    result = {
        "timestamp": datetime.now().isoformat(),
        "rule": rule,
        "query_generation": query_info,
        "local_search_result": {
            "success": rag_result.get("success", False),
            "answer": rag_result.get("answer", "")
        },
        "compliance_analysis": compliance
    }

    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n💾 結果已儲存: {filename}")


def audit_single_rule(rule: Dict):
    """
    稽核單個規則的完整流程
    """
    print(f"\n{'='*80}")
    print(f"🔍 開始稽核: {rule['id']} - {rule['category']}")
    print(f"{'='*80}")

    # 步驟 1: Query Generation Agent
    print("\n📝 步驟 1: Query Generation Agent 優化查詢...")
    query_info = generate_optimized_query(rule)
    print(f"   ✅ 查詢已生成")

    # 步驟 2: 預覽確認
    if not preview_and_confirm(rule, query_info):
        return

    # 步驟 3: Local Searchee
    print("\n🔍 步驟 2: 執行 Local Search...")
    rag_result = query_contract_local_search(query_info['graph_query'])

    if rag_result['success']:
        print(f"   ✅ 查詢成功")
        print(f"\n   【檢索結果預覽】")
        answer_preview = rag_result['answer'][:300] + "..." if len(rag_result['answer']) > 300 else rag_result['answer']
        print(f"   {answer_preview}")
    else:
        print(f"   ❌ 查詢失敗")

    # 步驟 4: 合規分析
    print("\n🤖 步驟 3: LLM 合規性分析...")
    compliance = analyze_compliance(rule, query_info, rag_result)

    # 顯示結果
    print(f"\n{'='*80}")
    print(f"📊 稽核結果")
    print(f"{'='*80}")
    print(f"  判斷結果: {compliance['status']}")
    print(f"  風險等級: {compliance['severity']}")
    print(f"  判斷理由: {compliance['reason']}")
    print(f"  契約證據: {compliance.get('evidence', 'N/A')[:150]}")
    print(f"  建議行動: {compliance['recommendation']}")
    print(f"{'='*80}")

    # 儲存結果
    save_result(rule, query_info, rag_result, compliance)


# ==========================================
# 主程序
# ==========================================

def main():
    """主程式"""
    print("\n" + "="*80)
    print("🚀 契約自動稽核代理人 - 互動式測試版")
    print("="*80)

    # 載入規則
    print("\n📋 載入稽核規則...")
    rules = load_audit_rules(RULES_FILE)

    if not rules:
        print("❌ 無法載入規則")
        return

    print(f"✅ 成功載入 {len(rules)} 條規則")

    # 互動式選擇
    while True:
        selected = display_rule_menu(rules)

        if selected is None:
            print("\n👋 再見！")
            break
        elif selected == 'all':
            # 全部執行
            print(f"\n🚀 開始執行全部 {len(rules)} 條規則...")
            for idx, rule in enumerate(rules, 1):
                print(f"\n{'#'*80}")
                print(f"# 進度: {idx}/{len(rules)}")
                print(f"{'#'*80}")
                audit_single_rule(rule)
            print("\n✅ 全部稽核完成！")
            break
        else:
            audit_single_rule(selected)
            continue_choice = input("\n是否繼續稽核其他規則？(y/n): ").strip().lower()
            if continue_choice != 'y':
                print("\n👋 再見！")
                break


if __name__ == "__main__":
    main()
