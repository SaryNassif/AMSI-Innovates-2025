from flask import Flask, render_template, url_for, redirect,flash,request
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin,login_user, LoginManager, login_required, logout_user, current_user
from flask_wtf import FlaskForm
from wtforms import StringField,PasswordField,SubmitField
from wtforms.validators import InputRequired, Length, ValidationError
from flask_bcrypt import Bcrypt
from openai import OpenAI
import os
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import re
from collections import Counter
from sqlalchemy import func

load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")
print(api_key)

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SECRET_KEY'] = 'thisisasecretkey'

bcrypt=Bcrypt(app)
db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def no_spaces(form, field):
    if ' ' in field.data:
        raise ValidationError("Spaces are not allowed.")

def validate_description(description):
    """
    Checks if the user input is meaningful.
    - Rejects input with excessive random letters or short nonsense.
    - Allows real words and meaningful sentences.
    """

    # Check if the description is too short
    if len(description) < 10:
        return False

    # Reject inputs that are just gibberish (e.g., "ajshdjkashd")
    if re.fullmatch(r"[a-zA-Z]{8,}", description):
        return False

    # Allow only descriptions with proper words (at least 3 words)
    words = description.split()
    if len(words) < 3:
        return False

    return True


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), nullable=False, unique=True)
    password = db.Column(db.String(80), nullable=False)

class RegisterForm(FlaskForm):
    username = StringField(validators=[InputRequired(), Length(min=4, max=20),no_spaces], render_kw={"placeholder": "Username"})
    password = PasswordField(validators=[InputRequired(), Length(min=8, max=20),no_spaces], render_kw={"placeholder": "Password"})
    submit = SubmitField('Register')

    def validate_username(self, username):
        existing_user_username = User.query.filter_by(
            username=username.data).first()
        if existing_user_username:
            raise ValidationError(
                'That username already exists. Please choose a different one.')

class LoginForm(FlaskForm):
    username = StringField(validators=[InputRequired(), Length(min=4, max=20)], render_kw={"placeholder": "Username"})
    password = PasswordField(validators=[InputRequired(), Length(min=8, max=20)], render_kw={"placeholder": "Password"})
    submit = SubmitField('Login')

class PollutionReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    location = db.Column(db.String(200), nullable=False)
    community = db.Column(db.String(100), nullable=False)  # ADD THIS
    description = db.Column(db.Text, nullable=False)
    ai_response = db.Column(db.Text)

@app.route('/')
def home():
    # Query database to count reports per community
    community_reports = (
        db.session.query(PollutionReport.community, func.count(PollutionReport.id))
        .group_by(PollutionReport.community)
        .all()
    )
    # Convert results into a dictionary { "Community Name": Count }
    community_stats = {community: count for community, count in community_reports}

    return render_template('index.html', community_stats=community_stats)

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/report',methods=["GET"])
@login_required
def report():
    return render_template('report.html')

@app.route('/process_report', methods=['POST'])
@login_required
def process_report():
    location = request.form['location']
    community = request.form['community']
    description = request.form['description'].strip()

    # Validate user input
    if not validate_description(description):
        return render_template('report.html', error="Your description must be meaningful and not just random characters.")

    client = OpenAI(api_key=api_key)

    prompt = f"""
    You are an AI system assisting in documenting environmental pollution reports for government authorities. 
    Convert the given user input into a **formal report** with the following structure:

    ### **Pollution Report**
    - **Location:** {location}
    - **Community:** {community}
    - **Description of Issue:** {description}
    - **Possible Causes:** Provide possible causes of this pollution.
    - **Impact on Environment & Public Health:** Explain how this affects people and the environment.
    - **Recommended Actions:** Suggest actions that should be taken by authorities.

    Ensure the report is **formal, structured, and actionable, concise and between 100-150 words**.
    """

    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    gpt_response = completion.choices[0].message.content

    # Save structured report into database
    new_report = PollutionReport(location=location, community=community, description=description, ai_response=gpt_response)
    db.session.add(new_report)
    db.session.commit()

    return render_template('report.html', gpt_response=gpt_response)
@app.route('/delete_report/<int:report_id>', methods=['POST'])
@login_required
def delete_report(report_id):
    report = PollutionReport.query.get_or_404(report_id)

    # Only allow the user to delete their own reports
    db.session.delete(report)
    db.session.commit()

    return redirect(url_for('profile'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    error = None  # Initialize error variable

    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        
        if user:
            if bcrypt.check_password_hash(user.password, form.password.data):
                login_user(user)
                return redirect(url_for('profile'))
            else:
                error = "Invalid password. Please try again."
        else:
            error = "Username not found. Please register first."

    return render_template('login.html', form=form, error=error)

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user:
            if bcrypt.check_password_hash(user.password, form.password.data):
                login_user(user)
                return redirect(url_for('profile'))
    return render_template('login.html',form=form)

@app.route('/profile')
@login_required
def profile():
    reports = PollutionReport.query.all()
    return render_template('profile.html',reports=reports)

@app.route('/logout', methods=['GET', 'POST'])
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/register', methods=['GET','POST'])
def register():
    form = RegisterForm()

    if form.validate_on_submit():
        hashed_password = bcrypt.generate_password_hash(form.password.data)
        new_user = User(username=form.username.data, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html',form=form)

if __name__ == '__main__':
    app.run(debug=True)