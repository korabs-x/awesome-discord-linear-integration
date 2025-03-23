from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
import os
from dotenv import load_dotenv
import requests
import uvicorn

# Load environment variables
load_dotenv(override=True)

LINEAR_CLIENT_ID = os.getenv("LINEAR_CLIENT_ID")
LINEAR_CLIENT_SECRET = os.getenv("LINEAR_CLIENT_SECRET")
REDIRECT_URI = "http://localhost:3000/callback"

app = FastAPI()


@app.get("/")
async def root():
    """Generate Linear OAuth authorization URL."""
    params = {
        "client_id": LINEAR_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "read,write,issues:create",
        "actor": "application",
    }
    auth_url = "https://linear.app/oauth/authorize"
    return RedirectResponse(
        url=f"{auth_url}?{'&'.join(f'{k}={v}' for k, v in params.items())}"
    )


@app.get("/callback")
async def oauth_callback(code: str):
    """Handle OAuth callback and exchange code for token."""
    try:
        response = requests.post(
            "https://api.linear.app/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": LINEAR_CLIENT_ID,
                "client_secret": LINEAR_CLIENT_SECRET,
                "code": code,
                "redirect_uri": REDIRECT_URI,
            },
        )
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to get access token")

        token_data = response.json()
        # In a real application, you'd want to securely store this token
        # For now, we'll just display it
        return {
            "message": "Authorization successful! Copy this access token to your .env file:",
            "access_token": token_data["access_token"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3000)
