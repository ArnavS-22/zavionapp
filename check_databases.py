#!/usr/bin/env python3
import sqlite3
import os

# Check local database (controller uses this)
local_db = "./gum.db"
cache_db = r"C:\Users\arnav\.cache\gum\gum.db"

print("=== DATABASE ANALYSIS ===")

for db_path, db_name in [(local_db, "Local gum.db (controller)"), (cache_db, "Cache gum.db (CLI)")]:
    print(f"\n{db_name}:")
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Get all tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [t[0] for t in cursor.fetchall()]
            print(f"  Tables: {tables}")
            
            # Check propositions count
            if 'propositions' in tables:
                cursor.execute("SELECT COUNT(*) FROM propositions")
                prop_count = cursor.fetchone()[0]
                print(f"  Propositions: {prop_count}")
                
                # Check high confidence propositions
                cursor.execute("SELECT COUNT(*) FROM propositions WHERE confidence >= 8")
                high_conf = cursor.fetchone()[0]
                print(f"  High confidence (>=8): {high_conf}")
            
            # Check suggestions count
            if 'suggestions' in tables:
                cursor.execute("SELECT COUNT(*) FROM suggestions")
                sugg_count = cursor.fetchone()[0]
                print(f"  Suggestions: {sugg_count}")
                
                if sugg_count > 0:
                    cursor.execute("SELECT title, created_at, delivered FROM suggestions ORDER BY created_at DESC LIMIT 3")
                    recent = cursor.fetchall()
                    print(f"  Recent suggestions:")
                    for title, created, delivered in recent:
                        print(f"    - '{title[:50]}...' (delivered: {delivered})")
            else:
                print(f"  No 'suggestions' table found!")
            
            conn.close()
        except Exception as e:
            print(f"  Error: {e}")
    else:
        print(f"  Database not found!")

print("\n=== END ANALYSIS ===")
