"""
設定管理模組

負責讀寫 GUI 設定，並將設定注入 os.environ，
讓現有所有使用 os.getenv() 的模組自動取得正確值。
"""

import json
import os
from pathlib import Path
from typing import Any, Dict

CONFIG_DIR = Path.home() / ".sino_iso_audit"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "azure_openai_endpoint": "",
    "azure_openai_api_key": "",
    "azure_openai_api_version": "2025-01-01-preview",
    "azure_openai_chat_deployment": "o4-mini",
    "azure_openai_embedding_deployment": "text-embedding-3-large",
    "neo4j_uri": "bolt://localhost:7687",
    "neo4j_user": "neo4j",
    "neo4j_password": "",
    "graphrag_api_key": "",
    "rules_file": str(Path.home() / "Sino_ISO" / "錯誤樣態.xlsx"),
    "output_dir": str(Path.home() / "Sino_ISO" / "contracts" / "audit_reports"),
    "graphrag_root": str(Path.home() / "Sino_ISO" / "contracts"),
    "input_dir": str(Path.home() / "Sino_ISO" / "contracts" / "input_graphrag"),
}


def load() -> Dict[str, Any]:
    """載入設定，不存在則返回預設值"""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            config = DEFAULT_CONFIG.copy()
            config.update(data)
            return config
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def save(config: Dict[str, Any]) -> None:
    """儲存設定到檔案"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def inject_to_env(config: Dict[str, Any] = None) -> None:
    """
    將設定注入 os.environ。

    必須在 import audit_agent_interactive 等模組之前呼叫，
    確保模組級 AzureOpenAI() 讀到正確的 API key。
    """
    if config is None:
        config = load()

    mapping = {
        "AZURE_OPENAI_ENDPOINT": config.get("azure_openai_endpoint", ""),
        "AZURE_OPENAI_API_KEY": config.get("azure_openai_api_key", ""),
        "AZURE_OPENAI_API_VERSION": config.get("azure_openai_api_version", "2025-01-01-preview"),
        "AZURE_OPENAI_CHAT_DEPLOYMENT": config.get("azure_openai_chat_deployment", "o4-mini"),
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT": config.get(
            "azure_openai_embedding_deployment", "text-embedding-3-large"
        ),
        "NEO4J_URI": config.get("neo4j_uri", "bolt://localhost:7687"),
        "NEO4J_USER": config.get("neo4j_user", "neo4j"),
        "NEO4J_PASSWORD": config.get("neo4j_password", ""),
        "GRAPHRAG_API_KEY": config.get("graphrag_api_key", ""),
        "GRAPHRAG_ROOT": config.get("graphrag_root", ""),
    }

    for key, value in mapping.items():
        if value:
            os.environ[key] = value
