import re
import ast
import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class LLMUsageAnalysis:
    """Analysis result for LLM usage in generated API code."""
    uses_llm: bool
    ai_models_detected: List[str]
    primary_model: Optional[str]
    estimated_tokens_per_call: int
    complexity_rating: str
    api_calls_detected: List[str]
    confidence_score: float
    analysis_details: Dict[str, Any]

class APICodeAnalyzer:
    """Service to analyze generated API code and detect LLM usage patterns."""
    
    def __init__(self):
        # Model detection patterns
        self.MODEL_PATTERNS = {
            # OpenAI models
            r'model\s*=\s*[\'\"](gpt-4o-mini)[\'"]': 'gpt-4o-mini',
            r'model\s*=\s*[\'\"](gpt-4o)[\'"]': 'gpt-4o',
            r'model\s*=\s*[\'\"](gpt-4-turbo)[\'"]': 'gpt-4-turbo',
            r'model\s*=\s*[\'\"](gpt-4)[\'"]': 'gpt-4',
            r'model\s*=\s*[\'\"](gpt-3\.5-turbo)[\'"]': 'gpt-3.5-turbo',
            r'model\s*=\s*[\'\"](gpt-5[^\'\"]*)[\'"]': 'gpt-5',
            
            # Claude models
            r'model\s*=\s*[\'\"](claude-3-haiku[^\'\"]*)[\'"]': 'claude-3-haiku',
            r'model\s*=\s*[\'\"](claude-3-sonnet[^\'\"]*)[\'"]': 'claude-3-sonnet',
            r'model\s*=\s*[\'\"](claude-3-opus[^\'\"]*)[\'"]': 'claude-3-opus',
            r'model\s*=\s*[\'\"](claude-4[^\'\"]*)[\'"]': 'claude-4',
            
            # Generic patterns
            r'[\'\"](gpt-[^\'\"]+)[\'"]': 'gpt-detected',
            r'[\'\"](claude-[^\'\"]+)[\'"]': 'claude-detected',
        }
        
        # LLM service detection patterns
        self.LLM_SERVICE_PATTERNS = [
            r'from\s+openai\s+import',
            r'import\s+openai',
            r'OpenAI\s*\(',
            r'client\.chat\.completions\.create',
            r'openai\.ChatCompletion',
            r'anthropic\.Anthropic',
            r'from\s+anthropic\s+import',
            r'import\s+anthropic',
            r'messages\.create',
        ]
        
        # Token estimation patterns
        self.TOKEN_ESTIMATION_PATTERNS = {
            'max_tokens': r'max_tokens\s*=\s*(\d+)',
            'temperature': r'temperature\s*=\s*([\d\.]+)',
            'prompt_length_indicators': [
                r'len\([^)]*\)',
                r'[:]\d+\]',  # Text slicing
                r'\.split\(',
                r'\.strip\(',
            ]
        }
        
        logger.info("APICodeAnalyzer initialized")
    
    async def analyze_api_code(self, code: str, original_prompt: str = "") -> LLMUsageAnalysis:
        """
        Analyze generated API code to detect LLM usage and estimate costs.
        
        Args:
            code: The generated API code to analyze
            original_prompt: The original user prompt (for context)
            
        Returns:
            LLMUsageAnalysis with detailed analysis results
        """
        logger.info("Starting API code analysis for LLM usage detection")
        
        try:
            # Step 1: Detect LLM service usage
            uses_llm = self._detect_llm_usage(code)
            
            # Step 2: Extract AI models
            ai_models_detected = self._extract_ai_models(code)
            
            # Step 3: Determine primary model
            primary_model = self._determine_primary_model(ai_models_detected, code)
            
            # Step 4: Estimate tokens per call
            estimated_tokens = self._estimate_tokens_per_call(code, primary_model)
            
            # Step 5: Determine complexity
            complexity_rating = self._analyze_complexity(code, original_prompt)
            
            # Step 6: Detect API calls
            api_calls_detected = self._detect_api_calls(code)
            
            # Step 7: Calculate confidence score
            confidence_score = self._calculate_confidence_score(
                uses_llm, ai_models_detected, api_calls_detected, code
            )
            
            # Step 8: Build analysis details
            analysis_details = self._build_analysis_details(
                code, original_prompt, ai_models_detected, api_calls_detected
            )
            
            result = LLMUsageAnalysis(
                uses_llm=uses_llm,
                ai_models_detected=ai_models_detected,
                primary_model=primary_model,
                estimated_tokens_per_call=estimated_tokens,
                complexity_rating=complexity_rating,
                api_calls_detected=api_calls_detected,
                confidence_score=confidence_score,
                analysis_details=analysis_details
            )
            
            logger.info(f"Analysis complete: uses_llm={uses_llm}, primary_model={primary_model}, "
                       f"estimated_tokens={estimated_tokens}, confidence={confidence_score:.2f}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error analyzing API code: {str(e)}")
            # Return safe defaults
            return LLMUsageAnalysis(
                uses_llm=False,
                ai_models_detected=[],
                primary_model=None,
                estimated_tokens_per_call=0,
                complexity_rating='simple',
                api_calls_detected=[],
                confidence_score=0.0,
                analysis_details={'error': str(e)}
            )
    
    def _detect_llm_usage(self, code: str) -> bool:
        """Detect if the code uses any LLM services."""
        for pattern in self.LLM_SERVICE_PATTERNS:
            if re.search(pattern, code, re.IGNORECASE):
                logger.debug(f"LLM usage detected with pattern: {pattern}")
                return True
        return False
    
    def _extract_ai_models(self, code: str) -> List[str]:
        """Extract AI model names from the code."""
        models_found = []
        
        for pattern, model_name in self.MODEL_PATTERNS.items():
            matches = re.findall(pattern, code, re.IGNORECASE)
            for match in matches:
                if isinstance(match, str):
                    models_found.append(match)
                elif model_name != 'gpt-detected' and model_name != 'claude-detected':
                    models_found.append(model_name)
        
        # Remove duplicates while preserving order
        unique_models = []
        for model in models_found:
            if model not in unique_models:
                unique_models.append(model)
        
        logger.debug(f"AI models detected: {unique_models}")
        return unique_models
    
    def _determine_primary_model(self, models: List[str], code: str) -> Optional[str]:
        """Determine the primary AI model used in the code."""
        if not models:
            return None
        
        # If only one model, that's the primary
        if len(models) == 1:
            return models[0]
        
        # Priority order for multiple models (most commonly used first)
        priority_order = [
            'gpt-4o-mini', 'gpt-4o', 'gpt-4-turbo', 'gpt-4', 'gpt-3.5-turbo',
            'claude-3-haiku', 'claude-3-sonnet', 'claude-3-opus', 'claude-4'
        ]
        
        for preferred_model in priority_order:
            if preferred_model in models:
                return preferred_model
        
        # Return the first model if no priority match
        return models[0]
    
    def _estimate_tokens_per_call(self, code: str, primary_model: Optional[str]) -> int:
        """Estimate tokens per API call based on code analysis."""
        
        # If no AI model detected, return 0 tokens (free processing)
        if not primary_model:
            logger.debug("No AI model detected - returning 0 tokens (free processing)")
            return 0
        
        base_tokens = 100  # Minimum baseline for LLM APIs
        
        # Extract max_tokens if specified
        max_tokens_match = re.search(self.TOKEN_ESTIMATION_PATTERNS['max_tokens'], code)
        if max_tokens_match:
            specified_max_tokens = int(max_tokens_match.group(1))
            base_tokens = max(base_tokens, specified_max_tokens)
        
        # Analyze prompt complexity indicators
        complexity_multiplier = 1.0
        
        # Check for text processing indicators
        if re.search(r'text\[:?\d*\]', code):  # Text slicing
            complexity_multiplier += 0.3
        
        if re.search(r'\.split\(|\.join\(|\.replace\(', code):  # Text manipulation
            complexity_multiplier += 0.2
        
        if re.search(r'json\.loads|json\.dumps', code):  # JSON processing
            complexity_multiplier += 0.2
        
        if re.search(r'for\s+\w+\s+in|while\s+', code):  # Loops
            complexity_multiplier += 0.4
        
        # Model-specific adjustments
        model_multipliers = {
            'gpt-4o-mini': 1.0,
            'gpt-4o': 1.5,
            'gpt-4': 1.8,
            'gpt-4-turbo': 1.3,
            'gpt-3.5-turbo': 0.8,
            'claude-3-haiku': 0.9,
            'claude-3-sonnet': 1.4,
            'claude-3-opus': 2.0,
            'claude-4': 2.2,
        }
        
        if primary_model and primary_model in model_multipliers:
            complexity_multiplier *= model_multipliers[primary_model]
        
        estimated_tokens = int(base_tokens * complexity_multiplier)
        
        # Reasonable bounds
        estimated_tokens = max(50, min(estimated_tokens, 10000))
        
        logger.debug(f"Estimated tokens per call: {estimated_tokens} (base: {base_tokens}, multiplier: {complexity_multiplier:.2f})")
        return estimated_tokens
    
    def _analyze_complexity(self, code: str, original_prompt: str) -> str:
        """Analyze code complexity for pricing purposes."""
        complexity_score = 0
        
        # Code length factor
        if len(code) > 3000:
            complexity_score += 2
        elif len(code) > 1500:
            complexity_score += 1
        
        # Structural complexity
        if re.search(r'class\s+\w+', code):
            complexity_score += 2
        
        if re.search(r'async\s+def|await\s+', code):
            complexity_score += 1
        
        if re.search(r'try:|except:|finally:', code):
            complexity_score += 1
        
        # AI-specific complexity
        if re.search(r'messages\s*=|system.*content|user.*content', code):
            complexity_score += 1
        
        if re.search(r'temperature|max_tokens|top_p', code):
            complexity_score += 1
        
        # Prompt complexity
        if original_prompt:
            if len(original_prompt) > 200:
                complexity_score += 1
            if any(keyword in original_prompt.lower() for keyword in 
                   ['analyze', 'extract', 'classify', 'summarize', 'generate']):
                complexity_score += 1
        
        # Determine complexity rating
        if complexity_score >= 5:
            return 'complex'
        elif complexity_score >= 3:
            return 'medium'
        else:
            return 'simple'
    
    def _detect_api_calls(self, code: str) -> List[str]:
        """Detect API call patterns in the code."""
        api_calls = []
        
        patterns = [
            r'\.chat\.completions\.create',
            r'\.messages\.create',
            r'\.completions\.create',
            r'requests\.get|requests\.post',
            r'aiohttp\.ClientSession',
            r'httpx\.AsyncClient',
        ]
        
        for pattern in patterns:
            if re.search(pattern, code):
                api_calls.append(pattern.replace('\\', '').replace('.', '_'))
        
        return api_calls
    
    def _calculate_confidence_score(self, uses_llm: bool, models: List[str], 
                                   api_calls: List[str], code: str) -> float:
        """Calculate confidence score for the analysis."""
        confidence = 0.0
        
        if uses_llm:
            confidence += 0.4
        
        if models:
            confidence += 0.3 * min(len(models), 2)  # Cap at 2 models
        
        if api_calls:
            confidence += 0.2 * min(len(api_calls), 2)  # Cap at 2 call types
        
        # Code quality indicators
        if re.search(r'async\s+def\s+run', code):
            confidence += 0.1
        
        if re.search(r'return\s+\{.*result.*\}', code):
            confidence += 0.1
        
        return min(confidence, 1.0)
    
    def _build_analysis_details(self, code: str, original_prompt: str, 
                               models: List[str], api_calls: List[str]) -> Dict[str, Any]:
        """Build detailed analysis information."""
        return {
            'code_length': len(code),
            'prompt_length': len(original_prompt),
            'models_found': models,
            'api_calls_found': api_calls,
            'has_async_function': bool(re.search(r'async\s+def\s+run', code)),
            'has_error_handling': bool(re.search(r'try:|except:', code)),
            'has_json_processing': bool(re.search(r'json\.', code)),
            'analysis_timestamp': logger.info.__name__,  # Simple timestamp placeholder
        }

# Global instance
api_code_analyzer = APICodeAnalyzer()
