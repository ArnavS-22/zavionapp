#!/usr/bin/env python3
import sqlite3
import os

# Check the real GUM database
db_path = os.path.expanduser("~/.cache/gum/gum.db")

if not os.path.exists(db_path):
    print(f"❌ Database not found: {db_path}")
    exit(1)

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get all tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print(f"📋 Tables in database: {[t[0] for t in tables]}")
    
    # Check if suggestions table exists
    if ('suggestions',) in tables:
        cursor.execute("SELECT COUNT(*) FROM suggestions")
        count = cursor.fetchone()[0]
        print(f"✅ Suggestions table exists with {count} suggestions")
        
        if count > 0:
            cursor.execute("SELECT id, title, created_at FROM suggestions ORDER BY created_at DESC LIMIT 5")
            suggestions = cursor.fetchall()
            print("📝 Recent suggestions:")
            for s in suggestions:
                print(f"   ID {s[0]}: {s[1][:50]}... ({s[2]})")
    else:
        print("❌ Suggestions table does NOT exist")
    
    # Check propositions (should have 393)
    cursor.execute("SELECT COUNT(*) FROM propositions")
    prop_count = cursor.fetchone()[0]
    print(f"📊 Propositions: {prop_count}")
    
    # Check for high-confidence propositions (should trigger Gumbo)
    cursor.execute("SELECT COUNT(*) FROM propositions WHERE confidence >= 8")
    high_conf_count = cursor.fetchone()[0]
    print(f"🎯 High-confidence propositions (≥8): {high_conf_count}")
    
    if high_conf_count > 0:
        cursor.execute("SELECT id, text, confidence FROM propositions WHERE confidence >= 8 ORDER BY confidence DESC LIMIT 3")
        high_conf_props = cursor.fetchall()
        print("🔥 High-confidence propositions that should trigger Gumbo:")
        for p in high_conf_props:
            print(f"   ID {p[0]}: {p[1][:50]}... (confidence: {p[2]})")
    
    conn.close()
    
except Exception as e:
    print(f"❌ Error: {e}")
