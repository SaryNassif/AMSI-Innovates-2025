from flask import Flask, render_template, url_for, redirect,flash,request,make_response
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
from flask_migrate import Migrate
from collections import Counter
from sqlalchemy import func
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
import io

load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SECRET_KEY'] = 'thisisasecretkey'

bcrypt=Bcrypt(app)
db = SQLAlchemy(app)
migrate = Migrate(app, db)  

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

def validate_location(location):
    """
    Uses GPT-4 to check if a location is somewhat valid.
    - Allows partial matches (e.g., "Mall of Emirates" instead of full address)
    - Rejects obvious gibberish like "adfhjdshfjds"
    """
    client = OpenAI(api_key=api_key)

    prompt = f"""
    The user has provided this as a location: "{location}".
    - If it's **clearly nonsense** (random letters, fake places), say "INVALID".
    - If it's **somewhat valid** (a known place, community, or area but not perfect), say "LIKELY VALID".
    - If it's **fully correct** (a real place), say "VALID".
    - Don't add extra details, just return one of these: "INVALID", "LIKELY VALID", or "VALID".
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    verdict = response.choices[0].message.content.strip()
    return verdict in ["VALID", "LIKELY VALID"]  # ✅ Allows likely valid locations

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
    community = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    ai_response = db.Column(db.Text)
    severity = db.Column(db.Integer, nullable=False)

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
    location = request.form['location'].strip()
    community = request.form['community'].strip()
    description = request.form['description'].strip()

    # 🔹 STEP 1: IMPROVED LOCATION VALIDATION (MORE FORGIVING)
    if not validate_location(location):
        return render_template('report.html', error="The location provided seems too vague or incorrect. Try using a more recognizable place.")

    # 🔹 STEP 2: IMPROVED DESCRIPTION VALIDATION
    client = OpenAI(api_key=api_key)
    validation_prompt = f"""
    You are an AI that verifies if a pollution report is **logically valid** and describes a real issue.

    Given the following report description:
    - "{description}"

    **Requirements:**
    - If the description is **clearly nonsense, gibberish, or not about pollution**, return `"INVALID - Reason: [explain why]"`
    - If it **describes a real pollution problem**, return `"VALID"`
    - If it's **too short or unclear**, return `"INVALID - Reason: Too short or unclear"`

    **Response (ONLY return "VALID" or "INVALID - Reason: [reason]")**
    """

    description_validation = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": validation_prompt}]
    )

    description_validity = description_validation.choices[0].message.content.strip()

    if description_validity.startswith("INVALID"):
        reason = description_validity.replace("INVALID - Reason: ", "")  # Extract the reason
        return render_template('report.html', error=f"Invalid description: {reason}")

    # 🔹 STEP 3: SEVERITY RANKING (FORCE NUMBER OUTPUT)
    severity_prompt = f"""
    Rank this pollution report's severity on a scale of **1-10** (Only return a number).

    **Scale:**
    - **1-3:** Minor (littering, minor air pollution)
    - **4-6:** Moderate (waste dumping, air pollution affecting people)
    - **7-10:** Severe (toxic waste, hazardous spills, major threats to human health)

    **Description:** "{description}"

    **Response (ONLY a number 1-10, no extra text):**
    """

    severity_response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": severity_prompt}]
    )

    severity_score = severity_response.choices[0].message.content.strip()

    try:
        severity_score = int(severity_score)
        if severity_score < 1 or severity_score > 10:
            severity_score = 5  # Default if GPT gives invalid score
    except ValueError:
        severity_score = 5  # Default if GPT fails

    # 🔹 STEP 4: GENERATE POLLUTION REPORT
    report_prompt = f"""
    **Pollution Report:**
    - **📍 Location:** {location}
    - **🏙️ Community:** {community}
    - **🔥 Severity (1-10):** {severity_score}
    - **📝 Description:** {description}

    **Additional AI Analysis:**
    - **Possible Causes:** Identify key causes of this pollution.
    - **Impact on Environment & Public Health:** Explain why this is a problem.
    - **Recommended Actions:** Suggest solutions that authorities should take.

    **Ensure the response is formal, structured, and between 100-150 words.**
    """

    report_response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": report_prompt}]
    )

    gpt_response = report_response.choices[0].message.content

    # 🔹 STEP 5: SAVE TO DATABASE
    new_report = PollutionReport(location=location, community=community, description=description, ai_response=gpt_response, severity=severity_score)
    db.session.add(new_report)
    db.session.commit()

    return render_template('report.html', gpt_response=gpt_response)

@app.route('/download_report/<int:report_id>')
@login_required
def download_report(report_id):
    report = PollutionReport.query.get_or_404(report_id)

    # Create an in-memory buffer
    buffer = io.BytesIO()
    pdf = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []

    # Styles
    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    title_style.alignment = 1  # Centered text

    header_style = ParagraphStyle(
        "HeaderStyle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12,
        textColor=colors.black,
        spaceAfter=6
    )

    normal_style = styles["Normal"]

    # Title
    elements.append(Paragraph("Pollution Report", title_style))
    elements.append(Spacer(1, 12))  # Spacer for better formatting

    # Report Details
    elements.append(Paragraph("<b> Location:</b> " + report.location, header_style))
    elements.append(Paragraph("<b> Community:</b> " + report.community, header_style))
    elements.append(Paragraph("<b> Severity (1-10):</b> " + str(report.severity), header_style))
    elements.append(Spacer(1, 12))  # Spacer for separation

    # User Description
    elements.append(Paragraph("<b> Description:</b> " + report.description, normal_style))
    elements.append(Spacer(1, 12))

    # AI Report (Formatted)
    elements.append(Paragraph("<b> AI Report:</b>", header_style))
    elements.append(Paragraph(report.ai_response, normal_style))

    # Build the PDF
    pdf.build(elements)

    buffer.seek(0)

    # Create response
    response = make_response(buffer.read())
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = f"attachment; filename=Pollution_Report_{report_id}.pdf"

    return response

@app.route('/delete_report/<int:report_id>', methods=['POST'])
@login_required
def delete_report(report_id):
    report = PollutionReport.query.get_or_404(report_id)

    # Only allow the user to delete their own reports
    db.session.delete(report)
    db.session.commit()

    return redirect(url_for('profile'))

@app.route('/community_reports/<community>')
@login_required
def community_reports(community):
    reports = PollutionReport.query.filter_by(community=community).all()
    return render_template('community_reports.html', community=community, reports=reports)


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