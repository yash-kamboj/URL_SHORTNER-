import uvicorn
from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
import random
import string
import os
from jinja2 import Environment, DictLoader 

# --- 1. CONFIGURATION & MONGODB SETUP ---

MONGO_URI = "mongodb://localhost:27017/" 
DATABASE_NAME = "url_shortener_db"

# Initialize MongoDB variables outside try block
client = None
db = None
links_collection = None
users_collection = None
is_db_connected = False

try:
    # Attempt to connect to MongoDB
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000) # 5 second timeout
    # The ismaster command is cheap and does not require auth.
    client.admin.command('ismaster') 
    
    db = client[DATABASE_NAME]
    links_collection = db["links"]
    users_collection = db["users"]
    
    # Ensure a unique index for username
    if 'username' not in users_collection.index_information():
        users_collection.create_index("username", unique=True)
        
    is_db_connected = True
    print("SUCCESS: Connected to MongoDB.")
        
except Exception as e:
    # This print statement shows up in your terminal, helping diagnose the 500 error
    print(f"ERROR: Failed to connect to MongoDB at {MONGO_URI}. Please ensure MongoDB is running.")
    print(f"Details: {e}")
    # is_db_connected remains False

# --- 2. TEMPLATE SETUP ---

# Template content strings
DB_ERROR_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><title>Database Error</title></head>
<body style="font-family: sans-serif; text-align: center; padding-top: 50px;">
    <h1 style="color: #FF4500;">🚨 Database Connection Error 🚨</h1>
    <p style="font-size: 1.2em;">The application failed to connect to MongoDB.</p>
    <p>Please ensure your MongoDB server is running and accessible at <code>{{ mongo_uri }}</code>.</p>
    <p>Restart the application after starting MongoDB.</p>
</body>
</html>
"""

HOME_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><title>URL Shortener</title></head>
<body>
    <h1>URL Shortener</h1>
    {% if username %}
        <p>Welcome, <b>{{ username }}</b>! <a href="/logout">Logout</a></p>
        <hr>
        <h2>Shorten a URL</h2>
        <form action="/shorten" method="POST">
            Long URL: <input name="url" required style="width: 300px; padding: 5px;">
            <button type="submit">Shorten URL</button>
        </form>
    {% else %}
        <p>Please <a href="/login">Login</a> or <a href="/register">Register</a> to shorten URLs.</p>
    {% endif %}

    {% if messages %}
        {% for category, message in messages %}
            <p style="color: {% if category == 'success': %}green{% else: %}red{% endif %};">
                {{ message | safe }}
            </p>
        {% endfor %}
    {% endif %}
</body>
</html>
"""

REGISTER_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><title>Register</title></head>
<body>
    <h2>Register</h2>
    {% if messages %}
        {% for category, message in messages %}
            <p style="color: red;">{{ message }}</p>
        {% endfor %}
    {% endif %}
    <form method="POST" action="/register">
        Username: <input name="username" required><br>
        Password: <input type="password" name="password" required><br>
        <button type="submit">Register</button>
    </form>
    <p><a href="/login">Login here</a></p>
</body>
</html>
"""

LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><title>Login</title></head>
<body>
    <h2>Login</h2>
    {% if messages %}
        {% for category, message in messages %}
            <p style="color: red;">{{ message }}</p>
        {% endfor %}
    {% endif %}
    <form method="POST" action="/login">
        Username: <input name="username" required><br>
        Password: <input type="password" name="password" required><br>
        <button type="submit">Login</button>
    </form>
    <p><a href="/register">Register here</a></p>
</body>
</html>
"""

# Map template names to their string content
TEMPLATES_MAP = {
    "db_error.html": DB_ERROR_TEMPLATE,
    "home.html": HOME_TEMPLATE,
    "register.html": REGISTER_TEMPLATE,
    "login.html": LOGIN_TEMPLATE
}

# Create the Jinja Environment directly using DictLoader
jinja_env = Environment(loader=DictLoader(TEMPLATES_MAP))

# --- 3. FASTAPI SETUP & UTILS ---

app = FastAPI(title="FastAPI URL Shortener")
flash_messages = {} 

def generate_code(length=5):
    """Generates a random 5-character short code."""
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))

def set_flash_message(session_id: str, category: str, message: str):
    """Stores a message to be displayed on the next request."""
    if session_id not in flash_messages:
        flash_messages[session_id] = []
    flash_messages[session_id].append((category, message))

def get_flash_messages(session_id: str):
    """Retrieves and clears messages for the current session."""
    messages = flash_messages.get(session_id, [])
    if session_id in flash_messages:
        del flash_messages[session_id]
    return messages

# Helper to render templates
def render(request: Request, template_name: str, context: dict, status_code: int = 200):
    """Helper function to render a template using the direct Jinja environment."""
    template = jinja_env.get_template(template_name)
    
    # Context is just the dictionary of data needed by the template.
    content = template.render(context)
    return HTMLResponse(content, status_code=status_code)


# Middleware to check DB connection for ALL routes
def check_db_connection(request: Request):
    """If DB connection fails, returns a 503 HTMLResponse, otherwise returns None."""
    if not is_db_connected:
        db_error_template = jinja_env.get_template("db_error.html")
        
        # Note: We must pass 'mongo_uri' explicitly here for the error template.
        content = db_error_template.render(mongo_uri=MONGO_URI)
        return HTMLResponse(content, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return None

# --- 4. AUTHENTICATION DEPENDENCY ---

def get_current_user(request: Request):
    """Retrieves the current user's username from a cookie."""
    # This is a synchronous function (no 'async def')
    if not is_db_connected:
        return None
        
    username = request.cookies.get("username_session")
    if username:
        try:
            # We check the database to ensure the user still exists
            user_data = users_collection.find_one({"username": username})
            if user_data:
                return username
        except Exception:
            # Handle DB error during query (e.g., connection dropped)
            pass
    return None 


def get_current_user_required(request: Request, username: str = Depends(get_current_user)):
    if username is None:
        # Check if this is due to DB failure
        if not is_db_connected:
            # Let the check_db_connection handler display the 503 error
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

        # Otherwise, redirect to login page for unauthenticated access
        session_id = request.client.host
        set_flash_message(session_id, 'info', 'Please log in to access this page.')
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="Not authenticated",
            headers={"Location": "/login"}
        )
    return username


# --- 5. PAGE ROUTES ---

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, username: str = Depends(get_current_user)):
    """Main homepage: checks DB connection first."""
    
    # --- DEBUGGING PRINT ---
    print("--- DEBUG: Attempting to render HOME page ---")
    # --- DEBUGGING PRINT ---

    # Run DB check middleware explicitly for routes that don't need required auth
    db_response = check_db_connection(request)
    if db_response:
        return db_response
        
    session_id = request.client.host
    messages = get_flash_messages(session_id)
    
    # Use the simple render helper
    return render(
        request,
        "home.html", 
        {"username": username, "messages": messages}
    )

# --- Register Routes ---
@app.get("/register", response_class=HTMLResponse)
async def register_get(request: Request):
    db_response = check_db_connection(request)
    if db_response: return db_response
    
    session_id = request.client.host
    
    # FIX: Removed 'await' since get_current_user is a synchronous function
    if get_current_user(request):
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        
    messages = get_flash_messages(session_id)

    # Use the simple render helper
    return render(
        request,
        "register.html", 
        {"messages": messages}
    )

@app.post("/register", response_class=RedirectResponse, status_code=status.HTTP_303_SEE_OTHER)
async def register_post(request: Request):
    db_response = check_db_connection(request)
    if db_response: return db_response
    
    session_id = request.client.host
    
    form = await request.form()
    username = form.get('username')
    password = form.get('password')

    if users_collection.find_one({"username": username}):
        set_flash_message(session_id, 'error', 'Username already taken!')
        return RedirectResponse(url="/register", status_code=status.HTTP_303_SEE_OTHER)
    else:
        hashed_password = generate_password_hash(password)
        users_collection.insert_one({"username": username, "password": hashed_password})
        
        set_flash_message(session_id, 'success', 'Registration successful. Please log in.')
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)


# --- Login Routes ---
@app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    db_response = check_db_connection(request)
    if db_response: return db_response
    
    session_id = request.client.host
    
    # FIX: Removed 'await' since get_current_user is a synchronous function
    if get_current_user(request):
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

    messages = get_flash_messages(session_id)

    # Use the simple render helper
    return render(
        request,
        "login.html", 
        {"messages": messages}
    )

@app.post("/login")
async def login_post(request: Request):
    db_response = check_db_connection(request)
    if db_response: return db_response
    
    session_id = request.client.host
    
    form = await request.form()
    username = form.get('username')
    password = form.get('password')
    user_data = users_collection.find_one({"username": username})

    if user_data and check_password_hash(user_data['password'], password):
        response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(key="username_session", value=username, httponly=True, max_age=3600) 
        set_flash_message(session_id, 'success', 'Logged in successfully!')
        return response
    else:
        set_flash_message(session_id, 'error', 'Invalid username or password')
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("username_session")
    return response


# --- 6. API / FUNCTIONAL ROUTES ---

@app.post("/shorten", response_class=RedirectResponse, status_code=status.HTTP_303_SEE_OTHER)
async def shorten(request: Request, username: str = Depends(get_current_user_required)):
    """Creates a new short URL (protected by authentication)."""
    # DB check is handled by the required dependency
    
    session_id = request.client.host
    form = await request.form()
    long_url = form.get("url")
    
    if not long_url:
        set_flash_message(session_id, 'error', "URL parameter missing")
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    code = generate_code()
    while links_collection.find_one({'code': code}):
        code = generate_code()

    link_document = {
        'code': code,
        'long_url': long_url,
        'created_by': username
    }
    links_collection.insert_one(link_document)
    
    # We call request.url_for here where we need it, but we don't pass 'request' to the template context
    short_link = request.url_for('redirect_to_url', code=code)

    set_flash_message(session_id, 'success', f'Short URL created: <a href="{short_link}">{short_link}</a>')
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@app.get('/{code}', response_class=RedirectResponse)
async def redirect_to_url(request: Request, code: str):
    """Handles redirection from the short code to the long URL."""
    db_response = check_db_connection(request)
    if db_response: return db_response
    
    mapping = links_collection.find_one({'code': code})
    if mapping:
        return RedirectResponse(url=mapping['long_url'], status_code=status.HTTP_302_FOUND)
        
    raise HTTPException(status_code=404, detail="URL not found")


# --- 7. RUN SERVER INSTRUCTIONS ---

if __name__ == "__main__":
    uvicorn.run("fastapi_shortener:app", host="127.0.0.1", port=8000, reload=True)