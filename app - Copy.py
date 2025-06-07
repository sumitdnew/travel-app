from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
import requests
import json
import random
from datetime import datetime, timedelta
import os
from urllib.parse import quote
from functools import wraps
import logging

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("python-dotenv not installed. Using environment variables directly.")

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-here-change-in-production')

# Enable CORS for API calls
CORS(app)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# API Keys - NOW PROPERLY SECURED
GOOGLE_PLACES_API_KEY = os.environ.get('GOOGLE_PLACES_API_KEY')
OPENWEATHER_API_KEY = os.environ.get('OPENWEATHER_API_KEY') 
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')

# Configure OpenAI - Compatible with both old and new versions
try:
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
    USE_NEW_OPENAI = True
    logger.info("Using new OpenAI client")
except ImportError:
    try:
        import openai
        openai.api_key = OPENAI_API_KEY
        client = None
        USE_NEW_OPENAI = False
        logger.info("Using legacy OpenAI client")
    except ImportError:
        client = None
        USE_NEW_OPENAI = False
        logger.warning("OpenAI not available")

# In-memory storage (replace with proper database in production)
users_db = {}
trips_db = {}
rate_limit_store = {}

# Subscription tiers and limits
SUBSCRIPTION_LIMITS = {
    'free': {
        'max_days': 3,
        'monthly_trips': 3,
        'features': ['basic_itinerary', 'weather', 'attractions']
    },
    'premium': {
        'max_days': 30,
        'monthly_trips': -1,  # Unlimited
        'features': ['all_features', 'pdf_export', 'calendar_sync', 'offline_maps']
    }
}

class User:
    def __init__(self, google_id, email, name, subscription_tier='free'):
        self.google_id = google_id
        self.email = email
        self.name = name
        self.subscription_tier = subscription_tier
        self.created_at = datetime.now()
        self.trips_this_month = 0
        self.total_trips = 0

def rate_limit(max_requests=10, window_minutes=1):
    """Simple rate limiting decorator"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            client_ip = request.remote_addr
            current_time = datetime.now()
            
            if client_ip not in rate_limit_store:
                rate_limit_store[client_ip] = []
            
            # Clean old requests
            rate_limit_store[client_ip] = [
                req_time for req_time in rate_limit_store[client_ip] 
                if current_time - req_time < timedelta(minutes=window_minutes)
            ]
            
            if len(rate_limit_store[client_ip]) >= max_requests:
                return jsonify({'error': 'Rate limit exceeded. Please try again later.'}), 429
            
            rate_limit_store[client_ip].append(current_time)
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def get_fallback_tips():
    """Fallback tips when AI is unavailable"""
    return [
        "🏠 Book accommodations in advance for better rates",
        "🚇 Use public transportation to save money",
        "🍽️ Try local street food for authentic flavors",
        "💳 Notify your bank before traveling",
        "📱 Download offline maps before you go",
        "🎫 Look for free walking tours and city passes"
    ]

def generate_ai_enhanced_tips(days, people, budget, country, city):
    """Generate AI-enhanced travel recommendations using compatible OpenAI API"""
    if not OPENAI_API_KEY:
        return get_fallback_tips()
    
    daily_budget = budget / days
    if daily_budget < 75:
        budget_category = "budget"
    elif daily_budget < 150:
        budget_category = "mid-range"
    else:
        budget_category = "luxury"
    
    prompt = f"""
    Give me 6 practical travel tips for visiting {city}, {country} on a {budget_category} budget for {days} days with {people} people.
    
    Focus on:
    - Money-saving strategies specific to this destination
    - Local food recommendations and where to find them
    - Transportation tips and cost-effective options
    - Cultural insights and etiquette
    - Hidden gems and off-the-beaten-path experiences
    - Safety advice and common tourist traps to avoid
    
    Format each tip as a short, actionable sentence starting with an emoji. Keep each tip under 60 characters.
    """
    
    try:
        if USE_NEW_OPENAI and client:
            # New OpenAI API
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a local travel expert with insider knowledge. Give practical, specific advice that saves money and enhances the travel experience."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=400,
                temperature=0.7
            )
            ai_tips = response.choices[0].message.content
        elif not USE_NEW_OPENAI and OPENAI_API_KEY:
            # Old OpenAI API
            import openai
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a local travel expert with insider knowledge. Give practical, specific advice that saves money and enhances the travel experience."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=400,
                temperature=0.7
            )
            ai_tips = response.choices[0].message.content
        else:
            return get_fallback_tips()
        
        tips_list = [tip.strip() for tip in ai_tips.split('\n') if tip.strip() and len(tip.strip()) > 10]
        
        # Ensure we have exactly 6 tips
        while len(tips_list) < 6:
            tips_list.extend(get_fallback_tips())
        
        return tips_list[:6]
        
    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        return get_fallback_tips()

def get_ai_destination_insights(city, country):
    """Get AI-powered destination insights with fallback"""
    if not OPENAI_API_KEY:
        return f"Discover the unique charm of {city}, a destination filled with rich culture, amazing food, and unforgettable experiences."
    
    prompt = f"""
    Provide a brief, engaging overview of {city}, {country} for travelers. Include:
    - What makes this destination special and unique
    - Best time to visit and why
    - One must-try local experience that tourists often miss
    
    Keep it under 100 words, inspiring, and informative.
    """
    
    try:
        if USE_NEW_OPENAI and client:
            # New OpenAI API
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a travel writer creating inspiring yet informative destination descriptions. Focus on what makes each place unique."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=150,
                temperature=0.8
            )
            return response.choices[0].message.content.strip()
        elif not USE_NEW_OPENAI and OPENAI_API_KEY:
            # Old OpenAI API
            import openai
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a travel writer creating inspiring yet informative destination descriptions. Focus on what makes each place unique."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=150,
                temperature=0.8
            )
            return response.choices[0].message.content.strip()
        else:
            return f"Discover the unique charm of {city}, a destination filled with rich culture, amazing food, and unforgettable experiences."
        
    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        return f"Discover the unique charm of {city}, a destination filled with rich culture, amazing food, and unforgettable experiences. From historic landmarks to vibrant local markets, this city offers something special for every traveler."

def get_hardcoded_coordinates(city):
    """Hardcoded coordinates for popular cities"""
    city_coordinates = {
        'miami': {'lat': 25.7617, 'lon': -80.1918, 'name': 'Miami', 'country': 'US', 'state': 'Florida'},
        'new orleans': {'lat': 29.9511, 'lon': -90.0715, 'name': 'New Orleans', 'country': 'US', 'state': 'Louisiana'},
        'new york': {'lat': 40.7128, 'lon': -74.0060, 'name': 'New York', 'country': 'US', 'state': 'New York'},
        'los angeles': {'lat': 34.0522, 'lon': -118.2437, 'name': 'Los Angeles', 'country': 'US', 'state': 'California'},
        'chicago': {'lat': 41.8781, 'lon': -87.6298, 'name': 'Chicago', 'country': 'US', 'state': 'Illinois'},
        'london': {'lat': 51.5074, 'lon': -0.1278, 'name': 'London', 'country': 'GB', 'state': 'England'},
        'paris': {'lat': 48.8566, 'lon': 2.3522, 'name': 'Paris', 'country': 'FR', 'state': 'Île-de-France'},
        'tokyo': {'lat': 35.6762, 'lon': 139.6503, 'name': 'Tokyo', 'country': 'JP', 'state': 'Tokyo'},
        'sydney': {'lat': -33.8688, 'lon': 151.2093, 'name': 'Sydney', 'country': 'AU', 'state': 'New South Wales'},
        'berlin': {'lat': 52.5200, 'lon': 13.4050, 'name': 'Berlin', 'country': 'DE', 'state': 'Berlin'},
        'nassau': {'lat': 25.0443, 'lon': -77.3504, 'name': 'Nassau', 'country': 'BS', 'state': 'New Providence'},
        'nicholls town': {'lat': 25.4167, 'lon': -78.0167, 'name': 'Nicholls Town', 'country': 'BS', 'state': 'Andros'}
    }
    
    city_variations = [
        city.lower().strip(),
        city.lower().replace(' ', ''),
        city.lower().replace('-', ' '),
        city.lower().replace('_', ' ')
    ]
    
    for variation in city_variations:
        if variation in city_coordinates:
            logger.info(f"✅ Using hardcoded coordinates for '{variation}'")
            return city_coordinates[variation]
    
    logger.error(f"❌ Could not find coordinates for '{city}'")
    return None

def get_location_coordinates(city, country):
    """Enhanced location lookup with better error handling"""
    logger.info(f"Looking up coordinates for: '{city}', '{country}'")
    
    if not OPENWEATHER_API_KEY:
        logger.warning("OpenWeatherMap API key not configured, using hardcoded coordinates")
        return get_hardcoded_coordinates(city)
    
    city_clean = city.strip().title()
    
    # Try different query formats
    queries = [
        city,
        city_clean,
        f"{city},{country}",
        f"{city_clean},{country}",
        f"{city}, {country}",
        f"{city_clean}, {country}",
    ]
    
    for query in queries:
        try:
            logger.info(f"Trying OpenWeatherMap query: '{query}'")
            geo_url = f"http://api.openweathermap.org/geo/1.0/direct?q={quote(query)}&limit=10&appid={OPENWEATHER_API_KEY}"
            response = requests.get(geo_url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"OpenWeatherMap returned {len(data)} results for '{query}'")
                
                if data:
                    for location in data:
                        if (city.lower() in location['name'].lower() or 
                            location['name'].lower() in city.lower()):
                            result = {
                                'lat': location['lat'],
                                'lon': location['lon'],
                                'name': location['name'],
                                'country': location.get('country', country),
                                'state': location.get('state', '')
                            }
                            logger.info(f"✅ Found matching location: {result}")
                            return result
                    
                    # Use first result if no exact match
                    location = data[0]
                    result = {
                        'lat': location['lat'],
                        'lon': location['lon'],
                        'name': location['name'],
                        'country': location.get('country', country),
                        'state': location.get('state', '')
                    }
                    logger.info(f"✅ Using first result: {result}")
                    return result
                    
        except Exception as e:
            logger.error(f"❌ OpenWeatherMap error for query '{query}': {e}")
            continue
    
    # Fallback to hardcoded coordinates
    return get_hardcoded_coordinates(city)

def get_weather_info(lat, lon):
    """Get weather information with error handling"""
    if not OPENWEATHER_API_KEY:
        return None
        
    try:
        weather_url = f"http://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}&units=metric"
        response = requests.get(weather_url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            return {
                'temperature': round(data['main']['temp']),
                'description': data['weather'][0]['description'].title(),
                'humidity': data['main']['humidity'],
                'feels_like': round(data['main']['feels_like'])
            }
    except Exception as e:
        logger.error(f"Error getting weather info: {e}")
    
    return None

def search_places_nearby(lat, lon, place_type, radius=15000):
    """Search for places using Google Places API"""
    if not GOOGLE_PLACES_API_KEY:
        logger.warning(f"Google Places API key not configured, returning empty list for {place_type}")
        return []
        
    try:
        places_url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json"
        params = {
            'location': f"{lat},{lon}",
            'radius': radius,
            'type': place_type,
            'key': GOOGLE_PLACES_API_KEY
        }
        
        response = requests.get(places_url, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            places = []
            
            for place in data.get('results', [])[:15]:
                place_info = {
                    'name': place.get('name', ''),
                    'rating': place.get('rating', 0),
                    'user_ratings_total': place.get('user_ratings_total', 0),
                    'price_level': place.get('price_level', 2),
                    'vicinity': place.get('vicinity', ''),
                    'place_id': place.get('place_id', ''),
                    'google_maps_url': f"https://www.google.com/maps/place/?q=place_id:{place.get('place_id', '')}" if place.get('place_id') else '',
                    'types': place.get('types', [])
                }
                places.append(place_info)
            
            return places
    except Exception as e:
        logger.error(f"Error searching places: {e}")
    
    return []

def search_hotels_nearby(lat, lon, radius=15000):
    """Search for hotels using Google Places API"""
    return search_places_nearby(lat, lon, 'lodging', radius)

def get_booking_links(place_name, city):
    """Generate booking/ticket links for attractions"""
    search_query = f"{place_name} {city}".replace(' ', '%20')
    
    return {
        'viator': f"https://www.viator.com/searchResults/all?text={search_query}",
        'getyourguide': f"https://www.getyourguide.com/s/?q={search_query}",
        'expedia': f"https://www.expedia.com/things-to-do/search?location={search_query}",
        'tripadvisor': f"https://www.tripadvisor.com/Search?q={search_query}"
    }

def estimate_daily_budget(country, budget_level):
    """Estimate daily budget based on location and level"""
    base_costs = {'budget': 50, 'mid': 100, 'luxury': 200}
    country_multipliers = {'US': 1.2, 'United States': 1.2, 'GB': 1.1, 'United Kingdom': 1.1, 'DE': 0.9, 'Germany': 0.9, 'BS': 1.3, 'Bahamas': 1.3}
    
    multiplier = country_multipliers.get(country, 1.0)
    return base_costs[budget_level] * multiplier

def generate_real_itinerary(days, people, total_budget, country, city, start_date=None):
    """Generate a comprehensive AI-enhanced travel itinerary"""
    
    # Get location coordinates
    location_info = get_location_coordinates(city, country)
    if not location_info:
        return {"error": f"Could not find location information for {city}, {country}. Please try a different city or check spelling."}
    
    # Get weather information
    weather_info = get_weather_info(location_info['lat'], location_info['lon'])
    
    # Calculate budget
    daily_budget = total_budget / days
    
    # Determine budget category
    if daily_budget < 75:
        budget_category = "budget"
    elif daily_budget < 150:
        budget_category = "mid"
    else:
        budget_category = "luxury"
    
    logger.info(f"Searching for places near {city}...")
    
    # Get comprehensive places data
    attractions = search_places_nearby(
        location_info['lat'], location_info['lon'], 
        'tourist_attraction'
    )
    logger.info(f"Found {len(attractions)} attractions")
    
    restaurants = search_places_nearby(
        location_info['lat'], location_info['lon'], 
        'restaurant'
    )
    logger.info(f"Found {len(restaurants)} restaurants")
    
    museums = search_places_nearby(
        location_info['lat'], location_info['lon'], 
        'museum'
    )
    logger.info(f"Found {len(museums)} museums")
    
    # Get hotels
    hotels = search_hotels_nearby(
        location_info['lat'], location_info['lon']
    )
    logger.info(f"Found {len(hotels)} hotels")
    
    # Generate check-in/check-out dates
    check_in_date = start_date or (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    check_out_date = (datetime.strptime(check_in_date, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")
    
    # Get AI-enhanced content
    ai_tips = generate_ai_enhanced_tips(days, people, total_budget, country, city)
    ai_insights = get_ai_destination_insights(city, country)
    
    # Create sample activities if no real data available
    if not attractions and not restaurants:
        logger.info("No places found via API, creating sample itinerary")
        sample_activities = [
            {'name': 'Local Beach', 'rating': 4.5, 'user_ratings_total': 100, 'vicinity': 'Waterfront area', 'types': ['tourist_attraction']},
            {'name': 'Historic Downtown', 'rating': 4.2, 'user_ratings_total': 85, 'vicinity': 'City center', 'types': ['tourist_attraction']},
            {'name': 'Local Market', 'rating': 4.0, 'user_ratings_total': 60, 'vicinity': 'Market district', 'types': ['tourist_attraction']}
        ]
        sample_restaurants = [
            {'name': 'Local Seafood Restaurant', 'rating': 4.3, 'user_ratings_total': 120, 'vicinity': 'Harbor area', 'price_level': 2},
            {'name': 'Traditional Cafe', 'rating': 4.1, 'user_ratings_total': 90, 'vicinity': 'Main street', 'price_level': 1},
            {'name': 'Beachside Grill', 'rating': 4.4, 'user_ratings_total': 150, 'vicinity': 'Beach front', 'price_level': 3}
        ]
        attractions = sample_activities
        restaurants = sample_restaurants
    
    # Combine all activities
    all_activities = attractions + museums
    
    # Sort by rating to get best places first
    all_activities.sort(key=lambda x: x.get('rating', 0), reverse=True)
    restaurants.sort(key=lambda x: x.get('rating', 0), reverse=True)
    hotels.sort(key=lambda x: x.get('rating', 0), reverse=True)
    
    # Generate daily itinerary with detailed information
    itinerary = []
    used_activities = set()
    used_restaurants = set()
    
    for day in range(1, days + 1):
        # Select 2-3 activities for the day
        available_activities = [a for a in all_activities if a['name'] not in used_activities]
        day_activities = []
        
        activities_count = min(2, len(available_activities))
        if activities_count > 0:
            selected = available_activities[:activities_count]
            for activity in selected:
                activity_info = {
                    'name': activity['name'],
                    'rating': activity.get('rating', 0),
                    'reviews_count': activity.get('user_ratings_total', 0),
                    'address': activity.get('vicinity', ''),
                    'types': activity.get('types', []),
                    'phone': activity.get('phone', ''),
                    'website': activity.get('website', ''),
                    'google_maps_url': activity.get('google_maps_url', ''),
                    'google_url': activity.get('google_url', ''),
                    'opening_hours': activity.get('opening_hours_text', []),
                    'booking_links': get_booking_links(activity['name'], city)
                }
                day_activities.append(activity_info)
                used_activities.add(activity['name'])
        
        # Select restaurant for the day
        available_restaurants = [r for r in restaurants if r['name'] not in used_restaurants]
        restaurant_info = None
        
        if available_restaurants:
            selected_restaurant = available_restaurants[0]  # Best rated available
            restaurant_info = {
                'name': selected_restaurant['name'],
                'rating': selected_restaurant.get('rating', 0),
                'reviews_count': selected_restaurant.get('user_ratings_total', 0),
                'price_level': selected_restaurant.get('price_level', 2),
                'address': selected_restaurant.get('vicinity', ''),
                'phone': selected_restaurant.get('phone', ''),
                'website': selected_restaurant.get('website', ''),
                'google_maps_url': selected_restaurant.get('google_maps_url', ''),
                'google_url': selected_restaurant.get('google_url', ''),
                'opening_hours': selected_restaurant.get('opening_hours_text', []),
                'cuisine_types': [t.replace('_', ' ').title() for t in selected_restaurant.get('types', []) if 'food' in t or 'restaurant' in t or 'meal' in t]
            }
            used_restaurants.add(selected_restaurant['name'])
        
        # Estimate daily cost
        estimated_cost = estimate_daily_budget(location_info['country'], budget_category)
        if people > 2:
            estimated_cost *= (people * 0.85)  # Group discount
        
        day_plan = {
            "day": day,
            "date": (datetime.now() + timedelta(days=day-1)).strftime("%Y-%m-%d"),
            "activities": day_activities,
            "restaurant": restaurant_info,
            "estimated_cost": round(estimated_cost, 2)
        }
        itinerary.append(day_plan)
    
    total_estimated_cost = sum(day["estimated_cost"] for day in itinerary)
    
    return {
        "destination": f"{location_info['name']}, {location_info['country']}",
        "location_info": location_info,
        "weather_info": weather_info,
        "ai_powered": True,
        "ai_insights": ai_insights,
        "total_days": days,
        "total_people": people,
        "budget": total_budget,
        "daily_budget": round(daily_budget, 2),
        "budget_category": budget_category.title(),
        "money_saving_tips": ai_tips,
        "itinerary": itinerary,
        "total_estimated_cost": round(total_estimated_cost, 2),
        "budget_status": "Within Budget" if total_estimated_cost <= total_budget else "Over Budget",
        "attractions_found": len(attractions),
        "restaurants_found": len(restaurants),
        "museums_found": len(museums),
        "hotels": hotels[:10] if hotels else [],  # Top 10 hotels
        "check_in_date": check_in_date,
        "check_out_date": check_out_date
    }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/countries')
def get_countries():
    """Get list of countries with caching - SIMPLIFIED VERSION"""
    logger.info("Countries API endpoint called")
    
    # Use reliable fallback countries first
    fallback_countries = [
        "United States", "United Kingdom", "Canada", "Australia", "Germany",
        "France", "Japan", "Italy", "Spain", "Mexico", "Brazil", "India",
        "Thailand", "Netherlands", "Sweden", "Norway", "Denmark", "Switzerland",
        "Austria", "Belgium", "Portugal", "Greece", "Poland", "Czech Republic",
        "Hungary", "Ireland", "Finland", "New Zealand", "South Korea", "Singapore",
        "Bahamas", "Jamaica", "Costa Rica", "Chile", "Argentina", "Colombia",
        "Peru", "Ecuador", "Panama", "Croatia", "Slovenia", "Estonia", "Latvia"
    ]
    
    try:
        # Try to get from REST Countries API with shorter timeout
        response = requests.get('https://restcountries.com/v3.1/all?fields=name', timeout=3)
        if response.status_code == 200:
            data = response.json()
            countries = []
            for country in data:
                if 'name' in country and 'common' in country['name']:
                    name = country['name']['common']
                    if len(name) < 50:  # Filter out very long names
                        countries.append(name)
            
            if len(countries) > 50:  # Only use API result if we got a good response
                logger.info(f"Loaded {len(countries)} countries from REST Countries API")
                return jsonify(sorted(countries))
    except Exception as e:
        logger.warning(f"REST Countries API failed: {e}")
    
    # Always return fallback countries if API fails
    logger.info(f"Using fallback countries: {len(fallback_countries)} countries")
    return jsonify(sorted(fallback_countries))

@app.route('/api/cities/<country>')
def get_cities_for_country(country):
    """Get cities for a country with improved handling"""
    logger.info(f"Getting cities for country: {country}")
    
    # Enhanced popular cities database
    popular_cities = {
        "United States": [
            "New York", "Los Angeles", "Chicago", "Houston", "Phoenix", "Philadelphia",
            "San Antonio", "San Diego", "Dallas", "San Jose", "Austin", "Jacksonville",
            "San Francisco", "Columbus", "Charlotte", "Fort Worth", "Indianapolis",
            "Seattle", "Denver", "Boston", "Detroit", "Nashville", "Memphis", "Portland",
            "Las Vegas", "Miami", "Atlanta", "New Orleans", "Tampa", "Orlando"
        ],
        "United Kingdom": [
            "London", "Birmingham", "Manchester", "Glasgow", "Liverpool", "Leeds",
            "Sheffield", "Edinburgh", "Bristol", "Cardiff", "Belfast", "Leicester",
            "Brighton", "Newcastle", "Nottingham", "Cambridge", "Oxford", "Bath"
        ],
        "Bahamas": [
            "Nassau", "Freeport", "Nicholls Town", "Alice Town", "Clarence Town", 
            "Cockburn Town", "Cooper's Town", "Dunmore Town", "Governor's Harbour",
            "High Rock", "Marsh Harbour", "Matthew Town", "Rock Sound"
        ],
        "Canada": [
            "Toronto", "Montreal", "Vancouver", "Calgary", "Edmonton", "Ottawa", 
            "Winnipeg", "Quebec City", "Hamilton", "Victoria", "Halifax", "Saskatoon"
        ],
        "Germany": [
            "Berlin", "Hamburg", "Munich", "Cologne", "Frankfurt", "Stuttgart",
            "Düsseldorf", "Leipzig", "Dortmund", "Essen", "Bremen", "Dresden"
        ],
        "France": [
            "Paris", "Marseille", "Lyon", "Toulouse", "Nice", "Nantes", "Montpellier",
            "Strasbourg", "Bordeaux", "Lille", "Rennes", "Reims", "Toulon", "Grenoble"
        ],
        "Japan": [
            "Tokyo", "Osaka", "Kyoto", "Yokohama", "Nagoya", "Sapporo", "Fukuoka",
            "Kobe", "Hiroshima", "Sendai", "Kawasaki", "Chiba", "Nara", "Kanazawa"
        ],
        "Italy": [
            "Rome", "Milan", "Naples", "Turin", "Palermo", "Genoa", "Bologna",
            "Florence", "Venice", "Verona", "Catania", "Bari", "Messina", "Padua"
        ],
        "Spain": [
            "Madrid", "Barcelona", "Valencia", "Seville", "Zaragoza", "Málaga",
            "Murcia", "Palma", "Bilbao", "Alicante", "Granada", "Córdoba", "Vigo"
        ],
        "Australia": [
            "Sydney", "Melbourne", "Brisbane", "Perth", "Adelaide", "Gold Coast",
            "Newcastle", "Canberra", "Sunshine Coast", "Wollongong", "Hobart", "Geelong"
        ],
        "Mexico": [
            "Mexico City", "Guadalajara", "Monterrey", "Puebla", "Tijuana", "León",
            "Juárez", "Torreón", "Querétaro", "San Luis Potosí", "Mérida", "Mexicali"
        ],
        "Brazil": [
            "São Paulo", "Rio de Janeiro", "Brasília", "Salvador", "Fortaleza", "Belo Horizonte",
            "Manaus", "Curitiba", "Recife", "Goiânia", "Belém", "Porto Alegre"
        ]
    }
    
    # Return hardcoded cities if available
    if country in popular_cities:
        logger.info(f"Found {len(popular_cities[country])} cities for {country}")
        return jsonify(popular_cities[country])
    
    # Try Google Places API for other countries
    if GOOGLE_PLACES_API_KEY:
        try:
            places_url = f"https://maps.googleapis.com/maps/api/place/textsearch/json"
            params = {
                'query': f"major cities in {country}",
                'type': 'locality',
                'key': GOOGLE_PLACES_API_KEY
            }
            
            response = requests.get(places_url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                cities = []
                
                for place in data.get('results', [])[:20]:
                    city_name = place.get('name', '')
                    if city_name and any(t in place.get('types', []) for t in ['locality', 'administrative_area_level_1']):
                        cities.append(city_name)
                
                unique_cities = list(set(cities))
                if len(unique_cities) > 0:
                    logger.info(f"Found {len(unique_cities)} cities for {country} via Google Places")
                    return jsonify(sorted(unique_cities))
        
        except Exception as e:
            logger.error(f"Error fetching cities for {country}: {e}")
    
    # Final fallback: return some generic cities
    fallback_cities = ["Capital City", "Main City", "Downtown", "City Center", "Metropolitan Area"]
    logger.warning(f"Using fallback cities for {country}")
    return jsonify(fallback_cities)
    
    # Try Google Places API for other countries
    if GOOGLE_PLACES_API_KEY:
        try:
            places_url = f"https://maps.googleapis.com/maps/api/place/textsearch/json"
            params = {
                'query': f"major cities in {country}",
                'type': 'locality',
                'key': GOOGLE_PLACES_API_KEY
            }
            
            response = requests.get(places_url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                cities = []
                
                for place in data.get('results', [])[:20]:
                    city_name = place.get('name', '')
                    if city_name and any(t in place.get('types', []) for t in ['locality', 'administrative_area_level_1']):
                        cities.append(city_name)
                
                unique_cities = list(set(cities))
                return jsonify(sorted(unique_cities))
        
        except Exception as e:
            logger.error(f"Error fetching cities for {country}: {e}")
    
    return jsonify([])

@app.route('/generate', methods=['POST'])
@rate_limit(max_requests=5, window_minutes=1)
def generate():
    """Generate travel itinerary with enhanced security and validation"""
    try:
        data = request.get_json()
        
        # Enhanced input validation
        try:
            days = int(data.get('days', 1))
            people = int(data.get('people', 1))
            budget = float(data.get('budget', 100))
            country = data.get('country', '').strip()
            city = data.get('city', '').strip()
        except (ValueError, TypeError) as e:
            return jsonify({"error": "Invalid input format. Please check your values."}), 400
        
        # Validate ranges
        if not (1 <= days <= 30):
            return jsonify({"error": "Days must be between 1 and 30"}), 400
        if not (1 <= people <= 20):
            return jsonify({"error": "People must be between 1 and 20"}), 400
        if not (50 <= budget <= 100000):
            return jsonify({"error": "Budget must be between $50 and $100,000"}), 400
        if not all([country, city]):
            return jsonify({"error": "Please fill in all fields with valid values"}), 400
        
        # Check authentication and subscription limits
        auth_header = request.headers.get('Authorization')
        user = None
        if auth_header:
            try:
                token = auth_header.replace('Bearer ', '')
                user = users_db.get(token)
            except:
                pass
        
        # Demo limits for unauthenticated users
        if not user:
            if days > 3:
                return jsonify({
                    "error": "Sign in required for trips longer than 3 days",
                    "upgrade_required": True,
                    "message": "Create a free account to plan longer trips, or upgrade to Premium for unlimited planning"
                }), 401
        
        logger.info(f"Generating itinerary for {city}, {country} - {days} days, {people} people, ${budget}")
        
        # Generate the itinerary using existing logic
        itinerary = generate_real_itinerary(days, people, budget, country, city)
        
        if "error" in itinerary:
            return jsonify(itinerary), 400
        
        # Track trip creation
        if user:
            user.trips_this_month += 1
            user.total_trips += 1
            
            # Store trip in database
            trip_id = f"trip_{len(trips_db) + 1}"
            trips_db[trip_id] = {
                'user_id': user.google_id,
                'destination': f"{city}, {country}",
                'days': days,
                'budget': budget,
                'created_at': datetime.now(),
                'itinerary_data': itinerary
            }
        
        # Add premium upgrade prompts for free users
        if not user or user.subscription_tier == 'free':
            itinerary['upgrade_prompts'] = {
                'pdf_export': 'Upgrade to Premium to export your itinerary as PDF',
                'calendar_sync': 'Sync your trip to Google Calendar with Premium',
                'offline_maps': 'Download offline maps with Premium subscription',
                'unlimited_trips': 'Create unlimited trips with Premium'
            }
        
        return jsonify(itinerary)
        
    except Exception as e:
        logger.error(f"Generation error: {e}")
        return jsonify({"error": "An unexpected error occurred. Please try again."}), 500

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy", 
        "app": "TripCraft AI-Powered",
        "version": "2.0",
        "timestamp": datetime.now().isoformat()
    })

if __name__ == '__main__':
    logger.info("Starting Enhanced TripCraft app...")
    logger.info("Security improvements:")
    logger.info("  ✅ Environment variables for API keys")
    logger.info("  ✅ Rate limiting")
    logger.info("  ✅ Input validation")
    logger.info("  ✅ Modern OpenAI API compatibility")
    logger.info("  ✅ Enhanced error handling")
    logger.info("  ✅ Proper logging")
    logger.info("API endpoints:")
    logger.info("  Countries: http://localhost:5000/api/countries")
    logger.info("  Cities: http://localhost:5000/api/cities/<country>")
    logger.info("  Generate: http://localhost:5000/generate")
    logger.info("  Main app: http://localhost:5000/")
    app.run(debug=False, host='0.0.0.0', port=5000)