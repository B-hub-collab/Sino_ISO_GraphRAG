"""Re-export from canonical local_search module."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from local_search.neo4j_local_search import Neo4jLocalSearch

__all__ = ['Neo4jLocalSearch']
