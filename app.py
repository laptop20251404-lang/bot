from flask import Flask
import threading
import os

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!", 200

@app.route('/health')
def health():
    return "OK", 200

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

if __name__ == "__main__":
    # فلاسک رو توی یه نخ جداگانه اجرا کن
    threading.Thread(target=run_flask, daemon=True).start()
    
    # حالا ربات اصلی رو اجرا کن
    from bot import main
    main()
