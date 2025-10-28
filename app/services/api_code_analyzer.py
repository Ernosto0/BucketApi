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
    initial_tokens_estimate: int  # Initial estimate for display - will be replaced with real usage
    complexity_rating: str
    api_calls_detected: List[str]
    confidence_score: float
    analysis_details: Dict[str, Any]

class APICodeAnalyzer:
    """Service to analyze generated API code and detect LLM usage patterns."""
    
    def __init__(self):
        # Model detection patterns (ordered from most specific to least specific)
        self.MODEL_PATTERNS = [
            # OpenAI models - specific variants first
            (r'model\s*=\s*[\'\"](gpt-5-mini)[\'"]', 'gpt-5-mini'),
            (r'model\s*=\s*[\'\"](gpt-5-nano)[\'"]', 'gpt-5-nano'),
            (r'model\s*=\s*[\'\"](gpt-5-pro)[\'"]', 'gpt-5-pro'),
            (r'model\s*=\s*[\'\"](gpt-4o-mini)[\'"]', 'gpt-4o-mini'),
            (r'model\s*=\s*[\'\"](gpt-4o-2024-05-13)[\'"]', 'gpt-4o-2024-05-13'),
            (r'model\s*=\s*[\'\"](gpt-4o)[\'"]', 'gpt-4o'),
            (r'model\s*=\s*[\'\"](gpt-4-turbo)[\'"]', 'gpt-4-turbo'),
            (r'model\s*=\s*[\'\"](gpt-4)[\'"]', 'gpt-4'),
            (r'model\s*=\s*[\'\"](gpt-3\.5-turbo)[\'"]', 'gpt-3.5-turbo'),
            # General GPT-5 pattern (only matches if specific variants don't match first)
            (r'model\s*=\s*[\'\"](gpt-5(?!-mini|-nano|-pro)[^\'\"]*)[\'"]', 'gpt-5'),
            
            # Claude models
            (r'model\s*=\s*[\'\"](claude-3-haiku[^\'\"]*)[\'"]', 'claude-3-haiku'),
            (r'model\s*=\s*[\'\"](claude-3-sonnet[^\'\"]*)[\'"]', 'claude-3-sonnet'),
            (r'model\s*=\s*[\'\"](claude-3-opus[^\'\"]*)[\'"]', 'claude-3-opus'),
            (r'model\s*=\s*[\'\"](claude-4[^\'\"]*)[\'"]', 'claude-4'),
            
            # Generic patterns
            (r'[\'\"](gpt-[^\'\"]+)[\'"]', 'gpt-detected'),
            (r'[\'\"](claude-[^\'\"]+)[\'"]', 'claude-detected'),
        ]
        
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
            
            # Step 4: Get initial tokens estimate (for display only)
            estimated_tokens = self._get_initial_tokens_estimate(code, primary_model)
            
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
                initial_tokens_estimate=estimated_tokens,
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
                initial_tokens_estimate=0,
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
        
        # Enhanced debugging for model detection
        logger.debug(f"Starting model extraction from code (length: {len(code)})")
        
        # Track which model strings we've already matched to avoid duplicates
        matched_strings = set()
        
        for pattern, model_name in self.MODEL_PATTERNS:
            matches = re.findall(pattern, code, re.IGNORECASE)
            if matches:
                logger.info(f"Pattern '{pattern}' matched: {matches}")
                for match in matches:
                    if isinstance(match, str) and match not in matched_strings:
                        models_found.append(match)
                        matched_strings.add(match)
                        logger.info(f"Added model from match: {match}")
                    elif model_name != 'gpt-detected' and model_name != 'claude-detected' and model_name not in matched_strings:
                        models_found.append(model_name)
                        matched_strings.add(model_name)
                        logger.info(f"Added model from pattern: {model_name}")
        
        # Remove duplicates while preserving order
        unique_models = []
        for model in models_found:
            if model not in unique_models:
                unique_models.append(model)
        
        logger.info(f"AI models detected: {unique_models}")
        
        # Enhanced debugging for failed detection
        if not unique_models:
            logger.warning("No AI models detected in code. Performing detailed analysis...")
            
            # Fallback: Try to extract models using simpler patterns
            fallback_models = self._fallback_model_detection(code)
            if fallback_models:
                logger.info(f"Fallback detection found models: {fallback_models}")
                unique_models.extend(fallback_models)
            
            # Check for common model patterns manually for debugging
            if 'gpt-4o-mini' in code:
                logger.warning("Found 'gpt-4o-mini' in code but regex didn't match!")
                # Try to find the exact context
                lines = code.split('\n')
                for i, line in enumerate(lines):
                    if 'gpt-4o-mini' in line:
                        logger.warning(f"Line {i+1}: {line.strip()}")
            
            if 'model=' in code:
                logger.warning("Found 'model=' in code, checking context...")
                lines = code.split('\n')
                for i, line in enumerate(lines):
                    if 'model=' in line:
                        logger.warning(f"Line {i+1}: {line.strip()}")
            
            # Show a larger code snippet for debugging
            logger.debug(f"Code snippet for debugging:\n{code[:1000]}...")
        
        return unique_models
    
    def _fallback_model_detection(self, code: str) -> List[str]:
        """Fallback method to detect models when regex patterns fail."""
        models = []
        
        # Common model names to look for
        known_models = [
            'gpt-4o-mini', 'gpt-4o', 'gpt-4-turbo', 'gpt-4', 'gpt-3.5-turbo',
            'claude-3-haiku', 'claude-3-sonnet', 'claude-3-opus', 'claude-4',
            'claude-3-5-haiku-latest', 'claude-3-5-sonnet-latest'
        ]
        
        # Simple string search for model names
        for model in known_models:
            if model in code:
                # Verify it's actually used as a model parameter
                if f'"{model}"' in code or f"'{model}'" in code:
                    models.append(model)
                    logger.info(f"Fallback detection found model: {model}")
        
        return models
    
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
    
    def _get_initial_tokens_estimate(self, code: str, primary_model: Optional[str]) -> int:
        """
        Provide initial token estimate for APIs that haven't been executed yet.
        This is only used for initial pricing display - real usage will be tracked during execution.
        """
        
        # If no AI model detected, return 0 tokens (free processing)
        if not primary_model:
            logger.debug("No AI model detected - returning 0 tokens (free processing)")
            return 0
        
        # For APIs with LLM usage, provide a conservative baseline estimate
        # This will be replaced with real usage data once the API is executed
        baseline_estimate = 500  # Conservative baseline for LLM APIs
        
        # Extract max_tokens if explicitly specified in code
        max_tokens_match = re.search(self.TOKEN_ESTIMATION_PATTERNS['max_tokens'], code)
        if max_tokens_match:
            specified_max_tokens = int(max_tokens_match.group(1))
            baseline_estimate = max(baseline_estimate, specified_max_tokens)
        
        logger.debug(f"Initial token estimate for pricing display: {baseline_estimate} (will be updated with real usage)")
        return baseline_estimate
    
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
