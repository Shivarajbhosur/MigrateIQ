"""
Ingest COBOL source files into Knowledge Base.

Usage:
    python scripts/ingest_cobol.py              # Index all .COB files
    python scripts/ingest_cobol.py --limit 10   # Index first 10 files
    python scripts/ingest_cobol.py --clear      # Clear and re-index all
    python scripts/ingest_cobol.py --stats      # Show stats only
    python scripts/ingest_cobol.py --search "HPPL494P"  # Test search
"""

import sys
import argparse
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.cobol_service import get_cobol_service


def main():
    parser = argparse.ArgumentParser(description="Ingest COBOL files into KB")
    parser.add_argument("--limit", type=int, help="Max files to index")
    parser.add_argument("--clear", action="store_true", help="Clear collection before indexing")
    parser.add_argument("--stats", action="store_true", help="Show stats only")
    parser.add_argument("--search", type=str, help="Test search query")
    parser.add_argument("--program", type=str, help="Get specific program by name")
    args = parser.parse_args()
    
    service = get_cobol_service()
    
    # Stats only
    if args.stats:
        stats = service.get_stats()
        print(f"\n📊 COBOL Stats:")
        print(f"   Total files: {stats['total_files']}")
        print(f"   Collection: {stats['collection_name']}")
        print(f"   COBOL path: {stats['cobol_path']}")
        return
    
    # Get specific program
    if args.program:
        print(f"\n🔍 Getting program: {args.program}")
        result = service.get_by_program_name(args.program)
        if result:
            meta = result['metadata']
            print(f"\n--- {result['id']} ---")
            print(f"File: {meta.get('filename', 'N/A')}")
            print(f"Size: {meta.get('size_bytes', 0)} bytes")
            print(f"\nFirst 500 chars of code:")
            print(result['document'][:500])
        else:
            print(f"❌ Program not found: {args.program}")
        return
    
    # Test search
    if args.search:
        print(f"\n🔍 Searching: {args.search}")
        results = service.search_hybrid(args.search, n_results=5)
        for i, r in enumerate(results):
            print(f"\n--- Result {i+1} ---")
            print(f"Program: {r['id']}")
            print(f"File: {r['metadata'].get('filename', 'Unknown')}")
            print(f"Keyword Match: {'✅ Yes' if r.get('keyword_match') else '❌ No'}")
            if r.get('match_count', 0) > 0:
                print(f"Match Count: {r.get('match_count', 0)}")
            if r.get('semantic_distance') is not None:
                print(f"Semantic Distance: {r.get('semantic_distance'):.4f}")
            print(f"Score: {r.get('score', 0):.1f}")
        return
    
    # Clear if requested
    if args.clear:
        print("🗑️  Clearing COBOL collection...")
        service.clear()
    
    # Index
    print(f"\n🚀 Starting COBOL indexing{'(limit: ' + str(args.limit) + ')' if args.limit else ''}...")
    print(f"   This may take a few minutes...\n")
    
    result = service.index_all(limit=args.limit)
    
    print(f"\n✅ Indexing Complete!")
    print(f"   Total files found: {result['total_files']}")
    print(f"   Indexed: {result['indexed']}")
    print(f"   Errors: {result['errors']}")
    print(f"   KB Total: {result['collection_count']}")


if __name__ == "__main__":
    main()