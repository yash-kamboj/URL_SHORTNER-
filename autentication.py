from flask import Flask, redirect, request, url_for, render_template_string, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
import random
import string

MONGO_URI = "mongodb://localhost:27017/"
DATABASE_NAME = "url_shortener_db"

client = MongoClient(MONGO_URI)
db = client[DATABASE_NAME]
links_collection = db["links"]
users_collection = db["users"]

app = Flask(__name__)
app.config['SECRET_KEY'] = 'a_secure_random_key_for_sessions'

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' 
login_manager.login_message_category = 'info'


class User(UserMixin):
    def __init__(self, username, password_hash=None):
        self.username = username
        self.password_hash = password_hash
    def get_id(self):
        return self.username

@login_manager.user_loader
def load_user(user_id):
    user_data = users_collection.find_one({"username": user_id})
    if user_data:
        return User(user_data['username'], user_data['password'])
    return None

def generate_code(length=5):
    """Generates a random 5-character short code."""
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if users_collection.find_one({"username": username}):
            flash('Username already taken!', 'error')
        else:
            hashed_password = generate_password_hash(password)
            users_collection.insert_one({"username": username, "password": hashed_password})
            flash('Registration successful. Please log in.', 'success')
            return redirect(url_for('login'))

    return render_template_string("""
        <h2>Register</h2>
        {% for category, message in get_flashed_messages(with_categories=true): %}
            <p style="color: red;">{{ message }}</p>
        {% endfor %}
        <form method="POST">
            Username: <input name="username" required><br>
            Password: <input type="password" name="password" required><br>
            <input type="submit" value="Register">
        </form>
        <p><a href="{{ url_for('login') }}">Login here</a></p>
    """)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user_data = users_collection.find_one({"username": username})

        if user_data and check_password_hash(user_data['password'], password):
            user = load_user(username)
            login_user(user)
            flash('Logged in successfully!', 'success')
            return redirect(url_for('home'))
        else:
            flash('Invalid username or password', 'error')

    return render_template_string("""
        <h2>Login</h2>
        {% for category, message in get_flashed_messages(with_categories=true): %}
            <p style="color: red;">{{ message }}</p>
        {% endfor %}
        <form method="POST">
            Username: <input name="username" required><br>
            Password: <input type="password" name="password" required><br>
            <input type="submit" value="Login">
        </form>
        <p><a href="{{ url_for('register') }}">Register here</a></p>
    """)

@app.route('/logout')
@login_required 
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('home'))


@app.route("/", methods=["GET"])
def home():
    return render_template_string("""
        <h1>URL Shortener</h1>
        <hr>
        
        {% if current_user.is_authenticated: %}
            <p>Welcome, <b>{{ current_user.username }}</b>! <a href="{{ url_for('logout') }}">Logout</a></p>
            
            <h2>Shorten a URL</h2>
            <form action="{{ url_for('shorten') }}" method="POST">
                Long URL: <input name="url" required>
                <input type="submit" value="Shorten URL">
            </form>
        {% else: %}
            <p>Please <a href="{{ url_for('login') }}">Login</a> or <a href="{{ url_for('register') }}">Register</a> to shorten URLs.</p>
        {% endif %}

        {% for category, message in get_flashed_messages(with_categories=true): %}
            <p style="color: {% if category == 'success': %}green{% else: %}red{% endif %};">
                <!-- Use the safe filter to render HTML links from flash() -->
                {{ message | safe }}
            </p>
        {% endfor %}
    """)

@app.route("/shorten", methods=["POST"])
@login_required
def shorten():
    long_url = request.form.get("url")
    if not long_url:
        flash("URL parameter missing", 'error')
        return redirect(url_for('home'))

    code = generate_code()
    while links_collection.find_one({'code': code}):
        code = generate_code()

    link_document = {
        'code': code,
        'long_url': long_url,
        'created_by': current_user.username 
    }
    links_collection.insert_one(link_document)
    
    short_link = url_for('redirect_to_url', code=code, _external=True)

    
    flash(f'Short URL created: <a href="{short_link}">{short_link}</a>', 'success')
    return redirect(url_for('home'))


@app.route('/<code>')
def redirect_to_url(code):
    mapping = links_collection.find_one({'code': code})
    if mapping:
        return redirect(mapping['long_url'])
        
    return "URL not found", 404


if __name__== "__main__":

    app.run(debug=True)
