from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import re
from datetime import datetime
from typing import Optional, List

# Create FastAPI app
app = FastAPI(
    title="VPN Location API",
    description="Professional API for location-based VPN configuration",
    version="1.0.0"
)

# Add CORS middleware for Flutter/web apps
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure properly in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load and clean CSV data
try:
    df = pd.read_csv('data/zip_code_database.csv')
    # Only use active (non-decommissioned) locations
    df = df[df['decommissioned'] == 0]
    print(f"✅ Loaded {len(df)} active zip codes")
except Exception as e:
    print(f"❌ Error loading CSV: {e}")
    df = pd.DataFrame()

# Your VPN server configuration
VPN_SERVER_IP = "3.149.140.244"
VPN_SERVER_PORT = 1194
VPN_PROTOCOL = "udp"

def validate_zip_code(zip_code: str) -> bool:
    """Validate zip code format"""
    return bool(re.match(r'^\d{5}$', zip_code))

@app.get("/api/vpn/config")
def get_vpn_config(
    zip_code: Optional[str] = Query(None, description="5-digit ZIP code"),
    city: Optional[str] = Query(None, description="City name"),
    state: Optional[str] = Query(None, description="2-letter state code"),
    client_name: str = Query("mobile-client", description="VPN client identifier")
):
    """Get VPN configuration based on location"""
    
    # Validate input
    if not zip_code and not (city and state):
        raise HTTPException(
            status_code=400, 
            detail="Must provide either 'zip_code' or both 'city' and 'state'"
        )
    
    # Validate formats
    if zip_code and not validate_zip_code(zip_code):
        raise HTTPException(status_code=400, detail="Invalid ZIP code format. Use 5 digits.")
    
    if state and not validate_state_code(state):
        raise HTTPException(status_code=400, detail="Invalid state code. Use 2 letters (e.g., TX)")
    
    # Search for location
    try:
        if zip_code:
            location = df[df['zip'] == int(zip_code)]
            search_params = f"ZIP {zip_code}"
        else:
            location = df[
                (df['primary_city'].str.lower() == city.lower()) & 
                (df['state'].str.upper() == state.upper())
            ]
            search_params = f"{city}, {state.upper()}"
        
        if location.empty:
            raise HTTPException(
                status_code=404, 
                detail=f"No location found for {search_params}"
            )
        
        # Get the most populous location if multiple matches
        loc = location.loc[location['irs_estimated_population'].idxmax()]
        
        # Generate VPN configuration
        config_content = f"""client
dev tun
proto {VPN_PROTOCOL}
remote {VPN_SERVER_IP} {VPN_SERVER_PORT}
resolv-retry infinite
nobind
persist-key
persist-tun
remote-cert-tls server
auth SHA512
ignore-unknown-option block-outside-dns
verb 3

# Client Configuration
# Name: {client_name}
# Location: {loc['primary_city']}, {loc['state']} {int(loc['zip'])}
# County: {loc['county']}
# Timezone: {loc['timezone']}
# Generated: {datetime.now().isoformat()}

# Production note: Real certificates would be embedded below
# <ca>...</ca>
# <cert>...</cert>
# <key>...</key>
# <tls-crypt>...</tls-crypt>
"""
        
        return {
            "success": True,
            "client_name": client_name,
            "config": config_content,
            "location": {
                "city": loc['primary_city'],
                "state": loc['state'],
                "zip_code": int(loc['zip']),
                "county": loc['county'],
                "timezone": loc['timezone'],
                "coordinates": {
                    "latitude": float(loc['latitude']),
                    "longitude": float(loc['longitude'])
                },
                "population": int(loc['irs_estimated_population'])
            },
            "server": {
                "ip": VPN_SERVER_IP,
                "port": VPN_SERVER_PORT,
                "protocol": VPN_PROTOCOL
            },
            "generated_at": datetime.now().isoformat()
        }
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid input: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

@app.get("/api/locations/search")
def search_locations(
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(20, ge=1, le=100, description="Maximum results")
):
    """Search locations by city or state name"""
    
    try:
        # Search in cities and states
        city_matches = df[df['primary_city'].str.contains(q, case=False, na=False)]
        state_matches = df[df['state'].str.contains(q, case=False, na=False)]
        
        # Combine and remove duplicates
        all_matches = pd.concat([city_matches, state_matches]).drop_duplicates()
        
        # Group by city/state and aggregate
        grouped = all_matches.groupby(['primary_city', 'state']).agg({
            'zip': 'count',
            'irs_estimated_population': 'sum',
            'latitude': 'first',
            'longitude': 'first',
            'county': 'first'
        }).reset_index()
        
        # Sort by population and limit results
        grouped = grouped.sort_values('irs_estimated_population', ascending=False).head(limit)
        
        results = []
        for _, row in grouped.iterrows():
            results.append({
                "city": row['primary_city'],
                "state": row['state'],
                "zip_count": int(row['zip']),
                "total_population": int(row['irs_estimated_population']),
                "county": row['county'],
                "coordinates": {
                    "latitude": float(row['latitude']),
                    "longitude": float(row['longitude'])
                }
            })
        
        return {
            "query": q,
            "total_found": len(results),
            "results": results
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search error: {str(e)}")

@app.get("/api/locations/zip/{zip_code}")
def get_location_by_zip(zip_code: str):
    """Get detailed location information by ZIP code"""
    
    if not validate_zip_code(zip_code):
        raise HTTPException(status_code=400, detail="Invalid ZIP code format")
    
    try:
        location = df[df['zip'] == int(zip_code)]
        
        if location.empty:
            raise HTTPException(status_code=404, detail=f"ZIP code {zip_code} not found")
        
        loc = location.iloc[0]
        
        return {
            "zip_code": int(loc['zip']),
            "type": loc['type'],
            "city": loc['primary_city'],
            "state": loc['state'],
            "county": loc['county'],
            "timezone": loc['timezone'],
            "area_codes": loc['area_codes'],
            "coordinates": {
                "latitude": float(loc['latitude']),
                "longitude": float(loc['longitude'])
            },
            "population": int(loc['irs_estimated_population']),
            "acceptable_cities": loc['acceptable_cities'] if pd.notna(loc['acceptable_cities']) else None
        }
        
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ZIP code")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

@app.get("/api/locations/nearby")
def get_nearby_locations(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    radius_miles: float = Query(25, ge=1, le=100, description="Search radius in miles")
):
    """Find locations within radius of coordinates"""
    
    try:
        # Simple distance calculation (approximate)
        lat_delta = radius_miles / 69.0  # 1 degree ≈ 69 miles
        lon_delta = radius_miles / (69.0 * abs(latitude) * 0.017453293)  # adjust for latitude
        
        nearby = df[
            (df['latitude'] >= latitude - lat_delta) &
            (df['latitude'] <= latitude + lat_delta) &
            (df['longitude'] >= longitude - lon_delta) &
            (df['longitude'] <= longitude + lon_delta)
        ]
        
        # Calculate actual distances and sort
        nearby = nearby.copy()
        nearby['distance'] = ((nearby['latitude'] - latitude) ** 2 + 
                            (nearby['longitude'] - longitude) ** 2) ** 0.5 * 69
        
        nearby = nearby[nearby['distance'] <= radius_miles].sort_values('distance').head(50)
        
        results = []
        for _, row in nearby.iterrows():
            results.append({
                "city": row['primary_city'],
                "state": row['state'],
                "zip_code": int(row['zip']),
                "distance_miles": round(float(row['distance']), 2),
                "population": int(row['irs_estimated_population']),
                "coordinates": {
                    "latitude": float(row['latitude']),
                    "longitude": float(row['longitude'])
                }
            })
        
        return {
            "center": {"latitude": latitude, "longitude": longitude},
            "radius_miles": radius_miles,
            "total_found": len(results),
            "locations": results
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search error: {str(e)}")



def validate_state_code(state: str) -> bool:
    """Validate state code format"""
    return bool(re.match(r'^[A-Z]{2}$', state.upper()))



@app.get("/")
def home():
    """API home with basic information"""
    return {
        "name": "VPN Location API",
        "version": "1.0.0",
        "description": "Get VPN configurations based on your location",
        "endpoints": {
            "vpn_config": "/api/vpn/config",
            "search": "/api/locations/search",
            "zip_lookup": "/api/locations/zip/{zip_code}",
            "health": "/api/health",
            "docs": "/docs"
        }
    }

@app.get("/api/health")
def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "database_records": len(df),
        "vpn_server": VPN_SERVER_IP
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)