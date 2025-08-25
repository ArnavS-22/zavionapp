"""
Enhanced suggestion engine implementing bundle-aware, utility-scored recommendations.

This module provides the core logic for generating strategic suggestions by:
1. Extracting entities from propositions
2. Bundling facts with related inferences
3. Generating diverse, deduplicated suggestions
4. Scoring suggestions on multiple utility dimensions
"""

import re
import json
import asyncio
import logging
from typing import List, Dict, Any, Tuple, Set, Optional
from datetime import datetime, timezone
from dataclasses import dataclass
from collections import defaultdict, Counter

import numpy as np
from sqlalchemy import select, desc, func
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from gum.models import Proposition

logger = logging.getLogger(__name__)


@dataclass
class PropositonBundle:
    """A bundle containing one high-confidence fact and related inferences."""
    anchor_fact: Proposition
    inferences: List[Proposition]
    shared_entities: Set[str]
    time_proximity_score: float
    
    
@dataclass
class ScoredSuggestion:
    """A suggestion with computed utility scores."""
    title: str
    description: str
    evidence: str
    benefit: float
    false_negative_cost: float
    novelty: float
    decay: float
    priority: float
    tool: str
    action_items: List[str]
    category: str
    priority_explanation: str
    bundle_info: Dict[str, Any]


class EntityExtractor:
    """Extracts entities and keywords from proposition text."""
    
    def __init__(self):
        # Common entity patterns
        self.patterns = {
            'apps': r'\b(?:ChatGPT|Visual Studio Code|Instagram|LinkedIn|Gmail|Zavion|Pitch|Airtable|Google|Chrome|PowerShell|Electron|FastAPI)\b',
            'people': r'\b(?:[A-Z][a-z]+ [A-Z][a-z]+)\b',  # First Last name pattern
            'organizations': r'\b(?:Y Combinator|Dorm Room Fund|Stanford|UC Berkeley|Harvard)\b',
            'tech_terms': r'\b(?:API|endpoint|backend|frontend|JavaScript|Python|React|debugging|port|server|database|JSON|HTTP)\b',
            'time_indicators': r'\b(?:late night|morning|afternoon|evening|weekend|daily|weekly|deadline)\b',
            'actions': r'\b(?:debugging|developing|building|applying|networking|learning|studying|coding|testing|reviewing)\b',
            'emotions': r'\b(?:frustrated|excited|worried|confident|stressed|focused|overwhelmed)\b'
        }
        
    def extract_entities(self, text: str) -> Dict[str, Set[str]]:
        """Extract entities from text using pattern matching."""
        entities = defaultdict(set)
        
        text_lower = text.lower()
        
        for category, pattern in self.patterns.items():
            matches = re.findall(pattern, text, re.IGNORECASE)
            entities[category].update(matches)
            
        # Extract additional keywords (high-frequency meaningful words)
        keywords = self._extract_keywords(text_lower)
        entities['keywords'].update(keywords)
        
        return dict(entities)
    
    def _extract_keywords(self, text: str) -> Set[str]:
        """Extract meaningful keywords from text."""
        # Remove common stop words and focus on nouns/verbs
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'can', 'this', 'that', 'these', 'those'}
        
        words = re.findall(r'\b[a-z]{3,}\b', text)  # 3+ letter words
        keywords = {word for word in words if word not in stop_words}
        
        # Focus on the most relevant keywords (limit to prevent noise)
        word_freq = Counter(keywords)
        return set(dict(word_freq.most_common(10)).keys())


class BundleCreator:
    """Creates bundles of facts + inferences for suggestion generation."""
    
    def __init__(self, entity_extractor: EntityExtractor):
        self.entity_extractor = entity_extractor
        
    async def create_bundles(self, session, max_bundles: int = 15) -> List[PropositonBundle]:
        """Create bundles of high-confidence facts with related inferences."""
        
        # Get high-confidence facts (anchor propositions)
        facts_stmt = (
            select(Proposition)
            .where(Proposition.confidence >= 8)
            .order_by(desc(Proposition.confidence), desc(Proposition.created_at))
            .limit(30)  # Get more facts than bundles to ensure diversity
        )
        facts_result = await session.execute(facts_stmt)
        facts = facts_result.scalars().all()
        
        # Get medium and low confidence inferences
        inferences_stmt = (
            select(Proposition)
            .where(Proposition.confidence.between(3, 7))
            .order_by(desc(Proposition.created_at))
            .limit(200)  # Get large pool of inferences
        )
        inferences_result = await session.execute(inferences_stmt)
        inferences = inferences_result.scalars().all()
        
        logger.info(f"Found {len(facts)} facts and {len(inferences)} inferences for bundling")
        
        # Extract entities for all propositions
        fact_entities = {}
        inference_entities = {}
        
        for fact in facts:
            fact_entities[fact.id] = self.entity_extractor.extract_entities(fact.text + " " + fact.reasoning)
            
        for inference in inferences:
            inference_entities[inference.id] = self.entity_extractor.extract_entities(inference.text + " " + inference.reasoning)
        
        # Create bundles
        bundles = []
        used_facts = set()
        
        for fact in facts:
            if len(bundles) >= max_bundles or fact.id in used_facts:
                continue
                
            # Find related inferences
            related_inferences = self._find_related_inferences(
                fact, fact_entities[fact.id], inferences, inference_entities
            )
            
            if related_inferences:
                # Calculate shared entities and time proximity
                shared_entities = self._calculate_shared_entities(
                    fact_entities[fact.id], [inference_entities[inf.id] for inf in related_inferences]
                )
                time_proximity = self._calculate_time_proximity(fact, related_inferences)
                
                bundle = PropositonBundle(
                    anchor_fact=fact,
                    inferences=related_inferences[:3],  # Limit to 3 inferences
                    shared_entities=shared_entities,
                    time_proximity_score=time_proximity
                )
                bundles.append(bundle)
                used_facts.add(fact.id)
        
        logger.info(f"Created {len(bundles)} proposition bundles")
        return bundles
    
    def _find_related_inferences(self, fact: Proposition, fact_entities: Dict, 
                                inferences: List[Proposition], inference_entities: Dict) -> List[Proposition]:
        """Find inferences related to a fact based on entity overlap and time proximity."""
        
        related = []
        fact_time = datetime.fromisoformat(fact.created_at.replace('Z', '+00:00'))
        
        for inference in inferences:
            # Calculate entity similarity
            entity_similarity = self._calculate_entity_similarity(fact_entities, inference_entities[inference.id])
            
            # Calculate time proximity (closer in time = higher score)
            inference_time = datetime.fromisoformat(inference.created_at.replace('Z', '+00:00'))
            time_diff_hours = abs((fact_time - inference_time).total_seconds()) / 3600
            time_score = max(0, 1 - time_diff_hours / (24 * 7))  # Decay over a week
            
            # Combined relevance score
            relevance = 0.7 * entity_similarity + 0.3 * time_score
            
            if relevance > 0.1:  # Minimum threshold for relatedness
                related.append((inference, relevance))
        
        # Sort by relevance and return top inferences
        related.sort(key=lambda x: x[1], reverse=True)
        return [inf for inf, _ in related[:5]]  # Top 5 related inferences
    
    def _calculate_entity_similarity(self, entities1: Dict, entities2: Dict) -> float:
        """Calculate similarity between two entity dictionaries."""
        
        total_score = 0
        total_weight = 0
        
        # Weight different entity types
        weights = {
            'apps': 3.0,
            'people': 2.5, 
            'organizations': 2.0,
            'tech_terms': 1.5,
            'actions': 1.2,
            'time_indicators': 1.0,
            'keywords': 0.8,
            'emotions': 0.5
        }
        
        for category in set(entities1.keys()) | set(entities2.keys()):
            set1 = entities1.get(category, set())
            set2 = entities2.get(category, set())
            
            if set1 and set2:
                overlap = len(set1 & set2)
                union = len(set1 | set2)
                jaccard = overlap / union if union > 0 else 0
                
                weight = weights.get(category, 1.0)
                total_score += jaccard * weight
                total_weight += weight
        
        return total_score / total_weight if total_weight > 0 else 0
    
    def _calculate_shared_entities(self, fact_entities: Dict, inference_entities_list: List[Dict]) -> Set[str]:
        """Calculate entities shared across fact and inferences."""
        
        shared = set()
        
        for category in fact_entities:
            fact_set = fact_entities[category]
            
            for inference_entities in inference_entities_list:
                inference_set = inference_entities.get(category, set())
                shared.update(fact_set & inference_set)
        
        return shared
    
    def _calculate_time_proximity(self, fact: Proposition, inferences: List[Proposition]) -> float:
        """Calculate average time proximity between fact and inferences."""
        
        if not inferences:
            return 0
            
        fact_time = datetime.fromisoformat(fact.created_at.replace('Z', '+00:00'))
        proximities = []
        
        for inference in inferences:
            inference_time = datetime.fromisoformat(inference.created_at.replace('Z', '+00:00'))
            time_diff_hours = abs((fact_time - inference_time).total_seconds()) / 3600
            proximity = max(0, 1 - time_diff_hours / (24 * 7))  # Decay over a week
            proximities.append(proximity)
        
        return sum(proximities) / len(proximities)


class SuggestionDeduplicator:
    """Handles deduplication and diversity selection using embeddings and MMR."""
    
    def __init__(self):
        self.vectorizer = TfidfVectorizer(
            max_features=1000, 
            stop_words='english',
            ngram_range=(1, 2)
        )
    
    def deduplicate_suggestions(self, suggestions: List[ScoredSuggestion], 
                              similarity_threshold: float = 0.92) -> List[ScoredSuggestion]:
        """Remove near-duplicate suggestions using cosine similarity."""
        
        if len(suggestions) <= 1:
            return suggestions
        
        # Create text representations for similarity comparison
        texts = [f"{sugg.title} {sugg.description}" for sugg in suggestions]
        
        try:
            # Calculate TF-IDF embeddings
            tfidf_matrix = self.vectorizer.fit_transform(texts)
            
            # Calculate pairwise similarities
            similarities = cosine_similarity(tfidf_matrix)
            
            # Find duplicates
            to_remove = set()
            for i in range(len(suggestions)):
                if i in to_remove:
                    continue
                for j in range(i + 1, len(suggestions)):
                    if j in to_remove:
                        continue
                    if similarities[i][j] > similarity_threshold:
                        # Keep the higher priority suggestion
                        if suggestions[i].priority >= suggestions[j].priority:
                            to_remove.add(j)
                        else:
                            to_remove.add(i)
                            break
            
            # Return deduplicated suggestions
            deduplicated = [sugg for i, sugg in enumerate(suggestions) if i not in to_remove]
            logger.info(f"Deduplicated {len(suggestions)} -> {len(deduplicated)} suggestions")
            return deduplicated
            
        except Exception as e:
            logger.warning(f"Deduplication failed: {e}, returning original suggestions")
            return suggestions
    
    def select_diverse_suggestions(self, suggestions: List[ScoredSuggestion], 
                                 max_suggestions: int = 8,
                                 max_per_category: int = 3) -> List[ScoredSuggestion]:
        """Select diverse suggestions using Modified Maximal Marginal Relevance (MMR)."""
        
        if len(suggestions) <= max_suggestions:
            return suggestions
        
        # Apply category limits first
        category_counts = defaultdict(int)
        filtered_by_category = []
        
        # Sort by priority to prefer high-priority suggestions in each category
        suggestions_by_priority = sorted(suggestions, key=lambda x: x.priority, reverse=True)
        
        for sugg in suggestions_by_priority:
            if category_counts[sugg.category] < max_per_category:
                filtered_by_category.append(sugg)
                category_counts[sugg.category] += 1
        
        if len(filtered_by_category) <= max_suggestions:
            return filtered_by_category
        
        # Apply MMR for final selection
        return self._apply_mmr(filtered_by_category, max_suggestions)
    
    def _apply_mmr(self, suggestions: List[ScoredSuggestion], k: int, lambda_param: float = 0.7) -> List[ScoredSuggestion]:
        """Apply Modified Maximal Marginal Relevance for diversity."""
        
        try:
            # Create text representations
            texts = [f"{sugg.title} {sugg.description}" for sugg in suggestions]
            tfidf_matrix = self.vectorizer.fit_transform(texts)
            
            selected = []
            remaining = list(range(len(suggestions)))
            
            # Select first suggestion (highest priority)
            if remaining:
                first_idx = max(remaining, key=lambda i: suggestions[i].priority)
                selected.append(first_idx)
                remaining.remove(first_idx)
            
            # Select remaining suggestions using MMR
            while len(selected) < k and remaining:
                best_score = -float('inf')
                best_idx = None
                
                for i in remaining:
                    # Relevance score (priority)
                    relevance = suggestions[i].priority
                    
                    # Diversity score (minimum similarity to selected)
                    if selected:
                        similarities = [cosine_similarity(tfidf_matrix[i], tfidf_matrix[j])[0][0] for j in selected]
                        max_similarity = max(similarities)
                    else:
                        max_similarity = 0
                    
                    # MMR score
                    mmr_score = lambda_param * relevance - (1 - lambda_param) * max_similarity
                    
                    if mmr_score > best_score:
                        best_score = mmr_score
                        best_idx = i
                
                if best_idx is not None:
                    selected.append(best_idx)
                    remaining.remove(best_idx)
                else:
                    break
            
            return [suggestions[i] for i in selected]
            
        except Exception as e:
            logger.warning(f"MMR selection failed: {e}, using priority-based selection")
            return sorted(suggestions, key=lambda x: x.priority, reverse=True)[:k]


class UtilityScorer:
    """Computes utility scores for suggestions based on multiple dimensions."""
    
    def score_suggestion(self, suggestion_data: Dict[str, Any], bundle: PropositonBundle) -> ScoredSuggestion:
        """Score a suggestion on benefit, false_negative_cost, novelty, and decay."""
        
        # Extract suggestion components
        title = suggestion_data.get('title', '')
        description = suggestion_data.get('description', '')
        category = suggestion_data.get('category', 'strategic')
        action_items = suggestion_data.get('action_items', [])
        evidence = suggestion_data.get('evidence', '')
        
        # Calculate utility scores
        benefit = self._calculate_benefit(suggestion_data, bundle)
        false_negative_cost = self._calculate_false_negative_cost(suggestion_data, bundle)
        novelty = self._calculate_novelty(suggestion_data, bundle)
        decay = self._calculate_decay(suggestion_data, bundle)
        
        # Calculate overall priority
        priority = (0.45 * benefit + 0.3 * false_negative_cost + 
                   0.15 * novelty + 0.1 * decay)
        
        # Generate priority explanation
        priority_explanation = self._generate_priority_explanation(
            benefit, false_negative_cost, novelty, decay, priority
        )
        
        return ScoredSuggestion(
            title=title,
            description=description,
            evidence=evidence,
            benefit=benefit,
            false_negative_cost=false_negative_cost,
            novelty=novelty,
            decay=decay,
            priority=priority,
            tool="gum_suggestions",
            action_items=action_items,
            category=category,
            priority_explanation=priority_explanation,
            bundle_info={
                'anchor_fact_confidence': bundle.anchor_fact.confidence,
                'num_inferences': len(bundle.inferences),
                'shared_entities': list(bundle.shared_entities),
                'time_proximity': bundle.time_proximity_score
            }
        )
    
    def _calculate_benefit(self, suggestion: Dict[str, Any], bundle: PropositonBundle) -> float:
        """Calculate potential benefit score (0-1)."""
        
        # Base benefit from anchor fact confidence
        base_benefit = bundle.anchor_fact.confidence / 10.0
        
        # Boost based on category importance
        category_boosts = {
            'strategic': 0.9,
            'optimization': 0.8,
            'workflow': 0.7,
            'learning': 0.6,
            'completion': 0.5
        }
        category = suggestion.get('category', 'strategic')
        category_boost = category_boosts.get(category, 0.7)
        
        # Boost based on action complexity (more actions = higher potential benefit)
        action_items = suggestion.get('action_items', [])
        action_boost = min(1.0, len(action_items) / 3.0)  # Normalize to 1.0 at 3 actions
        
        # Entity diversity boost
        entity_boost = min(1.0, len(bundle.shared_entities) / 5.0)  # Normalize to 1.0 at 5 entities
        
        return min(1.0, base_benefit * category_boost * (0.7 + 0.2 * action_boost + 0.1 * entity_boost))
    
    def _calculate_false_negative_cost(self, suggestion: Dict[str, Any], bundle: PropositonBundle) -> float:
        """Calculate cost of missing this suggestion (0-1)."""
        
        # Higher cost for time-sensitive suggestions
        urgency = suggestion.get('urgency', 'this_week')
        urgency_costs = {
            'now': 0.9,
            'today': 0.7,
            'this_week': 0.4
        }
        urgency_cost = urgency_costs.get(urgency, 0.4)
        
        # Higher cost for strategic categories
        category = suggestion.get('category', 'strategic')
        category_costs = {
            'strategic': 0.8,
            'optimization': 0.6,
            'completion': 0.7,
            'workflow': 0.5,
            'learning': 0.3
        }
        category_cost = category_costs.get(category, 0.5)
        
        # Higher cost if multiple inferences point to the same need
        inference_support = min(1.0, len(bundle.inferences) / 3.0)
        
        return min(1.0, urgency_cost * category_cost * (0.6 + 0.4 * inference_support))
    
    def _calculate_novelty(self, suggestion: Dict[str, Any], bundle: PropositonBundle) -> float:
        """Calculate novelty/non-obviousness score (0-1)."""
        
        # Lower confidence inferences indicate more novel insights
        inference_confidences = [inf.confidence for inf in bundle.inferences]
        avg_inference_confidence = sum(inference_confidences) / len(inference_confidences) if inference_confidences else 8
        
        # Lower average confidence = higher novelty
        novelty_from_inferences = max(0, 1 - avg_inference_confidence / 10.0)
        
        # Cross-domain connections increase novelty
        entity_diversity = len(bundle.shared_entities)
        cross_domain_bonus = min(0.3, entity_diversity / 10.0)
        
        # Time span increases novelty (connecting distant patterns)
        time_novelty = bundle.time_proximity_score * 0.2  # Paradoxically, more time span = more novel
        
        return min(1.0, novelty_from_inferences + cross_domain_bonus + time_novelty)
    
    def _calculate_decay(self, suggestion: Dict[str, Any], bundle: PropositonBundle) -> float:
        """Calculate how long the suggestion remains relevant (0-1)."""
        
        # Strategic suggestions have longer relevance
        category = suggestion.get('category', 'strategic')
        category_durability = {
            'strategic': 0.9,
            'optimization': 0.7,
            'learning': 0.8,
            'workflow': 0.6,
            'completion': 0.3  # Completion tasks decay quickly
        }
        
        base_durability = category_durability.get(category, 0.6)
        
        # Higher confidence anchor facts provide more durable insights
        confidence_factor = bundle.anchor_fact.confidence / 10.0
        
        # Broader entity coverage suggests more durable insights
        entity_factor = min(1.0, len(bundle.shared_entities) / 3.0)
        
        return min(1.0, base_durability * confidence_factor * (0.7 + 0.3 * entity_factor))
    
    def _generate_priority_explanation(self, benefit: float, false_negative: float, 
                                     novelty: float, decay: float, priority: float) -> str:
        """Generate human-readable explanation of priority score."""
        
        components = []
        
        if benefit > 0.7:
            components.append("high potential benefit")
        elif benefit > 0.4:
            components.append("moderate benefit")
        
        if false_negative > 0.6:
            components.append("significant cost if missed")
        
        if novelty > 0.6:
            components.append("novel cross-pattern insight")
        elif novelty > 0.3:
            components.append("some non-obvious connections")
        
        if decay > 0.7:
            components.append("long-term relevance")
        
        explanation = f"Priority {priority:.2f}: " + ", ".join(components) if components else f"Priority {priority:.2f}: standard suggestion"
        
        return explanation


class EnhancedSuggestionEngine:
    """Main orchestrator for the enhanced suggestion system."""
    
    def __init__(self):
        self.entity_extractor = EntityExtractor()
        self.bundle_creator = BundleCreator(self.entity_extractor)
        self.deduplicator = SuggestionDeduplicator()
        self.scorer = UtilityScorer()
    
    async def generate_suggestions(self, session, ai_client, user_name: str = "User", 
                                 max_suggestions: int = 8) -> List[Dict[str, Any]]:
        """Generate enhanced suggestions using the bundle-aware system."""
        
        try:
            # Step 1: Create proposition bundles
            bundles = await self.bundle_creator.create_bundles(session, max_bundles=15)
            
            if not bundles:
                logger.warning("No proposition bundles created")
                return []
            
            # Step 2: Generate suggestions from bundles using LLM
            raw_suggestions = []
            for bundle in bundles:
                suggestion = await self._generate_suggestion_from_bundle(
                    bundle, ai_client, user_name
                )
                if suggestion:
                    raw_suggestions.append((suggestion, bundle))
            
            logger.info(f"Generated {len(raw_suggestions)} raw suggestions from {len(bundles)} bundles")
            
            # Step 3: Score suggestions
            scored_suggestions = []
            for suggestion_data, bundle in raw_suggestions:
                try:
                    scored_suggestion = self.scorer.score_suggestion(suggestion_data, bundle)
                    scored_suggestions.append(scored_suggestion)
                except Exception as e:
                    logger.warning(f"Failed to score suggestion: {e}")
                    continue
            
            # Step 4: Deduplicate
            deduplicated = self.deduplicator.deduplicate_suggestions(scored_suggestions)
            
            # Step 5: Select diverse final set
            final_suggestions = self.deduplicator.select_diverse_suggestions(
                deduplicated, max_suggestions=max_suggestions
            )
            
            # Step 6: Convert to API format
            api_suggestions = []
            for scored_sugg in final_suggestions:
                api_suggestions.append({
                    'title': scored_sugg.title,
                    'description': scored_sugg.description,
                    'urgency': self._infer_urgency_from_priority(scored_sugg.priority),
                    'category': scored_sugg.category,
                    'evidence': scored_sugg.evidence,
                    'action_items': scored_sugg.action_items,
                    'confidence': int(scored_sugg.priority * 10),  # Convert to 1-10 scale
                    'scores': {
                        'benefit': round(scored_sugg.benefit, 2),
                        'false_negative_cost': round(scored_sugg.false_negative_cost, 2),
                        'novelty': round(scored_sugg.novelty, 2),
                        'decay': round(scored_sugg.decay, 2),
                        'priority': round(scored_sugg.priority, 2)
                    },
                    'priority_explanation': scored_sugg.priority_explanation,
                    'bundle_info': scored_sugg.bundle_info
                })
            
            logger.info(f"Returning {len(api_suggestions)} final enhanced suggestions")
            
            # Save suggestions to database so frontend can display them
            try:
                # Save suggestions directly to database (same pattern as controller)
                try:
                    # Get database session
                    from gum.gum import gum
                    gum_inst = gum(user_name=user_name)
                    await gum_inst.connect_db()
                    
                    async with gum_inst._session() as session:
                        from gum.models import Suggestion
                        
                        # Save each suggestion directly to database
                        suggestions_saved = 0
                        for suggestion_data in api_suggestions:
                            suggestion = Suggestion(
                                title=suggestion_data.get("title", "Untitled")[:200],
                                description=suggestion_data.get("description", "")[:1000],
                                category=suggestion_data.get("category", "general")[:100],
                                rationale=suggestion_data.get("evidence", "")[:500],
                                expected_utility=suggestion_data.get("confidence", 5) / 10.0,
                                probability_useful=0.7,
                                trigger_proposition_id=None,
                                batch_id=f"suggestion_engine_{int(time.time())}",
                                delivered=False
                            )
                            session.add(suggestion)
                            suggestions_saved += 1
                        
                        await session.commit()
                        logger.info(f"💾 SAVED {suggestions_saved} SUGGESTIONS DIRECTLY TO DATABASE")
                        
                except Exception as save_error:
                    logger.error(f"❌ FAILED TO SAVE SUGGESTIONS TO DATABASE: {save_error}")
            except Exception as save_error:
                logger.error(f"❌ FAILED TO SAVE SUGGESTIONS TO DATABASE: {save_error}")
            
            return api_suggestions
            
        except Exception as e:
            logger.error(f"Enhanced suggestion generation failed: {e}")
            return []
    
    async def _generate_suggestion_from_bundle(self, bundle: PropositonBundle, 
                                             ai_client, user_name: str) -> Optional[Dict[str, Any]]:
        """Generate a single suggestion from a proposition bundle using LLM."""
        
        try:
            # Create bundle-aware prompt
            from gum.prompts.gum import ENHANCED_SUGGESTIONS_PROMPT
            
            # Prepare bundle context
            bundle_context = self._prepare_bundle_context(bundle)
            
            prompt = (
                ENHANCED_SUGGESTIONS_PROMPT
                .replace("{user_name}", user_name)
                .replace("{bundle_context}", bundle_context)
            )
            
            # Generate suggestion
            response = await ai_client.complete_text(
                prompt=prompt,
                model="gpt-4o",
                max_tokens=800,
                temperature=0.1  # Lower temperature for more consistent output
            )
            
            content = response.get('choices', [{}])[0].get('message', {}).get('content', '')
            
            if not content:
                return None
            
            # Clean and parse JSON
            if '```json' in content:
                content = content.split('```json')[1].split('```')[0].strip()
            
            suggestion_data = json.loads(content)
            return suggestion_data
            
        except Exception as e:
            logger.warning(f"Failed to generate suggestion from bundle: {e}")
            return None
    
    def _prepare_bundle_context(self, bundle: PropositonBundle) -> str:
        """Prepare formatted context from a proposition bundle."""
        
        context = f"# Strategic Analysis Bundle\n\n"
        
        # Anchor fact
        context += f"## Core Verified Insight (Confidence: {bundle.anchor_fact.confidence}/10)\n"
        context += f"**Fact:** {bundle.anchor_fact.text}\n"
        context += f"**Evidence:** {bundle.anchor_fact.reasoning[:200]}...\n"
        context += f"**Timestamp:** {bundle.anchor_fact.created_at}\n\n"
        
        # Supporting inferences
        context += f"## Supporting Behavioral Inferences\n"
        for i, inference in enumerate(bundle.inferences, 1):
            context += f"**Inference {i}** (Confidence: {inference.confidence}/10):\n"
            context += f"- {inference.text}\n"
            context += f"- Evidence: {inference.reasoning[:150]}...\n"
            context += f"- Date: {inference.created_at}\n\n"
        
        # Pattern connections
        context += f"## Pattern Connections\n"
        context += f"**Shared Elements:** {', '.join(list(bundle.shared_entities)[:10])}\n"
        context += f"**Time Proximity Score:** {bundle.time_proximity_score:.2f}\n"
        context += f"**Cross-Time Intelligence Opportunity:** Connect the verified fact with the behavioral inferences to discover strategic opportunities.\n\n"
        
        return context
    
    def _infer_urgency_from_priority(self, priority: float) -> str:
        """Convert priority score to urgency category."""
        if priority >= 0.8:
            return "now"
        elif priority >= 0.6:
            return "today"
        else:
            return "this_week"
