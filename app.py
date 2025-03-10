import os
import random
import csv
import uuid
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Replace with a secure secret key

# Constants
EMAILS_DIR = os.path.join(os.getcwd(), 'emails')
NUM_PAIRS = 10
RESULTS_FILE = 'results.csv'


def load_email_files():
    # Get all HTML files starting with phish_, ai_ or regular_
    files = [f for f in os.listdir(EMAILS_DIR) if f.endswith('.html') and
             (f.startswith('phish_') or f.startswith('ai_') or f.startswith('regular_'))]
    return files


def generate_random_pairs():
    # Load email files
    emails = load_email_files()
    pairs = []
    for _ in range(NUM_PAIRS):
        # Randomly select two distinct emails from the list
        pair = random.sample(emails, 2)
        pairs.append(pair)
    return pairs


def save_response(response):
    # Append the response as a new row in the CSV file
    fieldnames = ['participant_id', 'timestamp', 'pair_number', 'email_left', 'email_right', 'selected_email',
                  'explanation', 'view_time']
    file_exists = os.path.isfile(RESULTS_FILE)
    with open(RESULTS_FILE, 'a', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(response)


@app.route('/')
def index():
    # Introduction/Consent page
    # Generate and store a unique participant id in the session
    if 'participant_id' not in session:
        session['participant_id'] = str(uuid.uuid4())
    return render_template('index.html')


@app.route('/demographics', methods=['GET', 'POST'])
def demographics():
    if request.method == 'POST':
        # Save demographics into session for later use (or store in DB)
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
            'timestamp': datetime.utcnow().isoformat(),
            'pair_number': pair_number,
            'email_left': email_left,
            'email_right': email_right,
            'selected_email': selected_email,
            'explanation': explanation,
            'view_time': view_time
        }
        save_response(response)

        # Move to next pair
        current_pair = int(session.get('current_pair', 0))
        current_pair += 1
        session['current_pair'] = current_pair
        if current_pair >= NUM_PAIRS:
            return redirect(url_for('thank_you'))
        else:
            return redirect(url_for('survey'))

    # On GET request: if survey not started, create random pairs and set counter
    if 'survey_pairs' not in session:
        session['survey_pairs'] = generate_random_pairs()
        session['current_pair'] = 0

    current_pair = session.get('current_pair', 0)
    pairs = session.get('survey_pairs')
    # Get the current pair file names
    email_left, email_right = pairs[current_pair]

    # Load the actual HTML content for each email
    with open(os.path.join(EMAILS_DIR, email_left), encoding='utf-8') as f:
        content_left = f.read()
    with open(os.path.join(EMAILS_DIR, email_right), encoding='utf-8') as f:
        content_right = f.read()

    return render_template('survey.html',
                           pair_number=current_pair + 1,
                           total_pairs=NUM_PAIRS,
                           email_left=content_left,
                           email_right=content_right,
                           file_left=email_left,
                           file_right=email_right)


@app.route('/thank_you')
def thank_you():
    return render_template('thank_you.html')


if __name__ == '__main__':
    app.run(debug=True)
