"""
Agentic Legal Graph RAG System

基於 LangChain v1.1 & LangGraph 的雙引擎智能問答系統
專門處理 Microsoft GraphRAG 生成的法律契約知識圖譜

Author: Boya
Version: 1.0.0
"""

__version__ = "1.0.0"
__author__ = "Boya"

from .state import AgentState
from .graph import create_agent_graph
from .main import run_agent

__all__ = ["AgentState", "create_agent_graph", "run_agent"]
