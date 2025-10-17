from flask import Flask, redirect
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

@app.route('/')
def index():
    return redirect("http://168.107.19.211:5000")

if __name__ == '__main__':
    app.run(debug=True)