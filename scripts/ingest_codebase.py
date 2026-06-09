"""
Script to index SSAB.OX codebase into Knowledge Base.

Usage:
    python scripts/ingest_codebase.py
    python scripts/ingest_codebase.py --clear
    python scripts/ingest_codebase.py --limit 50
    python scripts/ingest_codebase.py --stats
"""

import sys
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.codebase_service import get_codebase_service


def main():
    parser = argparse.ArgumentParser(description="Index codebase into KB")
    parser.add_argument("--limit", type=int, default=None, help="Max files to index")
    parser.add_argument("--clear", action="store_true", help="Clear before indexing")
    parser.add_argument("--stats", action="store_true", help="Show stats only")
    parser.add_argument("--search", type=str, help="Test search query")
    args = parser.parse_args()
    
    service = get_codebase_service()
    
    # Stats only
    if args.stats:
        stats = service.get_stats()
        print(f"\n📊 Codebase Stats:")
        print(f"   Total files: {stats['total_files']}")
        print(f"   Collection: {stats['collection_name']}")
        print(f"   Repo: {stats['repo_path']}")
        return
    
    # Test search
    if args.search:
        print(f"\n🔍 Searching: {args.search}")
        results = service.search(args.search, n_results=args.limit or 5)
        for i, r in enumerate(results):
            print(f"\n--- Result {i+1} ---")
            print(f"File: {r['metadata'].get('relative_path', 'Unknown')}")
            print(f"Distance: {r['distance']:.4f}")
        return
    
    # Clear if requested
    if args.clear:
        print("🗑️  Clearing codebase collection...")
        service.clear()
    
    # Run indexing
    limit_msg = f" (limit: {args.limit})" if args.limit else ""
    print(f"\n🚀 Starting codebase indexing{limit_msg}...")
    print("   This may take a few minutes...\n")
    
    result = service.index_all(limit=args.limit)
    
    print(f"\n✅ Indexing Complete!")
    print(f"   Total files found: {result['total_files']}")
    print(f"   Indexed: {result['indexed']}")
    print(f"   Errors: {result['errors']}")
    print(f"   KB Total: {result['collection_count']}")


if __name__ == "__main__":
    main()