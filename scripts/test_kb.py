"""
Test KB search functionality.
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   test_kb.py = Testing/Debugging Tool for Knowledge Base                       │
│                                                                                 │
│   It's NOT used in production.                                                 │
│   It's for me to verify KB is working correctly.                              │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

Usage:
    python scripts/test_kb.py --collection codebase --query "C-UPDATERA-TABELL" --mode hybrid
    python scripts/test_kb.py --collection pr_fixes --query "HPPL" --mode keyword
    python scripts/test_kb.py --collection cobol --query "HPPL494P" --mode hybrid
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.knowledge_base_service import get_kb_service
from services.codebase_service import get_codebase_service
from services.cobol_service import get_cobol_service


def main():
    parser = argparse.ArgumentParser(description="Test KB search")
    parser.add_argument("--collection", type=str, default="codebase", 
                        choices=["pr_fixes", "codebase", "cobol"], help="Collection to search")
    parser.add_argument("--query", type=str, required=True, help="Search query")
    parser.add_argument("--limit", type=int, default=5, help="Number of results")
    parser.add_argument("--mode", type=str, default="hybrid",
                        choices=["keyword", "semantic", "hybrid"], 
                        help="Search mode: keyword (exact), semantic (meaning), hybrid (both)")
    args = parser.parse_args()
    
    print(f"\n🔍 Searching '{args.collection}' for: {args.query}")
    print(f"   Mode: {args.mode.upper()}\n")
    
    # Get appropriate service
    if args.collection == "pr_fixes":
        service = get_kb_service()
    elif args.collection == "cobol":
        service = get_cobol_service()
    else:
        service = get_codebase_service()
    
    # Execute search based on mode
    if args.mode == "keyword":
        results = service.search_keyword(args.query, n_results=args.limit)
    elif args.mode == "semantic":
        if args.collection == "pr_fixes":
            results = service.search_similar(args.query, n_results=args.limit)
        else:
            results = service.search(args.query, n_results=args.limit)
    else:  # hybrid
        results = service.search_hybrid(args.query, n_results=args.limit)
    
    if not results:
        print("❌ No results found")
        return
    
    print(f"✅ Found {len(results)} results:\n")
    
    for i, r in enumerate(results):
        print(f"--- Result {i+1} ---")
        meta = r.get('metadata', {})
        
        if args.collection == "pr_fixes":
            print(f"PR ID: {meta.get('pr_id', 'N/A')}")
            print(f"Baseline: {meta.get('baseline', 'N/A')}")
            print(f"Ticket: {meta.get('ticket_id', 'N/A')}")
            print(f"Files: {meta.get('files_changed', 'N/A')}")
        elif args.collection == "cobol":
            print(f"Program: {r.get('id', 'N/A')}")
            print(f"File: {meta.get('filename', 'N/A')}")
            print(f"Size: {meta.get('size_bytes', 0)} bytes")
        else:
            print(f"File: {meta.get('relative_path', 'N/A')}")
            print(f"Size: {meta.get('size_bytes', 0)} bytes")
        
        # Show search-specific info
        if args.mode == "keyword":
            print(f"Match Count: {r.get('match_count', 0)}")
        elif args.mode == "semantic":
            print(f"Distance: {r.get('distance', 0):.4f}")
        else:  # hybrid
            print(f"Keyword Match: {'✅ Yes' if r.get('keyword_match') else '❌ No'}")
            if r.get('match_count', 0) > 0:
                print(f"Match Count: {r.get('match_count', 0)}")
            if r.get('semantic_distance') is not None:
                print(f"Semantic Distance: {r.get('semantic_distance'):.4f}")
            print(f"Score: {r.get('score', 0):.1f}")
        
        print()


if __name__ == "__main__":
    main()