from flask import Flask, render_template
from flask_sock import Sock

app = Flask(__name__)
sock = Sock(app)


@app.get("/")
def home():
    return render_template("index.html")


@sock.route("/ws")
def echo(ws):
    while True:
        message = ws.receive()
        ws.send(message)
