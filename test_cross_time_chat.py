#!/usr/bin/env python3
"""
Quick test script to verify cross-time proposition integration works
"""
import asyncio
import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def test_proposition_search():
    """Test the find_related_propositions_for_chat function"""
    from controller import find_related_propositions_for_chat
    from gum.models import init_db
    
    print("🧪 Testing cross-time proposition search...")
    
    try:
        # Initialize database connection
        engine, session_maker = await init_db("gum.db")
        
        # Create a mock suggestion context
        suggestion_context = {
            "title": "Email Management",
            "description": "Organize your inbox with 2,348 emails",
            "action_items": ["bulk unsubscribe", "create filters", "archive old emails"]
        }
        
        # Create mock recent observations (empty for this test)
        recent_observations = []
        
        # Test the function
        async with session_maker() as session:
            related_props = await find_related_propositions_for_chat(
                session, 
                suggestion_context, 
                recent_observations,
                limit=5
            )
            
            print(f"✅ Function executed successfully!")
            print(f"📊 Found {len(related_props)} related propositions")
            
            for i, (prop, score) in enumerate(related_props, 1):
                print(f"  {i}. {prop.text[:50]}... (confidence: {prop.confidence})")
        
        await engine.dispose()
        print("🎉 Test completed successfully!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_proposition_search())
