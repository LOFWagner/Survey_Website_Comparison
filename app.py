import os
import random
import uuid
import re
import sqlite3

try:
    import pyodbc
    AZURE_SQL_AVAILABLE = True
except ImportError:
    AZURE_SQL_AVAILABLE = False

from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', '3347b6bfe88c8c74c83f4511a49ecb7d')

# Constants
EMAILS_DIR = os.path.join(os.getcwd(), 'emails')
NUM_PAIRS = 10
DEBUG = True  # Set to False for production

# Database configuration
DB_CONFIG = {
    'debug': {
        'type': 'sqlite',
        'path': 'dev_results.db'
    },
    'production': {
        'type': 'azure_sql',
        'server': os.environ.get('AZURE_SQL_SERVER', ''),
        'database': os.environ.get('AZURE_SQL_DATABASE', ''),
        'username': os.environ.get('AZURE_SQL_USERNAME', ''),
        'password': os.environ.get('AZURE_SQL_PASSWORD', ''),
        'driver': '{ODBC Driver 17 for SQL Server}'
    }
}

def get_db_connection():
    """Get database connection based on current mode"""
    if DEBUG:
        config = DB_CONFIG['debug']
        return sqlite3.connect(config['path'])
    else:
        config = DB_CONFIG['production']
        if config['type'] == 'azure_sql' and AZURE_SQL_AVAILABLE:
            connection_string = (
                f"DRIVER={config['driver']};"
                f"SERVER={config['server']};"
                f"DATABASE={config['database']};"
                f"UID={config['username']};"
                f"PWD={config['password']}"
            )
            return pyodbc.connect(connection_string)
        else:
            raise Exception("Azure SQL configuration is not available or pyodbc is not installed")

def init_db():
    """Initialize the database with required tables"""
    conn = get_db_connection()
    c = conn.cursor()

    if isinstance(conn, sqlite3.Connection):
        # SQLite initialization
        c.execute('''
            CREATE TABLE IF NOT EXISTS responses (
                response_id TEXT PRIMARY KEY,
                pair_number INTEGER,
                email_left TEXT,
                email_right TEXT,
                selected_email TEXT,
                explanation TEXT,
                view_time INTEGER,
                demographics_age TEXT,
                demographics_experience TEXT
            )
        ''')
    elif 'pyodbc' in str(type(conn)):
        # Azure SQL Database initialization
        c.execute("""
            IF NOT EXISTS (
                SELECT * FROM INFORMATION_SCHEMA.TABLES 
                WHERE TABLE_NAME = 'responses'
            )
            BEGIN
                CREATE TABLE responses (
                    response_id NVARCHAR(36) PRIMARY KEY,
                    pair_number INT,
                    email_left NVARCHAR(MAX),
                    email_right NVARCHAR(MAX),
                    selected_email NVARCHAR(MAX),
                    explanation NVARCHAR(MAX),
                    view_time INT,
                    demographics_age NVARCHAR(50),
                    demographics_experience NVARCHAR(50)
                )
            END
        """)

    conn.commit()
    conn.close()

# Call init_db to ensure the database is initialized
init_db()

def load_email_files():
    # Get all HTML and PDF files starting with phish_, ai_ or regular_
    files = [f for f in os.listdir(EMAILS_DIR) if (f.endswith('.html') or f.endswith('.pdf')) and
             (f.startswith('phish_') or f.startswith('ai_') or f.startswith('regular_'))]
    return files

def get_email_content(filename):
    file_path = os.path.join(EMAILS_DIR, filename)

    if filename.endswith('.html'):
        with open(file_path, encoding='utf-8') as f:
            full_content = f.read()
            return extract_email_content(full_content), 'html'

    elif filename.endswith('.pdf'):
        relative_path = os.path.join('emails', filename)
        pdf_embed = f'''
        <div class="pdf-container" style="position: relative;">
            <div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; z-index: 10;"></div>
            <object data="/{relative_path}#zoom=65" type="application/pdf" width="100%" height="600px">
                <p>Unable to display PDF.</p>
            </object>
        </div>'''
        return pdf_embed, 'pdf'

@app.route('/emails/<path:filename>')
def serve_email_file(filename):
    return send_from_directory(EMAILS_DIR, filename)

def generate_random_pairs():
    # Load email files
    emails = load_email_files()

    # Check if we have enough unique emails
    if len(emails) < 2:
        raise ValueError("Not enough unique email files to create pairs")

    pairs = []
    used_pairs = set()  # Keep track of pairs we've already used

    while len(pairs) < NUM_PAIRS:
        # Randomly select two distinct emails from the list
        pair = random.sample(emails, 2)
        pair_tuple = tuple(pair)
        reverse_pair = tuple(reversed(pair))

        # Ensure we haven't used this pair before (in either order)
        if pair_tuple not in used_pairs and reverse_pair not in used_pairs:
            pairs.append(pair)
            used_pairs.add(pair_tuple)

    return pairs

def extract_email_content(html_content):
    """Extract the email container content without the surrounding HTML structure."""
    # Extract just the email-container div and its contents
    match = re.search(r'<div class="email-container">(.*?)</div>\s*</body>', html_content, re.DOTALL)
    if match:
        return '<div class="email-container">' + match.group(1) + '</div>'
    else:
        # Fallback if the expected structure isn't found
        return html_content

def save_response(response):
    """Save survey response to database"""
    conn = get_db_connection()
    c = conn.cursor()

    # Always generate a unique response ID
    response_id = str(uuid.uuid4())

    # Determine placeholders based on connection type
    if isinstance(conn, sqlite3.Connection) or 'pyodbc' in str(type(conn)):
        placeholders = '?'
    else:
        placeholders = '%s'

    # SQL query with appropriate placeholders
    query = f'''
        INSERT INTO responses (
            response_id, pair_number, email_left, email_right,
            selected_email, explanation, view_time,
            demographics_age, demographics_experience
        )
        VALUES ({', '.join([placeholders] * 9)})
    '''

    # Ensure the order of values matches the column order
    c.execute(query, (
        response_id,
        response['pair_number'],
        response['email_left'],
        response['email_right'],
        response['selected_email'],
        response['explanation'],
        response['view_time'],
        response.get('demographics_age', ''),
        response.get('demographics_experience', '')  # Using the correct key format now
    ))

    conn.commit()
    conn.close()

@app.route('/')
def index():
    # Generate and store a unique participant id in the session if not exists
    if 'participant_id' not in session:
        session['participant_id'] = str(uuid.uuid4())

    # Clear previous survey progress
    if 'survey_pairs' in session:
        del session['survey_pairs']
    if 'current_pair' in session:
        del session['current_pair']

    return render_template('index.html')

@app.route('/demographics', methods=['GET', 'POST'])
def demographics():
    # If demographics already exist, skip to instructions
    if 'demographics' in session:
        return redirect(url_for('instructions'))

    if request.method == 'POST':
        # Save demographics into session for later use
        session['demographics'] = request.form.to_dict()
        return redirect(url_for('instructions'))

    return render_template('demographics.html')

@app.route('/instructions')
def instructions():
    return render_template('instructions.html')

@app.route('/survey', methods=['GET', 'POST'])
def survey():
    if request.method == 'POST':
        # Process survey response for a single pair
        participant_id = session.get('participant_id')
        pair_number = request.form.get('pair_number')
        email_left = request.form.get('email_left')
        email_right = request.form.get('email_right')
        selected_email = request.form.get('selected_email')
        explanation = request.form.get('explanation', '')
        view_time = request.form.get('view_time')

        response = {
            'participant_id': participant_id,
            'pair_number': pair_number,
            'email_left': email_left,
            'email_right': email_right,
            'selected_email': selected_email,
            'explanation': explanation,
            'view_time': view_time
        }

        # Add demographic data to the response
        demographics = session.get('demographics', {})
        for key, value in demographics.items():
            response[f'demographics_{key}'] = value

        save_response(response)

        # Move to next pair
        current_pair = int(session.get('current_pair', 0))
        current_pair += 1
        session['current_pair'] = current_pair
        if current_pair >= NUM_PAIRS:
            return redirect(url_for('thank_you'))
        else:
            return redirect(url_for('survey'))

    # Check if survey is already completed
    current_pair = session.get('current_pair', 0)
    if current_pair >= NUM_PAIRS:
        return redirect(url_for('thank_you'))

    # On GET request: if survey not started, create random pairs and set counter
    if 'survey_pairs' not in session:
        session['survey_pairs'] = generate_random_pairs()
        session['current_pair'] = 0
        current_pair = 0

    pairs = session.get('survey_pairs')
    # Get the current pair file names
    email_left, email_right = pairs[current_pair]

    content_left, type_left = get_email_content(email_left)
    content_right, type_right = get_email_content(email_right)

    return render_template('survey.html',
                           pair_number=current_pair + 1,
                           total_pairs=NUM_PAIRS,
                           email_left=content_left,
                           email_right=content_right,
                           type_left=type_left,
                           type_right=type_right,
                           file_left=email_left,
                           file_right=email_right)

@app.route('/thank_you')
def thank_you():
    return render_template('thank_you.html')

@app.route('/reset', methods=['GET'])
def reset_survey():
    # Keep participant_id and demographics but reset survey data
    participant_id = session.get('participant_id')
    demographics = session.get('demographics')

    session.clear()

    if participant_id:
        session['participant_id'] = participant_id
    else:
        session['participant_id'] = str(uuid.uuid4())

    if demographics:
        session['demographics'] = demographics

    return redirect(url_for('instructions'))


@app.route('/admin/export_csv')
def export_csv():
    import csv
    from io import StringIO
    from flask import Response

    conn = get_db_connection()
    c = conn.cursor()

    # Query all data
    c.execute("SELECT * FROM responses")
    rows = c.fetchall()

    # Get column names
    if isinstance(conn, sqlite3.Connection):
        column_names = [description[0] for description in c.description]
    elif 'pyodbc' in str(type(conn)):
        column_names = [column[0] for column in c.description]
    else:
        column_names = [desc[0] for desc in c.description]

    # Create CSV in memory
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(column_names)
    writer.writerows(rows)

    conn.close()

    # Return CSV as a downloadable file
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=responses.csv"}
    )


if __name__ == '__main__':
    app.run(debug=True)