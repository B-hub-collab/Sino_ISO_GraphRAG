"""
探索 Neo4j 中的節點關係
提供多種方式查看和分析節點間的連接
"""

import os
from neo4j import GraphDatabase
from dotenv import load_dotenv
import json

load_dotenv()

uri = os.getenv("NEO4J_URI")
user = os.getenv("NEO4J_USER", "neo4j")
password = os.getenv("NEO4J_PASSWORD")

driver = GraphDatabase.driver(uri, auth=(user, password))

def explore_entity_relationships(entity_name, max_depth=2):
    """探索特定實體的關係網絡"""
    print(f"\n{'='*60}")
    print(f"探索實體: {entity_name}")
    print(f"{'='*60}\n")
    
    with driver.session() as session:
        # 查找實體及其直接關係
        result = session.run("""
            MATCH (e:Entity {title: $name})
            OPTIONAL MATCH (e)-[r:RELATED_TO]-(other:Entity)
            RETURN e, collect({entity: other.title, type: type(r), weight: r.weight, description: r.description}) as relationships
            LIMIT 1
        """, name=entity_name)
        
        record = result.single()
        if not record:
            print(f"找不到實體: {entity_name}")
            return
        
        entity = record['e']
        relationships = record['relationships']
        
        print(f"實體信息:")
        print(f"  標題: {entity['title']}")
        print(f"  類型: {entity['type']}")
        print(f"  描述: {entity['description'][:100] if entity['description'] else 'N/A'}...")
        
        print(f"\n直接關係 ({len([r for r in relationships if r['entity']])} 個):")
        for rel in sorted(relationships, key=lambda x: x.get('weight', 0) or 0, reverse=True)[:10]:
            if rel['entity']:
                print(f"  → {rel['entity']} (權重: {rel.get('weight', 'N/A')})")
                if rel.get('description'):
                    print(f"     {rel['description'][:80]}...")

def find_shortest_path(entity1, entity2):
    """找出兩個實體間的最短路徑"""
    print(f"\n{'='*60}")
    print(f"尋找路徑: {entity1} → {entity2}")
    print(f"{'='*60}\n")
    
    with driver.session() as session:
        result = session.run("""
            MATCH (start:Entity {title: $entity1})
            MATCH (end:Entity {title: $entity2})
            MATCH path = shortestPath((start)-[*..5]-(end))
            RETURN path, length(path) as pathLength
            LIMIT 1
        """, entity1=entity1, entity2=entity2)
        
        record = result.single()
        if not record:
            print(f"找不到路徑")
            return
        
        path_length = record['pathLength']
        print(f"最短路徑長度: {path_length}")
        print(f"\n路徑:")
        
        # 手動展開路徑
        result2 = session.run("""
            MATCH (start:Entity {title: $entity1})
            MATCH (end:Entity {title: $entity2})
            MATCH path = shortestPath((start)-[*..5]-(end))
            UNWIND nodes(path) as node
            RETURN collect(node.title) as nodes
        """, entity1=entity1, entity2=entity2)
        
        nodes = result2.single()['nodes']
        for i, node in enumerate(nodes):
            print(f"  {i+1}. {node}")

def explore_community_network(community_title):
    """探索社群內的關係網絡"""
    print(f"\n{'='*60}")
    print(f"社群網絡: {community_title}")
    print(f"{'='*60}\n")
    
    with driver.session() as session:
        result = session.run("""
            MATCH (c:Community {title: $title})
            MATCH (e:Entity)-[:BELONGS_TO]->(c)
            OPTIONAL MATCH (e)-[r:RELATED_TO]-(other:Entity)-[:BELONGS_TO]->(c)
            WITH c, e, count(distinct r) as connections, collect(distinct other.title)[0..5] as connected_to
            RETURN c.title, c.size, e.title, connections, connected_to
            ORDER BY connections DESC
            LIMIT 10
        """, title=community_title)
        
        print(f"社群內最活躍的實體:")
        for record in result:
            print(f"\n  {record['e.title']}")
            print(f"    連接數: {record['connections']}")
            if record['connected_to']:
                print(f"    連接到: {', '.join(record['connected_to'])}")

def show_relationship_types():
    """顯示所有關係類型及其統計"""
    print(f"\n{'='*60}")
    print(f"關係類型分析")
    print(f"{'='*60}\n")
    
    with driver.session() as session:
        result = session.run("""
            MATCH ()-[r]->()
            RETURN type(r) as relType, count(*) as count
            ORDER BY count DESC
        """)
        
        print("所有關係類型:")
        for record in result:
            print(f"  {record['relType']}: {record['count']} 條")

def find_highly_connected_entities(limit=10):
    """找出連接最多的實體（度中心性）"""
    print(f"\n{'='*60}")
    print(f"連接最多的實體 (度中心性)")
    print(f"{'='*60}\n")
    
    with driver.session() as session:
        result = session.run("""
            MATCH (e:Entity)
            OPTIONAL MATCH (e)-[r:RELATED_TO]-()
            WITH e, count(r) as degree
            WHERE degree > 0
            RETURN e.title, e.type, degree
            ORDER BY degree DESC
            LIMIT $limit
        """, limit=limit)
        
        print(f"Top {limit} 最多連接的實體:")
        for i, record in enumerate(result, 1):
            print(f"  {i}. {record['e.title']} ({record['e.type']})")
            print(f"     連接數: {record['degree']}")

def explore_text_entity_mentions():
    """探索文本單元提及的實體關係"""
    print(f"\n{'='*60}")
    print(f"文本單元與實體的關係")
    print(f"{'='*60}\n")
    
    with driver.session() as session:
        result = session.run("""
            MATCH (t:TextUnit)-[:MENTIONS]->(e:Entity)
            WITH t, collect(e.title)[0..10] as entities, count(e) as entity_count
            RETURN t.id, entity_count, entities
            ORDER BY entity_count DESC
            LIMIT 5
        """)
        
        print("提及最多實體的文本單元:")
        for i, record in enumerate(result, 1):
            print(f"\n  {i}. 文本單元 (提及 {record['entity_count']} 個實體)")
            print(f"     實體: {', '.join(record['entities'])}")

def main():
    """主選單"""
    print("\n" + "="*60)
    print("Neo4j 關係探索工具")
    print("="*60)
    
    # 1. 關係類型統計
    show_relationship_types()
    
    # 2. 最活躍的實體
    find_highly_connected_entities(10)
    
    # 3. 探索特定實體
    print("\n\n" + "="*60)
    print("示例: 探索'工程契約'的關係")
    print("="*60)
    explore_entity_relationships("工程契約")
    
    # 4. 尋找路徑
    print("\n\n" + "="*60)
    print("示例: 尋找路徑")
    print("="*60)
    find_shortest_path("工程契約", "甲方")
    
    # 5. 社群網絡
    print("\n\n" + "="*60)
    print("示例: 探索社群網絡")
    print("="*60)
    explore_community_network("Community 0")
    
    # 6. 文本實體關係
    explore_text_entity_mentions()
    
    driver.close()
    
    print("\n\n" + "="*60)
    print("提示: 您也可以使用 Neo4j Browser 進行視覺化探索")
    print(f"連接到: {uri}")
    print("="*60 + "\n")

if __name__ == "__main__":
    main()
