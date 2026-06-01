import os
import json
import time
from datetime import datetime
import requests
from flask import Flask, redirect, request, render_template, url_for, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)

CLIENT_ID = os.getenv('STRAVA_CLIENT_ID')
CLIENT_SECRET = os.getenv('STRAVA_CLIENT_SECRET')
REDIRECT_URI = os.getenv('REDIRECT_URI', 'http://localhost:5000/callback')
TOKENS_FILE = 'tokens.json'
CACHE_DIR = 'cache'

os.makedirs(CACHE_DIR, exist_ok=True)


def load_tokens():
    if os.path.exists(TOKENS_FILE):
        with open(TOKENS_FILE) as f:
            return json.load(f)
    return None


def save_tokens(tokens):
    with open(TOKENS_FILE, 'w') as f:
        json.dump(tokens, f)


def get_valid_token():
    tokens = load_tokens()
    if not tokens:
        return None
    if time.time() > tokens.get('expires_at', 0) - 60:
        r = requests.post('https://www.strava.com/oauth/token', data={
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'grant_type': 'refresh_token',
            'refresh_token': tokens['refresh_token']
        })
        if r.ok:
            new_tokens = r.json()
            save_tokens(new_tokens)
            return new_tokens['access_token']
        return None
    return tokens['access_token']


def get_all_activities(token):
    activities = []
    page = 1
    while True:
        r = requests.get(
            'https://www.strava.com/api/v3/athlete/activities',
            headers={'Authorization': f'Bearer {token}'},
            params={'per_page': 100, 'page': page}
        )
        if not r.ok:
            break
        data = r.json()
        if not data:
            break
        activities.extend(data)
        page += 1
    return activities


def fmt_time(seconds):
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}h {m:02d}m" if h > 0 else f"{m}m"


def fmt_pace(seconds, distance_m):
    if not distance_m:
        return '-'
    s = seconds / (distance_m / 1000)
    return f"{int(s // 60)}:{int(s % 60):02d}"


def fmt_date(date_str):
    dt = datetime.strptime(date_str[:10], '%Y-%m-%d')
    meses = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
             'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
    return f"{dt.day} {meses[dt.month-1]} {dt.year}"


@app.route('/')
def index():
    token = get_valid_token()
    if not token:
        return render_template('index.html', connected=False)

    raw = get_all_activities(token)
    raw_rides = [a for a in raw if a['type'] in ('Ride', 'VirtualRide', 'EBikeRide')]

    rides = []
    for a in raw_rides:
        # Local time for hour analysis
        local_str = a.get('start_date_local') or a.get('start_date', '')
        try:
            local_dt = datetime.strptime(local_str[:19], '%Y-%m-%dT%H:%M:%S')
            start_time = local_dt.strftime('%H:%M')
            hour = local_dt.hour
            local_date = local_dt.strftime('%Y-%m-%dT%H:%M:%S')
        except Exception:
            start_time = ''
            hour = 12
            local_date = a.get('start_date', '')

        ride = {
            'id': a['id'],
            'name': a['name'],
            'type': a['type'],
            'distance': a['distance'],
            'km': round(a['distance'] / 1000, 1),
            'moving_time': a['moving_time'],
            'tiempo': fmt_time(a['moving_time']),
            'fecha': fmt_date(a['start_date']),
            'start_date': local_date,
            'start_time': start_time,
            'hour': hour,
            'velocidad': round(a.get('average_speed', 0) * 3.6, 1),
            'max_velocidad': round(a.get('max_speed', 0) * 3.6, 1),
            'desnivel': round(a.get('total_elevation_gain', 0)),
            'ritmo': fmt_pace(a['moving_time'], a['distance']),
            'polyline': (a.get('map') or {}).get('summary_polyline') or '',
            'pulsaciones': round(a['average_heartrate']) if a.get('average_heartrate') else None,
            'max_pulsaciones': round(a['max_heartrate']) if a.get('max_heartrate') else None,
            'calorias': round(a['calories']) if a.get('calories') else None,
        }
        rides.append(ride)

    rides.sort(key=lambda x: x['start_date'], reverse=True)

    total_km = sum(r['distance'] for r in rides) / 1000
    total_seconds = sum(r['moving_time'] for r in rides)
    total_elevation = sum(r['desnivel'] for r in rides)

    best_ride = max(rides, key=lambda x: x['distance']) if rides else None
    best_elev = max(rides, key=lambda x: x['desnivel']) if rides else None

    monthly = {}
    for r in rides:
        m = r['start_date'][:7]
        monthly[m] = monthly.get(m, 0) + r['distance'] / 1000
    months_sorted = sorted(monthly.keys())[-12:]
    chart_labels = [m[5:] + '/' + m[2:4] for m in months_sorted]
    chart_data = [round(monthly.get(m, 0), 1) for m in months_sorted]
    chart_months = months_sorted

    yearly = {}
    for r in rides:
        y = r['start_date'][:4]
        if y not in yearly:
            yearly[y] = {'km': 0, 'rides': 0, 'elevation': 0, 'seconds': 0}
        yearly[y]['km'] += r['distance'] / 1000
        yearly[y]['rides'] += 1
        yearly[y]['elevation'] += r['desnivel']
        yearly[y]['seconds'] += r['moving_time']
    yearly_list = [
        {'year': y, 'km': round(v['km']), 'rides': v['rides'],
         'elevation': round(v['elevation']), 'horas': round(v['seconds'] / 3600, 1)}
        for y, v in sorted(yearly.items(), reverse=True)
    ]

    activities_js = json.dumps({
        str(r['id']): {
            'name': r['name'],
            'type': r['type'],
            'km': r['km'],
            'tiempo': r['tiempo'],
            'fecha': r['fecha'],
            'start_date': r['start_date'],
            'start_time': r['start_time'],
            'hour': r['hour'],
            'moving_time': r['moving_time'],
            'velocidad': r['velocidad'],
            'max_velocidad': r['max_velocidad'],
            'desnivel': r['desnivel'],
            'ritmo': r['ritmo'],
            'pulsaciones': r['pulsaciones'],
            'max_pulsaciones': r['max_pulsaciones'],
            'calorias': r['calorias'],
            'polyline': r['polyline'],
        }
        for r in rides
    })

    return render_template('index.html',
                           connected=True,
                           rides=rides,
                           total_km=round(total_km, 1),
                           total_horas=round(total_seconds / 3600, 1),
                           total_elevation=round(total_elevation),
                           total_rides=len(rides),
                           best_ride=best_ride,
                           best_elev=best_elev,
                           chart_labels=chart_labels,
                           chart_data=chart_data,
                           chart_months=chart_months,
                           yearly_list=yearly_list,
                           activities_js=activities_js)


@app.route('/api/streams/<int:activity_id>')
def get_streams(activity_id):
    cache_file = os.path.join(CACHE_DIR, f'streams_{activity_id}.json')
    if os.path.exists(cache_file):
        with open(cache_file) as f:
            return jsonify(json.load(f))
    token = get_valid_token()
    if not token:
        return jsonify({'error': 'not_authenticated'}), 401
    r = requests.get(
        f'https://www.strava.com/api/v3/activities/{activity_id}/streams',
        headers={'Authorization': f'Bearer {token}'},
        params={'keys': 'latlng,velocity_smooth,altitude', 'key_by_type': 'true'}
    )
    if not r.ok:
        return jsonify({'error': 'strava_error'}), r.status_code
    data = r.json()
    with open(cache_file, 'w') as f:
        json.dump(data, f)
    return jsonify(data)


@app.route('/api/photos/<int:activity_id>')
def get_photos(activity_id):
    cache_file = os.path.join(CACHE_DIR, f'photos_{activity_id}.json')
    if os.path.exists(cache_file):
        with open(cache_file) as f:
            return jsonify(json.load(f))
    token = get_valid_token()
    if not token:
        return jsonify([])
    r = requests.get(
        f'https://www.strava.com/api/v3/activities/{activity_id}/photos',
        headers={'Authorization': f'Bearer {token}'},
        params={'photo_sources': 'true', 'size': 1024}
    )
    urls = []
    if r.ok:
        for p in r.json():
            u = (p.get('urls') or {}).get('1024') or (p.get('urls') or {}).get('600')
            if u:
                urls.append(u)
    with open(cache_file, 'w') as f:
        json.dump(urls, f)
    return jsonify(urls)


@app.route('/connect')
def connect():
    url = (
        f"https://www.strava.com/oauth/authorize"
        f"?client_id={CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={REDIRECT_URI}"
        f"&approval_prompt=force"
        f"&scope=activity:read_all"
    )
    return redirect(url)


@app.route('/callback')
def callback():
    code = request.args.get('code')
    if not code:
        return redirect(url_for('index'))
    r = requests.post('https://www.strava.com/oauth/token', data={
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'code': code,
        'grant_type': 'authorization_code'
    })
    if r.ok:
        save_tokens(r.json())
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True)
