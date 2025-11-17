import os
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional, Any
import httpx
import json
from dotenv import load_dotenv

load_dotenv()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent?key={GEMINI_API_KEY}"
class ChatHistoryRequest(BaseModel):
    chat_history: Dict[str, str]  
    current_text: str  
class ConversationalResponse(BaseModel):
    reply_text: str 
class FlowchartRequest(BaseModel):
    chat_history: Dict[str, str] 
class FlowchartResponse(BaseModel):
    updated_plan_json: Optional[str] = None
    error: Optional[str] = None
CONVERSATIONAL_SYSTEM_PROMPT = """
You are "EventFlow," a concise and focused event planning assistant.

YOUR GOAL:
Gather necessary event details one piece at a time. Do not generate flowcharts yet.

STRICT RULES FOR INTERACTION:
1. **ASK ONLY ONE QUESTION AT A TIME**: Never ask multiple questions in a single response.
2. **KEEP IT SHORT**: Your entire response must be under 50 words.
3. **NO LISTS**: Do not provide lists of suggestions unless explicitly asked.
4. **BE DIRECT**: Skip long greetings or "fluff" text. Get straight to the point.

INFORMATION TO GATHER (ONE BY ONE):
- Event Type (Wedding, Corporate, etc.)
- Date/Timeframe
- Approximate Guest Count
- Budget Range
- Venue Preference
- Specific Vibe/Style

HOW TO RESPOND:
- If the user says "Hi", ask about the Event Type.
- If the user gives the Event Type, acknowledge briefly and ask for the Date.
- If the user gives partial info, ask for the next missing critical piece.

OUTPUT FORMAT:
Return ONLY a JSON object:
{
  "reply_text": "Your short, focused question here."
}
"""

FLOWCHART_SYSTEM_PROMPT = """
You are "EventFlow," an expert event planning system that creates detailed, actionable event plans.

YOUR TASK:
Analyze the entire conversation history provided and create a comprehensive, step-by-step event plan (flowchart) based on ALL the information gathered.

INFORMATION VALIDATION:
Before creating the plan, verify that you have AT LEAST these essential details:
1. Event type/description
2. Approximate date or timeframe
3. Guest count (even rough estimate)
4. Budget range (even rough estimate)
5. Basic venue preference or location type

If ANY of these essential details are missing or unclear, you MUST return an error message instead of a plan.

PLAN STRUCTURE:
If sufficient information exists, create a detailed plan with:
- **event_plan**: Array of steps, each containing:
  - step: Sequential number
  - task: Clear task name
  - details: Comprehensive details about what needs to be done
  - reasoning: Why this step is important and how it fits in the overall plan
- **required_vendors**: List of vendors/services needed (be specific based on their requirements)
- **suggestions**: Helpful suggestions, theme ideas, tips, or recommendations based on their event

PLAN QUALITY:
- Steps should be in logical order (vision → budget → venue → vendors → details → execution)
- Be specific and actionable
- Consider their budget, guest count, and preferences
- Include realistic timelines if date is known
- Prioritize based on what they emphasized as important

OUTPUT FORMAT:
Return a JSON object with this EXACT structure:

If SUFFICIENT information:
{
  "reply_text": "Brief confirmation message",
  "updated_plan_json": {
    "event_plan": [
      {
        "step": 1,
        "task": "Task name",
        "details": "Detailed description",
        "reasoning": "Why this matters"
      }
    ],
    "required_vendors": ["Vendor 1", "Vendor 2"],
    "suggestions": "Your helpful suggestions here"
  }
}

If INSUFFICIENT information:
{
  "reply_text": "I don't have enough information yet to create a comprehensive event plan.",
  "error": "Missing critical information. I still need: [list specific missing items like: event date/timeframe, guest count, budget range, etc.]. Please continue the conversation to provide these details."
}
"""
def convert_chat_history_to_gemini_format(chat_history: Dict[str, str]) -> List[Dict[str, Any]]:
    messages = []
    for key in sorted(chat_history.keys()):
        role = "model" if key.startswith("ai") else "user"
        text = chat_history[key]
        
        if text and text.strip(): 
            messages.append({
                "role": role,
                "parts": [{"text": text}]
            })
    
    return messages

def validate_information_sufficiency(chat_history: Dict[str, str]) -> tuple[bool, List[str]]:

    full_conversation = " ".join(chat_history.values()).lower()
    missing_items = []
    event_keywords = ["event", "party", "wedding", "birthday", "celebration", "anniversary", "corporate"]
    if not any(keyword in full_conversation for keyword in event_keywords):
        missing_items.append("event type/description")
    date_keywords = ["date", "when", "month", "year", "day", "week", "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
    if not any(keyword in full_conversation for keyword in date_keywords):
        missing_items.append("event date or timeframe")
    guest_keywords = ["guest", "people", "person", "attendee", "invite"]
    numbers = any(char.isdigit() for char in full_conversation)
    if not (any(keyword in full_conversation for keyword in guest_keywords) and numbers):
        missing_items.append("guest count") 
    budget_keywords = ["budget", "spend", "cost", "price", "dollar", "$", "money", "afford"]
    if not any(keyword in full_conversation for keyword in budget_keywords):
        missing_items.append("budget range")
    venue_keywords = ["venue", "location", "place", "where", "home", "restaurant", "hall", "outdoor", "indoor"]
    if not any(keyword in full_conversation for keyword in venue_keywords):
        missing_items.append("venue preference")
    is_sufficient = len(missing_items) <= 1
    return is_sufficient, missing_items

async def get_conversational_response(chat_history: Dict[str, str], current_text: str) -> Dict[str, Any]:
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is not configured on the server.")
    gemini_messages = convert_chat_history_to_gemini_format(chat_history)
    gemini_messages.append({
        "role": "user",
        "parts": [{"text": current_text}]
    })
    
    payload = {
        "systemInstruction": {
            "parts": [{"text": CONVERSATIONAL_SYSTEM_PROMPT}]
        },
        "contents": gemini_messages,
        "generationConfig": {
            "responseMimeType": "application/json",
        }
    }
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(API_URL, json=payload)
            response.raise_for_status()
            result = response.json()
            ai_json_response = result["candidates"][0]["content"]["parts"][0]["text"]
            final_data = json.loads(ai_json_response)
            return final_data
    
    except httpx.HTTPStatusError as e:
        print(f"HTTP Error: {e.response.status_code} - {e.response.text}")
        raise HTTPException(status_code=e.response.status_code, detail=f"Gemini API Error: {e.response.text}")
    except (Exception, json.JSONDecodeError) as e:
        print(f"An error occurred: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get or parse AI response: {str(e)}")

async def get_flowchart_response(chat_history: Dict[str, str]) -> Dict[str, Any]:
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is not configured on the server.")
    
    is_sufficient, missing_items = validate_information_sufficiency(chat_history)
    
    gemini_messages = convert_chat_history_to_gemini_format(chat_history)
    
    summary_prompt = f"""
    Based on the entire conversation history above, create a comprehensive event plan.
    Conversation has been analyzed. Information sufficiency: {"SUFFICIENT" if is_sufficient else "INSUFFICIENT"}
    {f"Missing items: {', '.join(missing_items)}" if not is_sufficient else ""}
    
    Please analyze all the details provided and generate the appropriate response.
    """
    gemini_messages.append({
        "role": "user",
        "parts": [{"text": summary_prompt}]
    })
    
    payload = {
        "systemInstruction": {
            "parts": [{"text": FLOWCHART_SYSTEM_PROMPT}]
        },
        "contents": gemini_messages,
        "generationConfig": {
            "responseMimeType": "application/json",
        }
    }
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(API_URL, json=payload)
            response.raise_for_status()
            result = response.json()
            ai_json_response = result["candidates"][0]["content"]["parts"][0]["text"]
            final_data = json.loads(ai_json_response)
            return final_data
    
    except httpx.HTTPStatusError as e:
        print(f"HTTP Error: {e.response.status_code} - {e.response.text}")
        raise HTTPException(status_code=e.response.status_code, detail=f"Gemini API Error: {e.response.text}")
    except (Exception, json.JSONDecodeError) as e:
        print(f"An error occurred: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get or parse AI response: {str(e)}")
    
app = FastAPI(title="EventFlow API", version="2.0")

@app.post("/chat", response_model=ConversationalResponse)
async def chat_endpoint(request: ChatHistoryRequest):
    try:
        ai_data = await get_conversational_response(request.chat_history, request.current_text)
        reply = ai_data.get("reply_text", "I'm here to help you plan your event! Could you tell me more about what you're planning?")
        
        return ConversationalResponse(reply_text=reply)
        
    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"Error in /chat endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@app.post("/generate-flowchart", response_model=FlowchartResponse)
async def generate_flowchart_endpoint(request: FlowchartRequest):
    """
    Generate a detailed event flowchart based on the entire conversation history.
    
    This endpoint analyzes all the information gathered during the conversation
    and creates a comprehensive, step-by-step event plan.
    
    If insufficient information is available, it returns an error message
    indicating what details are still needed.
    """
    try:
        ai_data = await get_flowchart_response(request.chat_history)
        
        # Check if there's an error (insufficient information)
        if "error" in ai_data and ai_data["error"]:
            return FlowchartResponse(
                updated_plan_json=None,
                error=ai_data["error"]
            )
        if "updated_plan_json" in ai_data:
            plan_json = json.dumps(ai_data["updated_plan_json"])
            return FlowchartResponse(
                updated_plan_json=plan_json,
                error=None
            )
        return FlowchartResponse(
            updated_plan_json=None,
            error="Unable to generate flowchart. Please provide more details about your event."
        )
        
    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"Error in /generate-flowchart endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "Welcome to EventFlow API v2.0",
        "endpoints": {
            "/chat": "POST - Conversational endpoint to gather event details",
            "/generate-flowchart": "POST - Generate detailed event flowchart",
            "/docs": "GET - Interactive API documentation"
        }
    }

if __name__ == "__main__":
    print("=" * 60)
    print("Starting EventFlow API v2.0...")
    print("=" * 60)
    print("Server: http://127.0.0.1:8000")
    print("API Docs: http://127.0.0.1:8000/docs")
    print("=" * 60)
    print("\nEndpoints:")
    print("POST /chat - Conversational event planning")
    print("POST /generate-flowchart - Generate event flowchart")
    print("=" * 60)
    uvicorn.run("eventflow_api:app", host="127.0.0.1", port=8000, reload=True)
