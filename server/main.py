from flask import Flask, send_from_directory, request, jsonify
import logging
from logging.handlers import RotatingFileHandler
import os
from auto_note_rebuild import UpdateThread

app = Flask(__name__)

PROJECT_FOLDER = r"C:\Users\Administrator\Desktop\servers\NotesEggpoker"
# folder to monitor for changes
SRC_FOLDER = r"C:\Users\Administrator\Dropbox\NOTES\obsidian\Coding" 
# folder for staging the content
DST_FOLDER = r"C:\Users\Administrator\Desktop\servers\NotesEggpoker\content"
# folder for publishing the content
ROOT_FOLDER = r"C:\Users\Administrator\Desktop\servers\NotesEggpoker\public"
LOG_FILE = r"C:\Users\Administrator\Desktop\servers\logs\NotesServer.log"

# Create a rotating file handler
handler = RotatingFileHandler(LOG_FILE, maxBytes=10000, backupCount=3)

# Set the logging level and format
handler.setLevel(logging.INFO)
formatter = logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
)
handler.setFormatter(formatter)

# Add the handler to the Flask app's logger
app.logger.addHandler(handler)


rebuild_thread = UpdateThread(
    logger=app.logger,
    project_dir=PROJECT_FOLDER,
    dir_to_watch=SRC_FOLDER,
    dst_dir=DST_FOLDER,
    interval=10,
    rebuild_on_start=True,
)
rebuild_thread.daemon = True
rebuild_thread.start()

@app.before_request
def check_rebuild_status():
    if rebuild_thread.is_rebuilding:
        app.logger.warning("Service Unavailable: Rebuild in progress")
        return jsonify({"error": "Service Unavailable - rebuilding in progress"}), 503

@app.route('/')
@app.route('/<path:filename>')
def serve_static(filename: str | None = None):
    client_ip = request.remote_addr
    user_agent = request.user_agent.string
    app.logger.info(f"Client {client_ip} requested {filename} using {request.method}. User-Agent: {user_agent}")
    
    if not filename:
        folder_path = ROOT_FOLDER
        file_path = "index.html"
    else:
        folder_path = ROOT_FOLDER
        file_path = filename
        _, ext = os.path.splitext(filename)
        if not ext:
            test_paths = [
                (ROOT_FOLDER, filename + '.html'),
                (os.path.join(ROOT_FOLDER, filename), "index.html")
            ]

            for test_path in test_paths:
                app.logger.info(f"trying {test_path} ...")
                if os.path.exists(os.path.join(*test_path)):
                    folder_path, file_path = test_path
                    break
                app.logger.info("not found")

    full_path = os.path.join(folder_path, file_path)
    if not os.path.exists(full_path):
        app.logger.warning(f"File not found: {full_path} (404 returned)")
        return send_from_directory(ROOT_FOLDER, '404.html'), 404

    app.logger.info(f"Serving file: {full_path}")
    return send_from_directory(folder_path, file_path)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8081)
