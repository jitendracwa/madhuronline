import os
import pandas as pd
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_super_secret_key_here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///transport_ledger.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class Branch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    branch_name = db.Column(db.String(100), unique=True, nullable=False)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey('branch.id'), nullable=True)
    branch = db.relationship('Branch', backref='users')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

with app.app_context():
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        b = Branch(branch_name='CHHINDWARA')
        db.session.add(b)
        db.session.commit()
        admin_user = User(username='admin', password=generate_password_hash('admin123'), role='admin', branch_id=b.id)
        db.session.add(admin_user)
        db.session.commit()

@app.route('/')
@login_required
def index():
    return render_template('index.html', user=current_user)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('index'))
        flash('Invalid username or password')
    return '''
        <h2>Transport App Login</h2>
        <form method="POST">
            Username: <input type="text" name="username"><br><br>
            Password: <input type="password" name="password"><br><br>
            <input type="submit" value="Login">
        </form>
    '''

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/admin')
@login_required
def admin_panel():
    if current_user.role != 'admin':
        flash('Access denied!')
        return redirect(url_for('index'))
    
    users = User.query.all()
    branches = Branch.query.all()
    return render_template('admin.html', users=users, branches=branches)

@app.route('/admin/add_branch', methods=['POST'])
@login_required
def add_branch():
    if current_user.role != 'admin':
        return redirect(url_for('index'))
    
    branch_name = request.form.get('branch_name').strip().upper()
    if branch_name:
        existing = Branch.query.filter_by(branch_name=branch_name).first()
        if not existing:
            new_branch = Branch(branch_name=branch_name)
            db.session.add(new_branch)
            db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin/add_user', methods=['POST'])
@login_required
def add_user():
    if current_user.role != 'admin':
        return redirect(url_for('index'))
    
    username = request.form.get('username').strip()
    password = request.form.get('password')
    role = request.form.get('role')
    branch_id = request.form.get('branch_id')

    if username and password:
        existing = User.query.filter_by(username=username).first()
        if not existing:
            hashed_pw = generate_password_hash(password)
            new_user = User(username=username, password=hashed_pw, role=role, branch_id=branch_id if branch_id else None)
            db.session.add(new_user)
            db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if current_user.role != 'admin':
        return redirect(url_for('index'))
    
    user = User.query.get(user_id)
    if user and user.username != 'admin':
        db.session.delete(user)
        db.session.commit()
    return redirect(url_for('admin_panel'))

# --- Database Backup / Export Route ---
@app.route('/admin/export_db')
@login_required
def export_db():
    if current_user.role != 'admin':
        return redirect(url_for('index'))
    
    try:
        users_df = pd.read_sql(db.session.query(User).statement, db.bind)
        branches_df = pd.read_sql(db.session.query(Branch).statement, db.bind)
        
        backup_file = 'database_backup.xlsx'
        with pd.ExcelWriter(backup_file, engine='openpyxl') as writer:
            users_df.to_excel(writer, sheet_name='Users', index=False)
            branches_df.to_excel(writer, sheet_name='Branches', index=False)
            
        return send_file(backup_file, as_attachment=True)
    except Exception as e:
        return str(e), 500

@app.route('/api/upload', methods=['POST'])
@login_required
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    group_mode = request.form.get('groupBy', 'Origin')
    sheet_name = request.form.get('sheetName', 0)

    try:
        df = pd.read_excel(file, sheet_name=sheet_name)
        
        if group_mode == 'Origin':
            grouped = df.groupby('Origin').agg(
                col1=('Origin', 'first'),
                total_pcs=('PCs', 'sum'),
                total_weight=('Weight (Kgs)', 'sum'),
                total_amount=('Amount', 'sum'),
                total_topay=('ToPay Amount', 'sum'),
                records=('Sr.No', 'count')
            ).reset_index()
        elif group_mode == 'Destination City':
            grouped = df.groupby('Destination City').agg(
                col1=('Destination City', 'first'),
                total_pcs=('PCs', 'sum'),
                total_weight=('Weight (Kgs)', 'sum'),
                total_amount=('Amount', 'sum'),
                total_topay=('ToPay Amount', 'sum'),
                records=('Sr.No', 'count')
            ).reset_index()
        else:
            grouped = df.groupby(['Origin', 'Destination City']).agg(
                col1=('Origin', 'first'),
                col2=('Destination City', 'first'),
                total_pcs=('PCs', 'sum'),
                total_weight=('Weight (Kgs)', 'sum'),
                total_amount=('Amount', 'sum'),
                total_topay=('ToPay Amount', 'sum'),
                records=('Sr.No', 'count')
            ).reset_index()

        result = grouped.to_dict(orient='records')
        return jsonify({'success': True, 'data': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)