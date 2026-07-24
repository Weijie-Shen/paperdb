"""Search modules — keyword, vector, and hybrid search for PaperDB."""

from paperdb.search.keyword import KeywordSearcher, segment_text
from paperdb.search.vector import VectorSearcher, has_vector_support
from paperdb.search.hybrid import HybridSearcher, reciprocal_rank_fusion
from paperdb.search.indexer import build_index
