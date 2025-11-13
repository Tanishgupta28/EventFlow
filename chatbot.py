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

class ChatPart(BaseModel):
    text: str

class ChatMessage(BaseModel):
    role: str
    parts: List[ChatPart]

class ChatRequest(BaseModel):
    chat_history: List[ChatMessage]
    current_plan_json: Optional[str] = ""

class ChatResponse(BaseModel):
    reply_text: str
    updated_plan_json: str

SYSTEM_PROMPT = """
You are "EventFlow," a world-class, detail-obsessed, and creative event planning expert. 
Your goal is to act as a collaborative assistant. You will have a natural conversation with the user,
ask clarifying questions, give suggestions, and help them build a complete event plan from scratch.

CONTEXT:
You will be given the user's entire `chat_history` and a `current_plan_json`.
1.  **If `current_plan_json` is empty:** The user is new. Your first job is to be friendly, 
    ask for the key details (event description, guest count, budget, date), and generate "Plan v1".
2.  **If `current_plan_json` is NOT empty:** The user is in a "refinement loop". 
    Their last message is feedback on the plan. Your job is to:
    a) Understand their feedback (e.g., "add a DJ," "book the photographer first," "what are some theme ideas?").
    b) Incorporate their changes into the plan.
    c) If they ask for suggestions, add them to the `suggestions` field.
    d) Generate an "updated_plan_json" (Plan v2, v3, etc.).

YOUR TASK:
Based on the full `chat_history`, write a natural, conversational `reply_text` to the user.
Then, generate an `updated_plan_json` that reflects all their requests *from the entire conversation*.

OUTPUT FORMAT:
You MUST respond in a pure, parsable JSON format. Do not write any other text.
Your response MUST match this exact schema:

{
  "reply_text": "This is your natural, conversational response to the user's last message.",
  "updated_plan_json": {
    "event_plan": [
      {
        "step": 1,
        "task": "Task Name (e.g., Finalize Budget)",
        "details": "Details about this task...",
        "reasoning": "Why this step is important."
      }
    ],
    "required_vendors": [
      "Caterer",
      "DJ / Musician"
    ],
    "suggestions": "Suggestions you gave the user (e.g., theme ideas)."
  }
}
"""

app = FastAPI()

async def get_llm_response(chat_history: List[ChatMessage], current_plan: str) -> Dict[str, Any]:
    """
    This is the main function that builds the prompt, calls the Gemini API,
    and parses the response.
    """
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is not configured on the server.")


    history_json = json.dumps([msg.dict() for msg in chat_history], indent=2)
    
    user_prompt = f"""
    Here is the data for your task:

    <chat_history>
    {history_json}
    </chat_history>

    <current_plan_json>
    {current_plan}
    </current_plan_json>

    Please follow your instructions and provide a JSON response.
    """
    payload = {
        "systemInstruction": {
            "parts": [{"text": SYSTEM_PROMPT}]
        },
        "contents": [
            # We add all previous messages
            *(msg.dict() for msg in chat_history),
            # And finally, we add our new user_prompt that contains the plan
            {"role": "user", "parts": [{"text": user_prompt}]}
        ],
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

@app.post("/chat", response_model=ChatResponse)
async def chat_with_agent(request: ChatRequest):
    try:
        ai_data = await get_llm_response(request.chat_history, request.current_plan_json)
        reply = ai_data.get("reply_text", "I'm sorry, I had trouble formulating a response.")
        updated_plan = json.dumps(ai_data.get("updated_plan_json", {}))
        return ChatResponse(
            reply_text=reply,
            updated_plan_json=updated_plan
        )
        
    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"Error in /chat endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

if __name__ == "__main__":
    print("Starting EventFlow AI server...")
    print("Find your API docs at http://127.0.0.1:8000/docs")
    uvicorn.run("chatbot:app", host="127.0.0.1", port=8000, reload=True)

#app.post  :
#everytime whenever user make a post request here, user will send the whole previous data in the form of an object, like AI,user,AI,user...  to AI. So AI do not have to maintain the context and user information. AI wil only send me the response for the last text which will be sent by user.

#app.post : 
#user will send all the chat history.you will give me the flow chart accordingly.If the chat history is not sufficient, then send a message in response in error.


# {
#   "chat_history": 
#     {
#       "ai": "give the description",
#       "user": "this is the description",
#       "ai": "this is the response".
#     }
#   "current_text": "i am doing an event."