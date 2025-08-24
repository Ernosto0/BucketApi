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
            # logger.info(f"Making OpenAI request with model: {model}")
            # logger.info(f"System prompt length: {len(system_prompt)} characters")
            # logger.info(f"User prompt length: {len(user_prompt)} characters")
            # logger.info(f"Max completion tokens: {prompt_config.get('max_completion_tokens', 500)}")
            # logger.info(f"System prompt preview: {system_prompt[:200]}...")
            # logger.info(f"User prompt: {user_prompt}")
            
            response = self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_completion_tokens=prompt_config.get("max_completion_tokens", 500)
            )
            
            # Log the full response structure for debugging
            logger.info(f"OpenAI response object: {response}")
            logger.info(f"Response choices length: {len(response.choices)}")
            logger.info(f"Response usage: {response.usage}")
            
            # Check finish reason
            finish_reason = response.choices[0].finish_reason if response.choices else None
            logger.info(f"OpenAI finish reason: {finish_reason}")
            
            content = response.choices[0].message.content
            if content is None:
                logger.error("OpenAI returned None content")
                logger.error(f"Message object: {response.choices[0].message}")
                logger.error(f"Finish reason: {finish_reason}")
                content = ""
            else:
                content = content.strip()
            
            # Handle length-limited responses
            if finish_reason == "length" and len(content) == 0:
                logger.error("OpenAI hit token limit but returned empty content - this is unusual")
                raise Exception("OpenAI response was truncated due to token limit and returned empty content. Please try with a shorter prompt or increase token limits.")
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            logger.info(f"OpenAI response content length: {len(content)} characters")
            if len(content) > 0:
                logger.info(f"OpenAI response preview: {content[:200]}{'...' if len(content) > 200 else ''}")
            else:
                logger.error("Empty content received from OpenAI")
            
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
                logger.error(f"Failed to log PromptService LLM call: {str(log_error)}")
            
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
                logger.error(f"Failed to log failed PromptService LLM call: {str(log_error)}")
            
            raise e
    
    def _estimate_openai_cost(self, model: str, input_tokens: int, output_tokens: int) -> int:
        """Estimate OpenAI API cost in cents."""
        # Same pricing estimates as OpenAI service
        pricing = {
            "gpt-4": {"input": 0.03, "output": 0.06},
            "gpt-4-turbo": {"input": 0.01, "output": 0.03},
            "gpt-4o-mini": {"input": 0.0015, "output": 0.002},
            "gpt-3.5-turbo": {"input": 0.003, "output": 0.004},
            "gpt-3.5-turbo-16k": {"input": 0.003, "output": 0.004},
            # GPT-5 models (based on your pricing table)
            "gpt-5": {"input": 1.25, "output": 10.00},
            "gpt-5-mini": {"input": 0.25, "output": 2.00},
            "gpt-5-nano": {"input": 0.05, "output": 0.40},
            "gpt-5-chat-latest": {"input": 1.25, "output": 10.00}
        }
        
        # Default to gpt-3.5-turbo pricing if model not found
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
                    
            except json.JSONDecodeError as parse_error:
                logger.error(f"Failed to parse analysis result as JSON: {str(parse_error)}")
                logger.error(f"Raw analysis result content: {repr(analysis_result)}")
                logger.error(f"Analysis result length: {len(analysis_result)} characters")
                return await self.ICantBuildThis(user_id, prompt, None)
                
        except Exception as e:
            logger.error(f"Error analyzing prompt: {str(e)}")
            return await self.ICantBuildThis(user_id, prompt, None)

    async def CanIBuildThis(self, user_id: str, prompt: str) -> str:
        """Main entry point for prompt analysis"""
        return await self.analyze_user_prompt(user_id, prompt)
    
    async def CanIModifyProposal(self, user_id: str, original_prompt: str, modification_request: str) -> str:
        """
        Analyze a request to modify an existing proposal.
        This is specifically for proposal-stage modifications, not code modifications.
        """
        try:
            logger.info(f"Analyzing proposal modification for user {user_id}: {modification_request[:100]}...")
            
            # Load prompt configuration from JSON file
            prompt_config = load_prompt("analyze_proposal_modification")
            system_prompt = prompt_config["system_prompt"]
            
            user_prompt = f"""Original API proposal: {original_prompt}

Modification request: {modification_request}

Analyze what the user wants to change about their original proposal."""
            
            analysis_result = await self._make_openai_request_with_logging(
                system_prompt, user_prompt, prompt_config, user_id, "proposal_modification_analysis"
            )
            logger.info(f"Proposal modification analysis result: {analysis_result}")
            
            # Check for empty response
            if not analysis_result or analysis_result.strip() == "":
                logger.error("Empty response received from OpenAI for proposal modification analysis")
                return json.dumps({
                    "status": "error",
                    "message": "Failed to analyze the modification request due to empty response. Please try again.",
                    "original_prompt": original_prompt,
                    "modification_request": modification_request
                }, indent=2)
            
            # Parse the JSON response and convert to our expected format
            try:
                analysis = json.loads(analysis_result)
                decision = analysis.get("status", "INVALID_MODIFICATION")
                
                # Convert the response to match our ProposalModificationResponse format
                if decision == "VALID_MODIFICATION":
                    # Generate a proper proposal using the modified requirements
                    modified_requirements = analysis.get("modified_requirements", "")
                    
                    try:
                        # Call the existing proposal generation method with the modified requirements
                        proposal_response = await self.PropeseTheBuild(user_id, modified_requirements)
                        proposal_data = json.loads(proposal_response)
                        proposal_object = proposal_data.get("proposal", {})
                        
                        # If proposal generation failed, create a minimal fallback
                        if not proposal_object:
                            proposal_object = {
                                "api_name": "Modified API",
                                "description": modified_requirements,
                                "functionality": ["Process modified requirements"]
                            }
                    except Exception as proposal_error:
                        logger.error(f"Failed to generate proposal for modification: {str(proposal_error)}")
                        # Fallback proposal if generation fails
                        proposal_object = {
                            "api_name": "Modified API", 
                            "description": modified_requirements,
                            "functionality": ["Process modified requirements"]
                        }
                    
                    return json.dumps({
                        "status": "buildable",
                        "message": f"I can modify your proposal: {analysis.get('reasoning', 'Modification is valid')}",
                        "modification_type": analysis.get("modification_type"),
                        "specific_changes": analysis.get("specific_changes", []),
                        "modified_requirements": modified_requirements,
                        "original_prompt": original_prompt,
                        "modification_request": modification_request,
                        "proposal": proposal_object
                    }, indent=2)
                elif decision == "NEEDS_CLARIFICATION":
                    return json.dumps({
                        "status": "needs_clarification",
                        "message": f"I need more details about your modification: {analysis.get('reasoning', 'Please clarify your request')}",
                        "questions": analysis.get("questions", []),
                        "original_prompt": original_prompt,
                        "modification_request": modification_request
                    }, indent=2)
                else:  # INVALID_MODIFICATION
                    return json.dumps({
                        "status": "not_buildable",
                        "message": f"I cannot make this modification: {analysis.get('reasoning', 'Invalid modification request')}",
                        "reasons": [analysis.get("reasoning", "Invalid modification request")],
                        "original_prompt": original_prompt,
                        "modification_request": modification_request
                    }, indent=2)
                    
            except json.JSONDecodeError as parse_error:
                logger.error(f"Failed to parse proposal modification analysis result as JSON: {str(parse_error)}")
                logger.error(f"Raw analysis result content: {repr(analysis_result)}")
                return json.dumps({
                    "status": "error",
                    "message": "Failed to analyze the modification request. Please try again.",
                    "original_prompt": original_prompt,
                    "modification_request": modification_request
                }, indent=2)
                
        except Exception as e:
            logger.error(f"Error analyzing proposal modification: {str(e)}")
            
            # Try a fallback with simpler approach
            try:
                logger.info("Attempting fallback analysis with simplified prompt...")
                fallback_result = await self._fallback_proposal_analysis(original_prompt, modification_request, user_id)
                return fallback_result
            except Exception as fallback_error:
                logger.error(f"Fallback analysis also failed: {str(fallback_error)}")
                
            return json.dumps({
                "status": "error",
                "message": f"Failed to analyze modification request: {str(e)}",
                "original_prompt": original_prompt,
                "modification_request": modification_request
            }, indent=2)
    
    async def _fallback_proposal_analysis(self, original_prompt: str, modification_request: str, user_id: str) -> str:
        """Fallback method for proposal analysis with simpler prompt."""
        system_prompt = """Analyze this API modification request and respond with valid JSON only.
        
        Determine if this is:
        - VALID_MODIFICATION: Clear, specific change request
        - NEEDS_CLARIFICATION: Vague or unclear
        - INVALID_MODIFICATION: Impossible or inappropriate
        
        Respond with exactly this JSON format:
        {"status": "VALID_MODIFICATION", "reasoning": "brief explanation", "modification_type": "scope_reduction", "specific_changes": ["change description"], "modified_requirements": "I need an API that..."}"""
        
        user_prompt = f"Original: {original_prompt}\nModification: {modification_request}\nAnalyze this modification request."
        
        # Use a more conservative config for fallback
        fallback_config = {
            "model": "gpt-5-mini",
            "max_completion_tokens": 300
        }
        
        
        try:
            response = await self._make_openai_request_with_logging(
                system_prompt, user_prompt, fallback_config, user_id, "fallback_proposal_analysis"
            )
            
            if response and response.strip():
                # Try to parse as JSON
                analysis = json.loads(response)
                status = analysis.get("status", "VALID_MODIFICATION")
                
                if status == "VALID_MODIFICATION":
                    # Use simple fallback proposal (this is already a fallback path)
                    fallback_proposal = {
                        "api_name": "Modified API",
                        "description": analysis.get("modified_requirements", f"Modified version of: {modification_request}"),
                        "functionality": ["Process requests with modified specifications"]
                    }
                    
                    return json.dumps({
                        "status": "buildable",
                        "message": f"I can modify your proposal: {analysis.get('reasoning', 'Modification is valid')}",
                        "modification_type": analysis.get("modification_type", "general_change"),
                        "specific_changes": analysis.get("specific_changes", []),
                        "modified_requirements": analysis.get("modified_requirements", f"Modified version of: {modification_request}"),
                        "original_prompt": original_prompt,
                        "modification_request": modification_request,
                        "proposal": fallback_proposal
                    }, indent=2)
                else:
                    return json.dumps({
                        "status": "needs_clarification",
                        "message": "Could you be more specific about what you want to modify?",
                        "questions": ["What specific part of the API do you want to change?", "What should the new behavior be?"],
                        "original_prompt": original_prompt,
                        "modification_request": modification_request
                    }, indent=2)
            else:
                raise Exception("Empty response from fallback")
                
        except Exception as e:
            logger.error(f"Fallback analysis failed: {str(e)}")
            raise e
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
                model=prompt_config.get("model", "gpt-5-mini"),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
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
        """
        Handle modification requests. Since we can't reliably determine context from keywords,
        we return a response that provides options for both proposal and code modifications.
        The frontend should handle routing based on conversation state.
        """
        response = {
            "status": "modify_request",
            "message": "I understand you want to make modifications.",
            "prompt": prompt,
            "instructions": [
                "If you're modifying a proposal (before generating code), the system should use proposal modification",
                "If you're modifying existing generated code, use the API modification tools",
                "The frontend should route based on conversation context"
            ],
            "next_steps": [
                "For proposal modifications: Use /modify-proposal endpoint",
                "For code modifications: Use /modify-api endpoint or Modify button",
                "Frontend should determine which based on current conversation state"
            ],
            "context_note": "Frontend should track conversation state to route appropriately"
        }
        
        logger.info(f"Detected modify request for user {user_id} - frontend should handle routing based on context")
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
                ]
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
                ]            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            logger.error(f"Error validating modification request: {str(e)}")
            return json.dumps({
                "feasible": False,
                "reasoning": "Error occurred during validation",
                "potential_issues": ["Validation system error"],
                "recommendations": ["Please try again or rephrase your request"]
            }, indent=2)