from flask import Flask, redirect, request, url_for
import random
import string
from pymongo import MongoClient


MONGO_URI = "mongodb://localhost:27017/"
DATABASE_NAME = "url_shortener_db"


client = MongoClient(MONGO_URI)
db = client[DATABASE_NAME]
links_collection = db["links"]


app = Flask(__name__)


def generate_code(length=5):
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


@app.route("/", methods=["GET"])
def home():
    return """
    <h2>URL Shortener</h2>
    <form action="/shorten" method="post">
        Long URL : <input name="url">
        <input type="submit">
    </form>
    """

@app.route("/shorten", methods=["POST"])
def shorten():
    long_url= request.form["url"]
    if not long_url:
        return "URL parameter missing", 400


    code = generate_code()
    while links_collection.find_one({'code': code}):
        code = generate_code()

    
    link_document = {
        'code': code,
        'long_url': long_url
    }
    links_collection.insert_one(link_document)


    short_link = url_for('redirect_to_url', code=code, _external=True)

    return f'Short URL: <a href="{short_link}">{short_link}</a>'


@app.route('/<code>')
def redirect_to_url(code):
    mapping = links_collection.find_one({'code': code})
    if mapping:
        return redirect(mapping['long_url'])
    
    return "URL not found", 404


if __name__== "__main__":
    app.run(debug=True)