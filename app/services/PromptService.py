from openai import OpenAI
from typing import List, Dict, Any
import logging
import json
import os
import time
import uuid
from ..config import settings
from ..models import ChatMessage
from .logging_service import logging_service, LogLevel, LogCategory

logger = logging.getLogger(__name__)

def load_prompt(prompt_name: str) -> Dict[str, Any]:
    """Load a prompt configuration from JSON file"""
    try:
        # Get the directory of this file
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # Go up one level to app directory, then into prompts/openai
        prompt_path = os.path.join(current_dir, "..", "prompts", "openai", f"{prompt_name}.json")
        
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading prompt {prompt_name}: {str(e)}")
        raise

class PromptServiceBuild:
    def __init__(self):
        if not settings.OPENAI_API_KEY:
            raise ValueError("OpenAI API key not configured. Please set OPENAI_API_KEY environment variable.")
        
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
        logger.info("ChatService initialized with OpenAI client")

    def get_chat_history(self, user_id: str) -> List[ChatMessage]:
        """Get chat history for a user"""
        # TODO: Implement database retrieval
        return []
    
    async def _make_openai_request_with_logging(self, system_prompt: str, user_prompt: str, 
                                               prompt_config: Dict[str, Any], user_id: str,
                                               operation_type: str) -> str:
        """Make OpenAI request with logging integration."""
        start_time = time.time()
        request_id = str(uuid.uuid4())
        model = prompt_config.get("model", settings.OPENAI_MODEL)
        
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=prompt_config.get("temperature", 0.1),
                max_tokens=prompt_config.get("max_tokens", 500)
            )
            
            content = response.choices[0].message.content.strip()
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Log successful LLM call
            try:
                usage = response.usage if hasattr(response, 'usage') else None
                input_tokens = usage.prompt_tokens if usage else len(system_prompt + user_prompt) // 4
                output_tokens = usage.completion_tokens if usage else len(content) // 4
                total_tokens = usage.total_tokens if usage else input_tokens + output_tokens
                
                # Estimate cost using the same method as OpenAI service
                estimated_cost_cents = self._estimate_openai_cost(model, input_tokens, output_tokens)
                
                await logging_service.log_llm_call(
                    service_type="openai",
                    model_name=model,
                    operation_type=operation_type,
                    system_prompt=system_prompt[:1000],
                    user_prompt=user_prompt[:1000],
                    prompt_length=len(system_prompt + user_prompt),
                    response_content=content[:1000],
                    response_length=len(content),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    estimated_cost_cents=estimated_cost_cents,
                    duration_ms=duration_ms,
                    user_id=user_id,
                    success=True,
                    request_id=request_id
                )
            except Exception as log_error:
                logger.error(f"Failed to log PromptService LLM call: {log_error}")
            
            return content
            
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Log failed LLM call
            try:
                await logging_service.log_llm_call(
                    service_type="openai",
                    model_name=model,
                    operation_type=operation_type,
                    system_prompt=system_prompt[:1000],
                    user_prompt=user_prompt[:1000],
                    prompt_length=len(system_prompt + user_prompt),
                    duration_ms=duration_ms,
                    user_id=user_id,
                    success=False,
                    error_message=str(e),
                    request_id=request_id
                )
            except Exception as log_error:
                logger.error(f"Failed to log failed PromptService LLM call: {log_error}")
            
            raise e
    
    def _estimate_openai_cost(self, model: str, input_tokens: int, output_tokens: int) -> int:
        """Estimate OpenAI API cost in cents."""
        # Same pricing estimates as OpenAI service
        pricing = {
            "gpt-4": {"input": 0.03, "output": 0.06},
            "gpt-4-turbo": {"input": 0.01, "output": 0.03},
            "gpt-3.5-turbo": {"input": 0.0015, "output": 0.002},
            "gpt-3.5-turbo-16k": {"input": 0.003, "output": 0.004}
        }
        
        model_pricing = pricing.get(model, pricing["gpt-3.5-turbo"])
        input_cost = (input_tokens / 1000) * model_pricing["input"]
        output_cost = (output_tokens / 1000) * model_pricing["output"]
        
        return int((input_cost + output_cost) * 100)

    async def analyze_user_prompt(self, user_id: str, prompt: str) -> str:
        """
        Analyze user prompt using OpenAI to determine if it's a buildable API, needs clarification, or is nonsense.
        Routes to appropriate function based on analysis.
        """
        try:
            logger.info(f"Analyzing prompt for user {user_id}: {prompt[:100]}...")
            
            # Load prompt configuration from JSON file
            prompt_config = load_prompt("analyze_user_prompt")
            system_prompt = prompt_config["system_prompt"]
            
            user_prompt = f"Analyze this API request: {prompt}"
            
            analysis_result = await self._make_openai_request_with_logging(
                system_prompt, user_prompt, prompt_config, user_id, "prompt_analysis"
            )
            logger.info(f"Analysis result: {analysis_result}")
            
            # Parse the JSON response
            try:
                analysis = json.loads(analysis_result)
                decision = analysis.get("decision", "NOT_BUILDABLE")
                
                # Route to appropriate function based on decision
                if decision == "BUILDABLE":
                    return await self.IcanBuildThis(user_id, prompt)
                elif decision == "NEEDS_CLARIFICATION":
                    questions = analysis.get("questions", [])
                    return await self.AskMoreQuestions(user_id, prompt, questions)
                elif decision == "MODIFY_REQUEST":
                    return await self.HandleModifyRequest(user_id, prompt)
                else:
                    return await self.ICantBuildThis(user_id, prompt, analysis)
                    
            except json.JSONDecodeError:
                logger.error(f"Failed to parse analysis result: {analysis_result}")
                return await self.ICantBuildThis(user_id, prompt, None)
                
        except Exception as e:
            logger.error(f"Error analyzing prompt: {str(e)}")
            return await self.ICantBuildThis(user_id, prompt, None)

    async def CanIBuildThis(self, user_id: str, prompt: str) -> str:
        """Main entry point for prompt analysis"""
        return await self.analyze_user_prompt(user_id, prompt)
    async def AskMoreQuestions(self, user_id: str, prompt: str, questions: List[str] = None) -> str:
        """Handle cases where more clarification is needed"""
        if not questions:
            questions = [
                "What specific functionality should the API provide?",
                "What type of input data will the API receive?",
                "What should the API return as output?",
                "Are there any specific requirements or constraints?"
            ]
        
        response = {
            "status": "needs_clarification",
            "message": "I need more information to build this API for you.",
            "questions": questions,
            "original_prompt": prompt
        }
        
        logger.info(f"Asking for clarification for user {user_id}")
        return json.dumps(response, indent=2)

    async def PropeseTheBuild(self, user_id: str, prompt: str) -> str:
        """
        Create a detailed explanation of what the API will do and ask for user confirmation.
        Uses OpenAI to generate comprehensive API specifications.
        """
        try:
            logger.info(f"Creating detailed API proposal for user {user_id}: {prompt[:100]}...")
            
            # Load prompt configuration from JSON file
            prompt_config = load_prompt("api_proposal")
            system_prompt = prompt_config["system_prompt"]
            
            user_prompt = f"Create a detailed API proposal for this request: {prompt}"
            
            response = self.client.chat.completions.create(
                model=prompt_config.get("model", "gpt-3.5-turbo"),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=prompt_config.get("temperature", 0.3),
                max_tokens=prompt_config.get("max_tokens", 1000)
            )
            
            proposal_result = response.choices[0].message.content.strip()
            logger.info(f"Generated API proposal: {proposal_result[:200]}...")
            
            # Parse the JSON response
            try:
                proposal = json.loads(proposal_result)
                
                # Create user-friendly response with the proposal
                response_data = {
                    "status": "proposal_ready",
                    "message": "Here's what I propose to build for you:",
                    "original_prompt": prompt,
                    "proposal": proposal,
                    "confirmation_needed": True,
                    "next_steps": [
                        "Review the API proposal carefully",
                        "Click 'Build It' if you're satisfied",
                        "Or ask for modifications if needed"
                    ]
                }
                
                logger.info(f"Created detailed proposal for user {user_id}")
                logger.info(f"Response data: {response_data}")
                return json.dumps(response_data, indent=2)
                
            except json.JSONDecodeError:
                logger.error(f"Failed to parse proposal result: {proposal_result}")
                # Fallback to simpler proposal
                return await self._create_simple_proposal(user_id, prompt)
                
        except Exception as e:
            logger.error(f"Error creating API proposal: {str(e)}")
            return await self._create_simple_proposal(user_id, prompt)

    async def _create_simple_proposal(self, user_id: str, prompt: str) -> str:
        """Fallback method to create a simple proposal if detailed generation fails"""
        response = {
            "status": "proposal_ready",
            "message": "Here's what I propose to build for you:",
            "original_prompt": prompt,
            "proposal": {
                "api_name": "Custom API",
                "description": f"An API based on your request: {prompt}",
                "functionality": ["Process your specified requirements"]
            },
            "confirmation_needed": True,
            
        }
        
        logger.info(f"Created simple proposal fallback for user {user_id}")
        return json.dumps(response, indent=2)

    async def IcanBuildThis(self, user_id: str, prompt: str) -> str:
        """Handle buildable API requests - now routes to proposal generation"""
        logger.info(f"Routing buildable API request to proposal generation for user {user_id}")
        return await self.PropeseTheBuild(user_id, prompt)

    async def ICantBuildThis(self, user_id: str, prompt: str, analysis: dict = None) -> str:
        """Handle non-buildable requests"""
        # Use analysis reasoning if available, otherwise use generic message
        if analysis and analysis.get("reasoning"):
            reasons = [analysis.get("reasoning")]
            # Use more specific message when we have analysis details
            message = "I can't build this API based on the provided request."
        else:
            reasons = [
                "The request may be too vague or unclear",
                "The functionality might not be technically feasible",
                "The request could involve inappropriate or harmful content"
            ]
            message = "I'm sorry, but I can't build this API."
        
        response = {
            "status": "not_buildable",
            "message": message,
            "reasons": reasons,
            "suggestions": [
                "Try to be more specific about what you want the API to do",
                "Provide examples of input and expected output", 
                "Focus on legitimate business or educational use cases"
            ]
        }
        
        logger.info(f"Rejected API request for user {user_id}")
        return json.dumps(response, indent=2)

    async def HandleModifyRequest(self, user_id: str, prompt: str) -> str:
        """Handle modification requests for existing APIs"""
        response = {
            "status": "modify_request",
            "message": "I understand you want to modify an existing API.",
            "prompt": prompt,
            "instructions": [
                "If you have a recently generated API in this chat, you can use the 'Modify' button",
                "For saved APIs, please specify which API you want to modify",
                "Describe what changes you want to make to the API"
            ],
            "next_steps": [
                "Click the 'Modify' button on your last generated API",
                "Or tell me which saved API you want to modify",
                "Specify exactly what changes you need"
            ]
        }
        
        logger.info(f"Detected modify request for user {user_id}")
        return json.dumps(response, indent=2)
    

class PromptServiceModify:
    def __init__(self):
        if not settings.OPENAI_API_KEY:
            raise ValueError("OpenAI API key not configured. Please set OPENAI_API_KEY environment variable.")
        
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
        logger.info("PromptServiceModify initialized with OpenAI client")

    async def analyze_modify_prompt(self, user_id: str, prompt: str, existing_api_code: str = None) -> str:
        """
        Analyze user modification request using OpenAI to determine what changes need to be made.
        """
        try:
            logger.info(f"Analyzing modify prompt for user {user_id}: {prompt[:100]}...")
            
            # Load prompt configuration from JSON file
            prompt_config = load_prompt("analyze_modify_prompt")
            system_prompt = prompt_config["system_prompt"]
            
            user_prompt = f"Analyze this API modification request: {prompt}"
            if existing_api_code:
                user_prompt += f"\n\nExisting API code:\n{existing_api_code[:1000]}..."
            
            response = self.client.chat.completions.create(
                model=prompt_config.get("model", settings.OPENAI_MODEL),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=prompt_config.get("temperature", 0.1),
                max_tokens=prompt_config.get("max_tokens", 500)
            )
            
            analysis_result = response.choices[0].message.content.strip()
            logger.info(f"Modify analysis result: {analysis_result}")
            
            # Parse the JSON response
            try:
                analysis = json.loads(analysis_result)
                modification_type = analysis.get("modification_type", "UNCLEAR_REQUEST")
                
                # Route to appropriate function based on modification type
                if modification_type == "UNCLEAR_REQUEST":
                    questions = analysis.get("questions", [])
                    return await self.AskForClarification(user_id, prompt, questions)
                else:
                    return await self.ProcessModification(user_id, prompt, analysis)
                    
            except json.JSONDecodeError:
                logger.error(f"Failed to parse modification analysis result: {analysis_result}")
                return await self.AskForClarification(user_id, prompt)
                
        except Exception as e:
            logger.error(f"Error analyzing modify prompt: {str(e)}")
            return await self.AskForClarification(user_id, prompt)

    async def AskForClarification(self, user_id: str, prompt: str, questions: List[str] = None) -> str:
        """Handle cases where modification request needs clarification"""
        if not questions:
            questions = [
                "What specific changes do you want to make to the API?",
                "Which part of the API functionality should be modified?",
                "What should the new behavior be?",
                "Are you looking to add, remove, or change existing features?"
            ]
        
        response = {
            "status": "needs_clarification",
            "message": "I need more details about what you want to modify.",
            "questions": questions,
            "original_prompt": prompt,
            "suggestions": [
                "Be specific about which part of the API to modify",
                "Describe the desired outcome after modification",
                "Provide examples if possible"
            ]
        }
        
        logger.info(f"Asking for modification clarification for user {user_id}")
        return json.dumps(response, indent=2)

    async def ProcessModification(self, user_id: str, prompt: str, analysis: Dict[str, Any]) -> str:
        """Process a clear modification request"""
        modification_type = analysis.get("modification_type")
        specific_changes = analysis.get("specific_changes", [])
        complexity = analysis.get("complexity", "MEDIUM")
        
        response = {
            "status": "modification_ready",
            "message": "I understand what you want to modify.",
            "modification_type": modification_type,
            "complexity": complexity,
            "prompt": prompt,
            "planned_changes": specific_changes,
            "next_steps": [
                "I'll analyze your existing API code",
                "Apply the requested modifications",
                "Test the changes for compatibility",
                "Provide you with the updated API"
            ],
            "estimated_effort": self._get_effort_estimate(complexity)
        }
        
        logger.info(f"Processing {modification_type} modification for user {user_id}")
        return json.dumps(response, indent=2)

    async def CanIModifyThis(self, user_id: str, prompt: str, existing_api_code: str = None) -> str:
        """Main entry point for modification analysis"""
        return await self.analyze_modify_prompt(user_id, prompt, existing_api_code)

    def _get_effort_estimate(self, complexity: str) -> str:
        """Get effort estimate based on complexity"""
        estimates = {
            "LOW": "Quick modification (1-2 minutes)",
            "MEDIUM": "Standard modification (2-5 minutes)", 
            "HIGH": "Complex modification (5-10 minutes)"
        }
        return estimates.get(complexity, "Standard modification (2-5 minutes)")

    async def ValidateModificationRequest(self, user_id: str, prompt: str, api_context: Dict[str, Any]) -> str:
        """Validate if the modification request is feasible with the given API"""
        try:
            # Load prompt configuration from JSON file
            prompt_config = load_prompt("validate_modification")
            system_prompt = prompt_config["system_prompt"]
            
            user_prompt = f"""
            Modification request: {prompt}
            API context: {json.dumps(api_context, indent=2)}
            
            Is this modification feasible?
            """
            
            response = self.client.chat.completions.create(
                model=prompt_config.get("model", settings.OPENAI_MODEL),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=prompt_config.get("temperature", 0.1),
                max_tokens=prompt_config.get("max_tokens", 300)
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            logger.error(f"Error validating modification request: {str(e)}")
            return json.dumps({
                "feasible": False,
                "reasoning": "Error occurred during validation",
                "potential_issues": ["Validation system error"],
                "recommendations": ["Please try again or rephrase your request"]
            }, indent=2)