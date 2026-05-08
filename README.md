# Netflix Clone + Python Backend

This project now includes a Python backend using Flask and SQLite.

## Features added

- `POST /api/signup` to create a new user
- `POST /api/signin` to authenticate a user
- `GET /api/movies` to fetch legal full-length movie records from Internet Archive
- `GET /api/health` to verify server status
- Password hashing with Werkzeug
- SQLite persistence in `backend/users.db`
- Post-login browse screen at `/browse` with dynamic movie cards
- Search bar + full-movie filter + footer on browse page
- Recommendations based on each user's search history (stored in browser localStorage)
- Every title has a Netflix-style `Play` modal that starts the full movie directly
- `GET /api/full-movie?identifier=...&title=...` fetches legal full-movie streams from Internet Archive
- Optional TMDB metadata enrichment for posters, ratings, years, and summaries using `TMDB_API_KEY`

## Run locally

1. Create and activate a virtual environment:
   - Windows PowerShell:
     - `python -m venv .venv`
     - `.venv\Scripts\Activate.ps1`
2. Install dependencies:
   - `pip install -r requirements.txt`
3. Optional: enable TMDB metadata:
   - PowerShell: `$env:TMDB_API_KEY="your_tmdb_api_key"`
4. Start backend:
   - `python backend/app.py`
5. Open:
   - `http://127.0.0.1:5000`

Use the existing `signup.html` and `signin.html` pages to create/login.
After sign in, you will be redirected to `/browse` where movies are loaded from the API.
