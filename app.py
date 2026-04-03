import os
import math
import hashlib
import jwt
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy

# ─────────────────────────────────────────────
# 1. App Configuration
# ─────────────────────────────────────────────
app = Flask(__name__)

# Database URL Handling (SQLAlchemy 1.4+ needs 'postgresql://' not 'postgres://')
DB_URL = os.getenv(
    'DATABASE_URL', 
    'postgresql://blood_donor_db_al97_user:q4IXPrkgVvQgg3D85H5w6Rba0rtOACnp@dpg-d77uu6ia214c73dkd1fg-a/blood_donor_db_al97'
)
if DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = DB_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JSON_SORT_KEYS'] = False
JWT_SECRET = os.getenv('JWT_SECRET', 'emergency-secret-key-123')

db = SQLAlchemy(app)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Clinic location (Sitaram Clinic, Coimbatore)
CLINIC = {'name': 'Sitaram Clinic', 'lat': 11.0026, 'lng': 76.9969, 'city': 'Coimbatore'}

# ─────────────────────────────────────────────
# 2. Database Models
# ─────────────────────────────────────────────
class Donor(db.Model):
    __tablename__ = 'donors'
    id             = db.Column(db.Integer, primary_key=True)
    name           = db.Column(db.String(100), nullable=False)
    blood_group    = db.Column(db.String(3),   nullable=False)
    phone          = db.Column(db.String(15),  nullable=False, unique=True)
    address        = db.Column(db.String(500), nullable=False)
    latitude       = db.Column(db.Float, nullable=False)
    longitude      = db.Column(db.Float, nullable=False)
    availability   = db.Column(db.Boolean, default=True)
    last_contacted = db.Column(db.DateTime, nullable=True)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at     = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id, 'name': self.name, 'bloodGroup': self.blood_group,
            'phone': self.phone, 'address': self.address,
            'latitude': self.latitude, 'longitude': self.longitude,
            'availability': self.availability,
            'lastContacted': self.last_contacted.isoformat() if self.last_contacted else None,
            'createdAt': self.created_at.isoformat(),
        }

class User(db.Model):
    __tablename__ = 'users'
    id          = db.Column(db.Integer, primary_key=True)
    email       = db.Column(db.String(120), unique=True, nullable=False)
    password    = db.Column(db.String(255), nullable=False)
    role        = db.Column(db.String(20), default='user')
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {'id': self.id, 'email': self.email, 'role': self.role}

# ─────────────────────────────────────────────
# 3. Database Initialization & Seeding
# ─────────────────────────────────────────────
def seed_data():
    if Donor.query.first() is not None:
        return
    
    sample_donors = [
        {'name': 'Arjun Kumar',   'blood_group': 'O+', 'phone': '9876543210', 'address': 'RS Puram, Coimbatore',      'latitude': 11.0076, 'longitude': 76.9543},
        {'name': 'Priya Sharma',  'blood_group': 'A+', 'phone': '9876543211', 'address': 'Gandhipuram, Coimbatore',   'latitude': 11.0168, 'longitude': 76.9558},
        {'name': 'Ravi Shankar',  'blood_group': 'B+', 'phone': '9876543212', 'address': 'Peelamedu, Coimbatore',     'latitude': 11.0276, 'longitude': 77.0036},
        {'name': 'Meera Nair',    'blood_group': 'AB+','phone': '9876543213', 'address': 'Saibaba Colony, Coimbatore','latitude': 11.0218, 'longitude': 76.9699},
        {'name': 'Karan Singh',   'blood_group': 'O-', 'phone': '9876543214', 'address': 'Singanallur, Coimbatore',   'latitude': 10.9985, 'longitude': 77.0249},
        {'name': 'Deepa Menon',   'blood_group': 'A-', 'phone': '9876543215', 'address': 'Vadavalli, Coimbatore',     'latitude': 11.0134, 'longitude': 76.9204},
        {'name': 'Suresh Babu',   'blood_group': 'B-', 'phone': '9876543216', 'address': 'Ukkadam, Coimbatore',       'latitude': 10.9862, 'longitude': 76.9694},
        {'name': 'Anita Patel',   'blood_group': 'AB-','phone': '9876543217', 'address': 'Kuniyamuthur, Coimbatore',  'latitude': 10.9756, 'longitude': 76.9564},
    ]
    for d in sample_donors:
        db.session.add(Donor(**d))
    db.session.commit()
    print("✅ Database Seeded Successfully")

# Initialize tables inside the app context (CRITICAL for Render/Postgres)
with app.app_context():
    db.create_all()
    seed_data()

# ─────────────────────────────────────────────
# 4. Auth Helpers & Decorators
# ─────────────────────────────────────────────
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password, hashed):
    return hash_password(password) == hashed

def generate_token(user_id, email):
    payload = {
        'userId': user_id, 'email': email,
        'iat': datetime.utcnow(),
        'exp': datetime.utcnow() + timedelta(days=7)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm='HS256')

def verify_token(token):
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
    except:
        return None

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get('Authorization', '')
        try:
            token = auth.split(' ')[1]
        except:
            return jsonify({'success': False, 'message': 'Token missing'}), 401
        decoded = verify_token(token)
        if not decoded:
            return jsonify({'success': False, 'message': 'Invalid token'}), 401
        return f(decoded, *args, **kwargs)
    return decorated

# ─────────────────────────────────────────────
# 5. Logic & Distance Helpers
# ─────────────────────────────────────────────
def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dLat, dLon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dLat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dLon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def find_nearest(clinic, donors, blood_group):
    candidates = [d for d in donors if d.availability and d.blood_group == blood_group]
    if not candidates:
        return {'success': False, 'message': f'No available {blood_group} donors'}

    ranked = sorted(candidates, key=lambda d: haversine(clinic['lat'], clinic['lng'], d.latitude, d.longitude))
    best = ranked[0]
    dist = round(haversine(clinic['lat'], clinic['lng'], best.latitude, best.longitude), 2)
    
    return {
        'success': True,
        'donor': best.to_dict(),
        'distance': dist,
        'travelTime': math.ceil((dist / 40) * 60),
        'alternatives': [{**d.to_dict(), 'distance': round(haversine(clinic['lat'], clinic['lng'], d.latitude, d.longitude), 2)} for d in ranked[1:4]]
    }

# ─────────────────────────────────────────────
# 6. API Routes
# ─────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    email, password = data.get('email'), data.get('password')
    if email == 'admin@clinic.com' and password == 'admin123':
        return jsonify({'success': True, 'token': generate_token(0, email), 'user': {'email': email, 'role': 'admin'}})
    user = User.query.filter_by(email=email).first()
    if user and verify_password(password, user.password):
        return jsonify({'success': True, 'token': generate_token(user.id, user.email), 'user': user.to_dict()})
    return jsonify({'success': False, 'message': 'Invalid credentials'}), 401

@app.route('/api/donors', methods=['GET'])
def get_donors():
    donors = Donor.query.all()
    return jsonify({'success': True, 'donors': [d.to_dict() for d in donors]})

@app.route('/api/donors/search/nearest', methods=['POST'])
def find_nearest_donor_api():
    data = request.get_json() or {}
    blood_group = data.get('bloodGroup')
    if not blood_group:
        return jsonify({'success': False, 'message': 'Blood group required'}), 400
    donors = Donor.query.all()
    result = find_nearest(CLINIC, donors, blood_group)
    return jsonify(result)

@app.route('/api/donors/statistics', methods=['GET'])
def get_statistics():
    stats = {}
    for bg in ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']:
        stats[bg] = {
            'total': Donor.query.filter_by(blood_group=bg).count(),
            'available': Donor.query.filter_by(blood_group=bg, availability=True).count()
        }
    return jsonify({'success': True, 'totalDonors': Donor.query.count(), 'bloodGroupStats': stats})

@app.route('/api/health')
def health():
    return jsonify({'status': 'OK'})

# ─────────────────────────────────────────────
# 7. Start Server
# ─────────────────────────────────────────────
if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)