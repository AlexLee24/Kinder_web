from flask import Flask, render_template

app = Flask(__name__, static_folder="static")
app.secret_key = 'test'

@app.route('/')
def maintenance():
    return render_template('maintenance.html', current_path='/')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80, debug=True)
