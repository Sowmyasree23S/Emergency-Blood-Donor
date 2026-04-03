import os
import math
import hashlib
from datetime import datetime, timedelta
from functools import wraps

import jwt
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy

# ─────────────────────────────────────────────
# App Setup
# ─────────────────────────────────────────────
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///blood_donor.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JSON_SORT_KEYS'] = False
JWT_SECRET = os.getenv('JWT_SECRET', 'changeme-in-production')

db = SQLAlchemy(app)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Clinic location (Sitaram Clinic, Coimbatore)
CLINIC = {'name': 'Sitaram Clinic', 'lat': 11.0026, 'lng': 76.9969, 'city': 'Coimbatore'}

# ─────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────
class Donor(db.Model):
    __tablename__ = 'donors'
    id           = db.Column(db.Integer, primary_key=True)
    name         = db.Column(db.String(100), nullable=False)
    blood_group  = db.Column(db.String(3),  nullable=False)
    phone        = db.Column(db.String(10),  nullable=False, unique=True)
    address      = db.Column(db.String(500), nullable=False)
    latitude     = db.Column(db.Float, nullable=False)
    longitude    = db.Column(db.Float, nullable=False)
    availability = db.Column(db.Boolean, default=True)
    last_contacted = db.Column(db.DateTime, nullable=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at   = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    id         = db.Column(db.Integer, primary_key=True)
    email      = db.Column(db.String(120), unique=True, nullable=False)
    password   = db.Column(db.String(255), nullable=False)
    role       = db.Column(db.String(20), default='user')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {'id': self.id, 'email': self.email, 'role': self.role}


# ─────────────────────────────────────────────
# Auth Helpers
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
    except Exception:
        return None

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get('Authorization', '')
        try:
            token = auth.split(' ')[1]
        except IndexError:
            return jsonify({'success': False, 'message': 'Token missing'}), 401
        decoded = verify_token(token)
        if not decoded:
            return jsonify({'success': False, 'message': 'Invalid or expired token'}), 401
        return f(decoded, *args, **kwargs)
    return decorated


# ─────────────────────────────────────────────
# Dijkstra / Distance Helpers
# ─────────────────────────────────────────────
def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dLat = math.radians(lat2 - lat1)
    dLon = math.radians(lon2 - lon1)
    a = math.sin(dLat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dLon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def travel_time(dist_km):
    return math.ceil((dist_km / 40) * 60)

def find_nearest(clinic, donors, blood_group):
    candidates = [d for d in donors if d.availability and d.blood_group == blood_group]
    if not candidates:
        return {'success': False, 'message': f'No available donors for blood group {blood_group}',
                'donor': None, 'distance': None, 'travelTime': None, 'alternatives': [], 'path': None}

    ranked = sorted(candidates, key=lambda d: haversine(clinic['lat'], clinic['lng'], d.latitude, d.longitude))
    best = ranked[0]
    dist = round(haversine(clinic['lat'], clinic['lng'], best.latitude, best.longitude), 2)

    alternatives = []
    for d in ranked[1:4]:
        ad = round(haversine(clinic['lat'], clinic['lng'], d.latitude, d.longitude), 2)
        alternatives.append({**d.to_dict(), 'distance': ad, 'travelTime': travel_time(ad)})

    return {
        'success': True, 'message': f'Found nearest donor: {best.name}',
        'donor': best.to_dict(), 'distance': dist, 'travelTime': travel_time(dist),
        'alternatives': alternatives,
        'path': {'clinic': clinic, 'donor': {'lat': best.latitude, 'lng': best.longitude}}
    }


# ─────────────────────────────────────────────
# UI Route
# ─────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')


# ─────────────────────────────────────────────
# Auth Routes
# ─────────────────────────────────────────────
@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    email, password = data.get('email'), data.get('password')
    if not email or not password:
        return jsonify({'success': False, 'message': 'Email and password required'}), 400

    # Hardcoded admin
    if email == 'admin@clinic.com' and password == 'admin123':
        return jsonify({'success': True, 'token': generate_token(0, email),
                        'user': {'id': 0, 'email': email, 'role': 'admin'}}), 200

    user = User.query.filter_by(email=email).first()
    if user and verify_password(password, user.password):
        return jsonify({'success': True, 'token': generate_token(user.id, user.email), 'user': user.to_dict()}), 200

    return jsonify({'success': False, 'message': 'Invalid email or password'}), 401


@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    email, password = data.get('email'), data.get('password')
    if not email or not password:
        return jsonify({'success': False, 'message': 'Email and password required'}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({'success': False, 'message': 'User already exists'}), 400
    try:
        user = User(email=email, password=hash_password(password))
        db.session.add(user)
        db.session.commit()
        return jsonify({'success': True, 'token': generate_token(user.id, user.email), 'user': user.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/auth/verify', methods=['GET'])
def verify():
    auth = request.headers.get('Authorization', '')
    try:
        token = auth.split(' ')[1]
        decoded = verify_token(token)
        if decoded:
            return jsonify({'success': True, 'user': decoded}), 200
    except Exception:
        pass
    return jsonify({'success': False, 'message': 'Invalid or expired token'}), 401


# ─────────────────────────────────────────────
# Donor Routes
# ─────────────────────────────────────────────
@app.route('/api/donors', methods=['GET'])
def get_donors():
    donors = Donor.query.all()
    return jsonify({'success': True, 'count': len(donors), 'donors': [d.to_dict() for d in donors]}), 200


@app.route('/api/donors/<int:donor_id>', methods=['GET'])
def get_donor(donor_id):
    donor = Donor.query.get(donor_id)
    if not donor:
        return jsonify({'success': False, 'message': 'Donor not found'}), 404
    return jsonify({'success': True, 'donor': donor.to_dict()}), 200


@app.route('/api/donors', methods=['POST'])
@token_required
def create_donor(current_user):
    data = request.get_json() or {}
    required = ['name', 'bloodGroup', 'phone', 'address', 'latitude', 'longitude']
    for f in required:
        if f not in data:
            return jsonify({'success': False, 'message': f'{f} is required'}), 400
    if Donor.query.filter_by(phone=data['phone']).first():
        return jsonify({'success': False, 'message': 'Phone number already exists'}), 400
    try:
        donor = Donor(name=data['name'], blood_group=data['bloodGroup'], phone=data['phone'],
                      address=data['address'], latitude=float(data['latitude']),
                      longitude=float(data['longitude']), availability=data.get('availability', True))
        db.session.add(donor)
        db.session.commit()
        return jsonify({'success': True, 'donor': donor.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/donors/<int:donor_id>', methods=['PUT'])
@token_required
def update_donor(current_user, donor_id):
    donor = Donor.query.get(donor_id)
    if not donor:
        return jsonify({'success': False, 'message': 'Donor not found'}), 404
    data = request.get_json() or {}
    for field, attr in [('name','name'),('bloodGroup','blood_group'),('phone','phone'),
                         ('address','address'),('availability','availability')]:
        if field in data:
            setattr(donor, attr, data[field])
    for field, attr in [('latitude','latitude'),('longitude','longitude')]:
        if field in data:
            setattr(donor, attr, float(data[field]))
    try:
        db.session.commit()
        return jsonify({'success': True, 'donor': donor.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/donors/<int:donor_id>', methods=['DELETE'])
@token_required
def delete_donor(current_user, donor_id):
    donor = Donor.query.get(donor_id)
    if not donor:
        return jsonify({'success': False, 'message': 'Donor not found'}), 404
    try:
        db.session.delete(donor)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Donor deleted'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/donors/<int:donor_id>/contact', methods=['PUT'])
def mark_contacted(donor_id):
    donor = Donor.query.get(donor_id)
    if not donor:
        return jsonify({'success': False, 'message': 'Donor not found'}), 404
    donor.last_contacted = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True, 'donor': donor.to_dict()}), 200


@app.route('/api/donors/search/nearest', methods=['POST'])
def find_nearest_donor():
    data = request.get_json() or {}
    blood_group = data.get('bloodGroup')
    if not blood_group:
        return jsonify({'success': False, 'message': 'Blood group is required'}), 400
    donors = Donor.query.all()
    result = find_nearest(CLINIC, donors, blood_group)
    if result['success'] and result['donor']:
        donor = Donor.query.get(result['donor']['id'])
        donor.last_contacted = datetime.utcnow()
        db.session.commit()
    return jsonify(result), 200 if result['success'] else 404


@app.route('/api/donors/statistics', methods=['GET'])
def get_statistics():
    total = Donor.query.count()
    available = Donor.query.filter_by(availability=True).count()
    stats = {}
    for bg in ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']:
        stats[bg] = {
            'total': Donor.query.filter_by(blood_group=bg).count(),
            'available': Donor.query.filter_by(blood_group=bg, availability=True).count()
        }
    return jsonify({'success': True, 'totalDonors': total, 'availableDonors': available, 'bloodGroupStats': stats}), 200


@app.route('/api/donors/clinic/info', methods=['GET'])
def clinic_info():
    return jsonify({'success': True, 'clinic': CLINIC}), 200


@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'OK', 'message': 'Emergency Blood Donor Finder is running'}), 200


@app.errorhandler(404)
def not_found(e):
    return jsonify({'success': False, 'message': 'Route not found'}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({'success': False, 'message': 'Internal server error'}), 500


# ─────────────────────────────────────────────
# Init DB + Seed
# ─────────────────────────────────────────────
def seed_data():
    if Donor.query.count() > 0:
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
    print("✓ Seeded sample donors")


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        seed_data()
    port = int(os.getenv('PORT', 5000))
    print(f"🩸 Starting Emergency Blood Donor Finder on port {port}")
    app.run(host='0.0.0.0', port=port, debug=os.getenv('FLASK_DEBUG', 'false').lower() == 'true')
