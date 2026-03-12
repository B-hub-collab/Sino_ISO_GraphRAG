"""
Global Search - Neo4j 全域社群摘要搜尋

此模組包含 Global Search 相關的實現：
- neo4j_global_search.py: Neo4j Global Search 核心模組（Map-Reduce）
- test_global_search.py: Global Search 測試套件
"""

from .neo4j_global_search import Neo4jGlobalSearch

__all__ = ['Neo4jGlobalSearch']
