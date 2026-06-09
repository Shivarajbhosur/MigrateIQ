"""
Script to run PR ingestion into Knowledge Base.

Usage:
    python scripts/ingest_prs.py              # Ingest ALL PRs
    python scripts/ingest_prs.py --limit 50   # Ingest 50 PRs
    python scripts/ingest_prs.py --stats      # Show stats only
"""

import sys
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.ingestion_service import get_ingestion_service
from services.knowledge_base_service import get_kb_service


def main():
    parser = argparse.ArgumentParser(description="Ingest PRs into Knowledge Base")
    parser.add_argument("--limit", type=int, default=None, help="Max PRs to ingest (default: ALL)")
    parser.add_argument("--clear", action="store_true", help="Clear KB before ingestion")
    parser.add_argument("--stats", action="store_true", help="Show KB stats only")
    args = parser.parse_args()
    
    kb = get_kb_service()
    
    # Stats only
    if args.stats:
        stats = kb.get_stats()
        print(f"\n📊 Knowledge Base Stats:")
        print(f"   Total entries: {stats['total_entries']}")
        print(f"   Collection: {stats['collection_name']}")
        print(f"   Path: {stats['db_path']}")
        return
    
    # Clear if requested
    if args.clear:
        print("🗑️  Clearing Knowledge Base...")
        kb.clear()
        print("   Done!")
    
    # Run ingestion
    limit_msg = f"limit: {args.limit}" if args.limit else "ALL PRs"
    print(f"\n🚀 Starting PR ingestion ({limit_msg})...")
    print("   This may take several minutes...\n")
    
    service = get_ingestion_service()
    result = service.ingest_prs(limit=args.limit)
    
    print(f"\n✅ Ingestion Complete!")
    print(f"   Total PRs found: {result.get('total_prs', 0)}")
    print(f"   Ingested: {result.get('ingested', 0)}")
    print(f"   Skipped: {result.get('skipped', 0)}")
    print(f"   Errors: {result.get('errors', 0)}")
    print(f"   KB Total: {result.get('kb_total', 0)}")


if __name__ == "__main__":
    main()