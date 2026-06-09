"""
COBOL Service - Indexes .COB files into KB.
#ingest_cobol.py → CobolService.index_all() → walks .COB files → upsert(full file content) → ChromaDB embeds with all-MiniLM-L6-v2)(default internaly used in chromadb)
"""

import os
from pathlib import Path
from typing import List, Dict, Any, Optional

import chromadb

import config
from utils.logger import get_logger

logger = get_logger("cobol_service")


class CobolService:
    """Service for indexing COBOL source files into ChromaDB."""
    
    def __init__(self):
        """Initialize COBOL service."""
        self.cobol_path = Path(config.COBOL_SOURCE_PATH)
        
        # KB path
        self.db_path = Path(config.BASE_DIR) / "data" / "knowledge_db"
        self.db_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize ChromaDB
        self.client = chromadb.PersistentClient(path=str(self.db_path))
        
        # Separate collection for COBOL
        self.collection = self.client.get_or_create_collection(
            name="cobol",
            metadata={"description": "COBOL source files (.COB)"}
        )
        
        logger.info(f"COBOL service initialized")
        logger.info(f"COBOL path: {self.cobol_path}")
        logger.info(f"Collection 'cobol' has {self.collection.count()} entries")
    
    def find_cobol_files(self) -> List[Path]:
        """
        Find all .COB files in COBOL source folder.
        
        Returns:
            List of .COB file paths
        """
        cobol_files = []
        
        if not self.cobol_path.exists():
            logger.error(f"COBOL path not found: {self.cobol_path}")
            return cobol_files
        
        # Walk through directory
        for root, dirs, files in os.walk(self.cobol_path):
            root_path = Path(root)
            
            for file in files:
                # Only .COB files (case-insensitive)
                if file.upper().endswith(".COB"):
                    file_path = root_path / file
                    cobol_files.append(file_path)
        
        logger.info(f"Found {len(cobol_files)} .COB files")
        return cobol_files
    
    def read_file_content(self, file_path: Path) -> Optional[str]:
        """Read file content with error handling."""
        try:
            # Try UTF-8 first
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except UnicodeDecodeError:
            try:
                # Fallback to latin-1
                with open(file_path, 'r', encoding='latin-1') as f:
                    return f.read()
            except Exception as e:
                logger.error(f"Failed to read {file_path}: {e}")
                return None
        except Exception as e:
            logger.error(f"Failed to read {file_path}: {e}")
            return None
    
    def extract_program_name(self, file_path: Path) -> str:
        """
        Extract program name from file.
        
        Example: HPPL494P.COB → HPPL494P
        """
        return file_path.stem.upper()
    
    def index_file(self, file_path: Path) -> bool:
        """
        Index a single .COB file into KB.
        
        Args:
            file_path: Path to .COB file
        
        Returns:
            bool: Success
        """
        try:
            content = self.read_file_content(file_path)
            
            if content is None:
                return False
            
            # Get program name
            program_name = self.extract_program_name(file_path)
            
            # Relative path for ID
            try:
                relative_path = file_path.relative_to(self.cobol_path)
            except ValueError:
                relative_path = file_path.name
            
            # Create document
            doc_text = f"""
Program: {program_name}
File: {file_path.name}
Path: {file_path}

{content}
"""
            
            # Metadata
            metadata = {
                "program_name": program_name,
                "filename": file_path.name,
                "relative_path": str(relative_path),
                "full_path": str(file_path),
                "extension": ".COB",
                "size_bytes": len(content),
                "source": "cobol"
            }
            
            # Add to collection
            self.collection.upsert(
                ids=[program_name],  # Use program name as ID for easy lookup
                documents=[doc_text],
                metadatas=[metadata]
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to index {file_path}: {e}")
            return False
    
    def index_all(self, limit: Optional[int] = None) -> Dict[str, Any]:
        """
        Index all .COB files into KB (skips already indexed).
        
        Args:
            limit: Max files to index (None = all)
        
        Returns:
            Summary of indexing
        """
        logger.info("Starting COBOL indexing...")
        
        cobol_files = self.find_cobol_files()
        
        if limit:
            cobol_files = cobol_files[:limit]
        
        # Get already indexed program names
        existing = set()
        try:
            all_ids = self.collection.get()['ids']
            existing = set(all_ids)
            logger.info(f"Already indexed: {len(existing)} programs")
        except:
            pass
        
        indexed = 0
        skipped = 0
        errors = 0
        
        for i, file_path in enumerate(cobol_files):
            if (i + 1) % 100 == 0:
                logger.info(f"Progress: {i + 1}/{len(cobol_files)} (indexed: {indexed}, skipped: {skipped})")
            
            # Skip if already exists
            program_name = self.extract_program_name(file_path)
            if program_name in existing:
                skipped += 1
                continue
            
            if self.index_file(file_path):
                indexed += 1
            else:
                errors += 1
        
        summary = {
            "success": True,
            "total_files": len(cobol_files),
            "indexed": indexed,
            "skipped": skipped,
            "errors": errors,
            "collection_count": self.collection.count()
        }
        
        logger.info(f"Indexing complete: {summary}")
        return summary
    
    def search(self, query: str, n_results: int = 5) -> List[Dict[str, Any]]:
        """
        Semantic search for COBOL code.
        
        Args:
            query: Search query
            n_results: Number of results
        
        Returns:
            List of matching files
        """
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=n_results
            )
            
            matches = []
            if results and results['ids'] and results['ids'][0]:
                for i, doc_id in enumerate(results['ids'][0]):
                    match = {
                        "id": doc_id,
                        "document": results['documents'][0][i] if results['documents'] else "",
                        "metadata": results['metadatas'][0][i] if results['metadatas'] else {},
                        "distance": results['distances'][0][i] if results['distances'] else 0
                    }
                    matches.append(match)
            
            return matches
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []
    
    def search_keyword(self, query: str, n_results: int = 10) -> List[Dict[str, Any]]:
        """
        Keyword search - finds exact text matches in COBOL.
        
        Args:
            query: Text to search for (exact match)
            n_results: Maximum number of results
        
        Returns:
            List of matching files
        """
        try:
            # Get all documents from collection
            all_docs = self.collection.get(
                include=["documents", "metadatas"]
            )
            
            matches = []
            query_lower = query.lower()
            
            if all_docs and all_docs['documents']:
                for i, doc in enumerate(all_docs['documents']):
                    if doc and query_lower in doc.lower():
                        # Count occurrences
                        count = doc.lower().count(query_lower)
                        matches.append({
                            "id": all_docs['ids'][i],
                            "document": doc,
                            "metadata": all_docs['metadatas'][i] if all_docs['metadatas'] else {},
                            "match_count": count,
                            "search_type": "keyword"
                        })
            
            # Sort by match count (more matches = better)
            matches.sort(key=lambda x: x['match_count'], reverse=True)
            
            return matches[:n_results]
            
        except Exception as e:
            logger.error(f"Keyword search failed: {e}")
            return []

    def search_hybrid(self, query: str, n_results: int = 10) -> List[Dict[str, Any]]:
            """
            Hybrid search - combines keyword (exact) and semantic (meaning) search.
            
            Args:
                query: Search query
                n_results: Maximum number of results
            
            Returns:
                Combined and ranked results
            """
            try:
                # Get keyword results (exact match)
                keyword_results = self.search_keyword(query, n_results=n_results)
                
                # Get semantic results (meaning match)
                semantic_results = self.search(query, n_results=n_results)
                
                # Combine results
                combined = {}
                
                # Normalize query for matching
                query_upper = query.upper().strip()
                
                # Add keyword results (higher priority)
                for r in keyword_results:
                    file_id = r['id']
                    combined[file_id] = {
                        "id": file_id,
                        "metadata": r['metadata'],
                        "keyword_match": True,
                        "match_count": r.get('match_count', 0),
                        "semantic_distance": None,
                        "score": 100 + r.get('match_count', 0) * 10
                    }
                
                # Add semantic results
                for r in semantic_results:
                    file_id = r['id']
                    distance = r.get('distance', 2.0)
                    semantic_score = max(0, (2.0 - distance) * 50)
                    
                    if file_id in combined:
                        combined[file_id]['semantic_distance'] = distance
                        combined[file_id]['score'] += semantic_score
                    else:
                        combined[file_id] = {
                            "id": file_id,
                            "metadata": r['metadata'],
                            "keyword_match": False,
                            "match_count": 0,
                            "semantic_distance": distance,
                            "score": semantic_score
                        }
                
                # Boost exact program name match
                for file_id, result in combined.items():
                    program_name = file_id.upper().strip()
                    
                    # Exact match - BIG boost
                    if program_name == query_upper:
                        result['score'] += 500
                        result['exact_match'] = True
                    # Starts with query - medium boost
                    elif program_name.startswith(query_upper):
                        result['score'] += 50
                        result['exact_match'] = False
                    # Query is part of program name - small boost
                    elif query_upper in program_name:
                        result['score'] += 25
                        result['exact_match'] = False
                    else:
                        result['exact_match'] = False
                
                # Sort by score (highest first)
                results = sorted(combined.values(), key=lambda x: x['score'], reverse=True)
                
                # Fetch content for top results
                top_results = results[:n_results]
                if top_results:
                    ids_to_fetch = [r['id'] for r in top_results]
                    docs = self.collection.get(ids=ids_to_fetch, include=['documents'])
                    
                    # Map id -> content
                    id_to_content = {}
                    for i, doc_id in enumerate(docs['ids']):
                        if docs['documents'] and i < len(docs['documents']):
                            id_to_content[doc_id] = docs['documents'][i]
                    
                    # Add content to results
                    for r in top_results:
                        r['content'] = id_to_content.get(r['id'], '')
                
                return top_results
                
            except Exception as e:
                logger.error(f"Hybrid search failed: {e}")
                return []
    
    def get_by_program_name(self, program_name: str) -> Optional[Dict[str, Any]]:
        """
        Get COBOL code by exact program name.
        
        Args:
            program_name: Program name (e.g., HPPL494P)
        
        Returns:
            COBOL document or None
        """
        try:
            result = self.collection.get(
                ids=[program_name.upper()],
                include=["documents", "metadatas"]
            )
            
            if result and result['ids']:
                return {
                    "id": result['ids'][0],
                    "document": result['documents'][0] if result['documents'] else "",
                    "metadata": result['metadatas'][0] if result['metadatas'] else {}
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get program {program_name}: {e}")
            return None
    
    def get_stats(self) -> Dict[str, Any]:
        """Get COBOL collection stats."""
        return {
            "total_files": self.collection.count(),
            "collection_name": "cobol",
            "cobol_path": str(self.cobol_path)
        }
    
    def clear(self) -> bool:
        """Clear COBOL collection."""
        try:
            self.client.delete_collection("cobol")
            self.collection = self.client.get_or_create_collection(
                name="cobol",
                metadata={"description": "COBOL source files (.COB)"}
            )
            logger.info("COBOL collection cleared")
            return True
        except Exception as e:
            logger.error(f"Failed to clear: {e}")
            return False


# Singleton
_cobol_service: Optional[CobolService] = None


def get_cobol_service() -> CobolService:
    """Get singleton COBOL service."""
    global _cobol_service
    if _cobol_service is None:
        _cobol_service = CobolService()
    return _cobol_service