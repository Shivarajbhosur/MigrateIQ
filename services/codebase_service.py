"""
Codebase Service - Indexes .cs files from SSAB.OX repo into KB.
"""

import os
from pathlib import Path
from typing import List, Dict, Any, Optional

import chromadb

import config
from utils.logger import get_logger

logger = get_logger("codebase_service")


class CodebaseService:
    """Service for indexing codebase into ChromaDB."""
    
    # Folders to exclude
    EXCLUDE_FOLDERS = {
        "bin", "obj", "packages", ".git", ".vs", 
        "node_modules", "TestResults", "Debug", "Release"
    }
    
    # File patterns to exclude
    EXCLUDE_PATTERNS = {
        ".Designer.cs",
        ".g.cs",
        ".g.i.cs",
        "AssemblyInfo.cs",
        "GlobalSuppressions.cs",
        ".AssemblyAttributes.cs"
    }
    
    def __init__(self):
        """Initialize codebase service."""
        self.repo_path = Path(config.SSAB_OX_REPO_PATH)
        
        # KB path
        self.db_path = Path(config.BASE_DIR) / "data" / "knowledge_db"
        self.db_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize ChromaDB
        self.client = chromadb.PersistentClient(path=str(self.db_path))
        
        # Separate collection for codebase
        self.collection = self.client.get_or_create_collection(
            name="codebase",
            metadata={"description": "SSAB.OX .cs source files"}
        )
        
        logger.info(f"Codebase service initialized")
        logger.info(f"Repo path: {self.repo_path}")
        logger.info(f"Collection 'codebase' has {self.collection.count()} entries")
    
    def _should_exclude_folder(self, folder_path: Path) -> bool:
        """Check if folder should be excluded."""
        parts = folder_path.parts
        for part in parts:
            if part.lower() in {f.lower() for f in self.EXCLUDE_FOLDERS}:
                return True
        return False
    
    def _should_exclude_file(self, file_path: Path) -> bool:
        """Check if file should be excluded."""
        filename = file_path.name
        for pattern in self.EXCLUDE_PATTERNS:
            if filename.endswith(pattern):
                return True
        return False
    
    def find_cs_files(self) -> List[Path]:
        """
        Find all .cs files in repo (excluding bin/obj etc).
        
        Returns:
            List of .cs file paths
        """
        cs_files = []
        
        for root, dirs, files in os.walk(self.repo_path):
            root_path = Path(root)
            
            # Skip excluded folders
            if self._should_exclude_folder(root_path):
                continue
            
            # Filter out excluded directories for further walking
            dirs[:] = [d for d in dirs if d.lower() not in {f.lower() for f in self.EXCLUDE_FOLDERS}]
            
            for file in files:
                if file.endswith(".cs"):
                    file_path = root_path / file
                    
                    if not self._should_exclude_file(file_path):
                        cs_files.append(file_path)
        
        logger.info(f"Found {len(cs_files)} .cs files")
        return cs_files
    
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
    
    def index_file(self, file_path: Path) -> bool:
        """
        Index a single .cs file into KB.
        
        Args:
            file_path: Path to .cs file
        
        Returns:
            bool: Success
        """
        try:
            content = self.read_file_content(file_path)
            
            if content is None:
                return False
            
            # Relative path for ID
            try:
                relative_path = file_path.relative_to(self.repo_path)
            except ValueError:
                relative_path = file_path.name
            
            # Create document
            doc_text = f"""
File: {relative_path}
Path: {file_path}

{content}
"""
            
            # Metadata
            metadata = {
                "filename": file_path.name,
                "relative_path": str(relative_path),
                "full_path": str(file_path),
                "extension": ".cs",
                "size_bytes": len(content),
                "source": "codebase"
            }
            
            # Add to collection
            self.collection.upsert(
                ids=[str(relative_path)],
                documents=[doc_text],
                metadatas=[metadata]
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to index {file_path}: {e}")
            return False
    
    def index_all(self, limit: Optional[int] = None) -> Dict[str, Any]:
        """
        Index all .cs files into KB.
        
        Args:
            limit: Max files to index (None = all)
        
        Returns:
            Summary of indexing
        """
        logger.info("Starting codebase indexing...")
        
        cs_files = self.find_cs_files()
        
        if limit:
            cs_files = cs_files[:limit]
        
        indexed = 0
        errors = 0
        
        for i, file_path in enumerate(cs_files):
            if (i + 1) % 50 == 0:
                logger.info(f"Progress: {i + 1}/{len(cs_files)}")
            
            if self.index_file(file_path):
                indexed += 1
            else:
                errors += 1
        
        summary = {
            "success": True,
            "total_files": len(cs_files),
            "indexed": indexed,
            "errors": errors,
            "collection_count": self.collection.count()
        }
        
        logger.info(f"Indexing complete: {summary}")
        return summary
    
    def search(self, query: str, n_results: int = 5) -> List[Dict[str, Any]]:
        """
        Search for relevant code files.
        
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
        Keyword search - finds exact text matches in code.
        
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
            
            # Add keyword results (higher priority)
            for r in keyword_results:
                file_id = r['id']
                combined[file_id] = {
                    "id": file_id,
                    "metadata": r['metadata'],
                    "keyword_match": True,
                    "match_count": r.get('match_count', 0),
                    "semantic_distance": None,
                    "score": 100 + r.get('match_count', 0) * 10  # High score for exact match
                }
            
            # Add semantic results
            for r in semantic_results:
                file_id = r['id']
                distance = r.get('distance', 2.0)
                semantic_score = max(0, (2.0 - distance) * 50)  # Convert distance to score
                
                if file_id in combined:
                    # Already found by keyword - boost score
                    combined[file_id]['semantic_distance'] = distance
                    combined[file_id]['score'] += semantic_score
                else:
                    # Only found by semantic
                    combined[file_id] = {
                        "id": file_id,
                        "metadata": r['metadata'],
                        "keyword_match": False,
                        "match_count": 0,
                        "semantic_distance": distance,
                        "score": semantic_score
                    }
            
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
    
    def get_stats(self) -> Dict[str, Any]:
        """Get codebase collection stats."""
        return {
            "total_files": self.collection.count(),
            "collection_name": "codebase",
            "repo_path": str(self.repo_path)
        }
    
    def clear(self) -> bool:
        """Clear codebase collection."""
        try:
            self.client.delete_collection("codebase")
            self.collection = self.client.get_or_create_collection(
                name="codebase",
                metadata={"description": "SSAB.OX .cs source files"}
            )
            logger.info("Codebase collection cleared")
            return True
        except Exception as e:
            logger.error(f"Failed to clear: {e}")
            return False


# Singleton
_codebase_service: Optional[CodebaseService] = None


def get_codebase_service() -> CodebaseService:
    """Get singleton codebase service."""
    global _codebase_service
    if _codebase_service is None:
        _codebase_service = CodebaseService()
    return _codebase_service
    
    
    
