
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI
from langchain_neo4j import Neo4jGraph

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from global_search.neo4j_global_search import Neo4jGlobalSearch

load_dotenv()

def main():
    query = "這份契約的主要風險有哪些？"
    print(f"\n🔍 Querying Neo4j Global Search: {query}")
    print("-" * 50)

    try:
        graph = Neo4jGraph(
            url=os.getenv("NEO4J_URI"),
            username=os.getenv("NEO4J_USER", "neo4j"),
            password=os.getenv("NEO4J_PASSWORD"),
        )
        
        llm = AzureChatOpenAI(
            azure_deployment=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o-mini"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        )
        
        # Initialize Global Search
        # Using max_communities=5 to get a good balance of speed and coverage for this demo
        global_search = Neo4jGlobalSearch(graph=graph, llm=llm, level=0, max_communities=5)
        
        # Execute search
        answer = global_search.search(query, verbose=True)
        
        print("\n" + "="*50)
        print("💡 Neo4j Global Search Answer:")
        print("="*50)
        print(answer)
        print("="*50)

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
